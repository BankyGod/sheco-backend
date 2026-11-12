from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from app.models import Product, Sale, SaleItem, User
from app.services.audit import add_audit
from app.services.ids import new_id
from app.services.inventory import (
    allocate_batches_for_sale,
    deduct_allocations,
    restore_sale_items,
)
from app.services.settings_svc import get_or_create_settings


def _salesperson_name(sale: Sale) -> str:
    if getattr(sale, "salesperson", None) is not None:
        return sale.salesperson.name
    return sale.salesperson_id


def _serialize_sale(sale: Sale, *, for_salesperson: bool = False) -> dict:
    items = []
    for item in sale.items:
        row = {
            "productId": item.product_id,
            "batchId": item.batch_id,
            "quantity": item.quantity,
            "unitSellingPrice": item.unit_selling_price,
            "prescriptionRef": item.prescription_ref,
        }
        if not for_salesperson:
            row["unitCostPrice"] = item.unit_cost_price
        items.append(row)

    return {
        "id": sale.id,
        "receiptNumber": sale.receipt_number,
        "deviceId": sale.device_id,
        "salespersonId": sale.salesperson_id,
        "salespersonName": _salesperson_name(sale),
        "createdAt": sale.created_at.isoformat(),
        "total": sale.total,
        "status": sale.status,
        "voidReason": sale.void_reason,
        "payment": {
            "method": sale.payment_method,
            "amountTendered": sale.amount_tendered,
            "change": sale.change_amount,
            "network": sale.momo_network,
            "reference": sale.momo_reference,
        },
        "items": items,
        "syncFlag": sale.sync_flag,
        "needsReview": sale.needs_review,
        "reviewReason": getattr(sale, "review_reason", None),
    }


def list_sales(db: Session, actor) -> list[dict]:
    q = (
        db.query(Sale)
        .options(joinedload(Sale.items), joinedload(Sale.salesperson))
        .order_by(Sale.created_at.desc())
    )
    if actor.role == "salesperson":
        q = q.filter(Sale.salesperson_id == actor.id)
    sales = q.all()
    for_salesperson = actor.role == "salesperson"
    return [_serialize_sale(s, for_salesperson=for_salesperson) for s in sales]


def get_sale(db: Session, sale_id: str, actor) -> dict | None:
    sale = (
        db.query(Sale)
        .options(joinedload(Sale.items), joinedload(Sale.salesperson))
        .filter(Sale.id == sale_id)
        .first()
    )
    if not sale:
        return None
    if actor.role == "salesperson" and sale.salesperson_id != actor.id:
        return None
    return _serialize_sale(sale, for_salesperson=actor.role == "salesperson")


def _next_receipt_number(db: Session, device_id: str) -> str:
    settings = get_or_create_settings(db)
    settings.receipt_seq += 1
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{device_id}-{day}-{settings.receipt_seq:04d}"


def _resolve_salesperson(db: Session, payload: dict, actor) -> User:
    requested_id = payload.get("salesperson_id")
    if not requested_id or requested_id == actor.id:
        return actor.user or db.get(User, actor.id)

    if actor.role != "super_admin" and requested_id != actor.id:
        raise HTTPException(
            status_code=403,
            detail="Only admins can sync sales for another salesperson",
        )

    seller = db.get(User, requested_id)
    if not seller:
        raise HTTPException(status_code=400, detail="Original salesperson not found")
    return seller


def complete_sale(
    db: Session,
    payload: dict,
    actor,
    *,
    from_sync: bool = False,
) -> dict:
    sale_id = payload.get("id") or new_id("sale")
    existing = (
        db.query(Sale)
        .options(joinedload(Sale.items), joinedload(Sale.salesperson))
        .filter(Sale.id == sale_id)
        .first()
    )
    if existing:
        return _serialize_sale(existing, for_salesperson=actor.role == "salesperson")

    offline = bool(payload.get("offline") or from_sync)
    allow_overshoot = from_sync
    line_items: list[dict] = []
    total = 0
    review_reasons: list[str] = []

    for line in payload["items"]:
        product = db.get(Product, line["product_id"])
        if not product or not product.active:
            raise HTTPException(status_code=400, detail="Product unavailable")
        if product.prescription_only and not line.get("prescription_ref"):
            raise HTTPException(
                status_code=400,
                detail=f"{product.name} requires a prescription reference",
            )

        queued_price = line.get("unit_selling_price")
        if (
            from_sync
            and queued_price is not None
            and int(queued_price) != int(product.selling_price)
        ):
            review_reasons.append(
                f"Price changed for {product.name}: queued {int(queued_price)} vs server {product.selling_price}"
            )

        allocations = allocate_batches_for_sale(
            db,
            line["product_id"],
            int(line["quantity"]),
            allow_overshoot=allow_overshoot,
        )
        for alloc in allocations:
            # Conflict policy: always charge current server selling price.
            line_items.append(
                {
                    "product_id": line["product_id"],
                    "batch_id": alloc["batchId"],
                    "quantity": alloc["quantity"],
                    "unit_selling_price": product.selling_price,
                    "unit_cost_price": alloc["unitCostPrice"],
                    "prescription_ref": line.get("prescription_ref"),
                }
            )
            total += product.selling_price * alloc["quantity"]

    salesperson = _resolve_salesperson(db, payload, actor)
    needs_review = deduct_allocations(
        db,
        [{"batchId": i["batch_id"], "quantity": i["quantity"]} for i in line_items],
        user_id=salesperson.id,
    )
    if needs_review:
        review_reasons.append("Stock overshoot during offline sync")
    if from_sync and offline and not review_reasons:
        # Mark offline origin lightly only when nothing else flagged.
        pass

    payment = payload["payment"]
    device_id = payload.get("device_id") or actor.device_id
    created_at = payload.get("created_at") or datetime.now(timezone.utc)
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))

    receipt_number = payload.get("receipt_number") or _next_receipt_number(db, device_id)
    if payload.get("receipt_number"):
        clash = (
            db.query(Sale)
            .filter(Sale.receipt_number == receipt_number, Sale.id != sale_id)
            .first()
        )
        if clash:
            receipt_number = _next_receipt_number(db, device_id)
            review_reasons.append("Receipt number regenerated due to conflict")

    sale = Sale(
        id=sale_id,
        receipt_number=receipt_number,
        device_id=device_id,
        salesperson_id=salesperson.id,
        created_at=created_at,
        total=total,
        discount=0,
        status="completed",
        void_reason=None,
        sync_flag="synced" if not from_sync else "synced_offline",
        needs_review=bool(review_reasons) or needs_review,
        review_reason="; ".join(review_reasons) if review_reasons else None,
        payment_method=payment["method"],
        amount_tendered=payment["amount_tendered"],
        change_amount=payment.get("change") or 0,
        momo_network=payment.get("network"),
        momo_reference=payment.get("reference"),
    )
    db.add(sale)
    for item in line_items:
        db.add(
            SaleItem(
                sale_id=sale.id,
                product_id=item["product_id"],
                batch_id=item["batch_id"],
                quantity=item["quantity"],
                unit_selling_price=item["unit_selling_price"],
                unit_cost_price=item["unit_cost_price"],
                prescription_ref=item["prescription_ref"],
            )
        )

    sale.salesperson = salesperson

    add_audit(
        db,
        user_id=actor.id,
        device_id=device_id,
        action="sale",
        record=(
            f"Receipt {sale.receipt_number}"
            + (" (synced offline)" if from_sync else "")
            + (f" — review: {sale.review_reason}" if sale.needs_review else "")
        ),
    )
    db.flush()
    return _serialize_sale(sale, for_salesperson=actor.role == "salesperson")


def void_sale(db: Session, sale_id: str, reason: str, actor) -> dict:
    sale = (
        db.query(Sale)
        .options(joinedload(Sale.items), joinedload(Sale.salesperson))
        .filter(Sale.id == sale_id)
        .first()
    )
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    if sale.status == "voided":
        raise HTTPException(status_code=400, detail="Sale already voided")
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="A reason is required to void a sale")

    restore_sale_items(db, sale.items, user_id=actor.id, reason=reason)
    sale.status = "voided"
    sale.void_reason = reason
    add_audit(
        db,
        user_id=actor.id,
        device_id=actor.device_id,
        action="void",
        record=f"Receipt {sale.receipt_number} — {reason}",
    )
    db.flush()
    return _serialize_sale(sale, for_salesperson=False)


def sync_sales(db: Session, sales_payload: list[dict], actor) -> dict:
    """Sync sales one-by-one. Commit successes; keep failures in the client queue."""
    synced = 0
    already = 0
    failed = 0
    results = []
    for payload in sales_payload:
        sale_id = payload.get("id") or ""
        try:
            existing = db.get(Sale, sale_id) if sale_id else None
            if existing:
                already += 1
                results.append(
                    {
                        "id": existing.id,
                        "status": "already_exists",
                        "sale": _serialize_sale(
                            existing, for_salesperson=actor.role == "salesperson"
                        ),
                    }
                )
                continue

            sale = complete_sale(db, {**payload, "offline": True}, actor, from_sync=True)
            db.commit()
            synced += 1
            results.append({"id": sale["id"], "status": "synced", "sale": sale})
        except HTTPException as exc:
            db.rollback()
            failed += 1
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            results.append({"id": sale_id, "status": "failed", "error": detail})
        except Exception as exc:  # noqa: BLE001 — surface per-sale errors to client
            db.rollback()
            failed += 1
            results.append({"id": sale_id, "status": "failed", "error": str(exc)})
    return {
        "synced": synced,
        "alreadyExists": already,
        "failed": failed,
        "results": results,
    }


def list_sales_needing_review(db: Session) -> list[dict]:
    sales = (
        db.query(Sale)
        .options(joinedload(Sale.items), joinedload(Sale.salesperson))
        .filter(Sale.needs_review.is_(True), Sale.status == "completed")
        .order_by(Sale.created_at.desc())
        .all()
    )
    return [_serialize_sale(s, for_salesperson=False) for s in sales]


def clear_sale_review(db: Session, sale_id: str, actor, *, note: str | None = None) -> dict:
    sale = (
        db.query(Sale)
        .options(joinedload(Sale.items), joinedload(Sale.salesperson))
        .filter(Sale.id == sale_id)
        .first()
    )
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    sale.needs_review = False
    cleared = note.strip() if note else "Reviewed and cleared"
    prior = sale.review_reason or ""
    sale.review_reason = f"{prior} | Cleared: {cleared}".strip(" |")
    add_audit(
        db,
        user_id=actor.id,
        device_id=actor.device_id,
        action="sale_review",
        record=f"Cleared review for {sale.receipt_number}: {cleared}",
    )
    db.flush()
    return _serialize_sale(sale, for_salesperson=False)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


PERIOD_OPTIONS = {
    "today": "Today",
    "this-week": "This week",
    "last-week": "Last week",
    "this-month": "This month",
    "last-month": "Last month",
    "this-year": "This year",
    "all-time": "All time",
}


def _period_bounds(period: str, now: datetime) -> tuple[datetime | None, datetime]:
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now

    if period == "today":
        return start_of_today, end

    if period == "this-week":
        # Monday-start week
        start = start_of_today - timedelta(days=start_of_today.weekday())
        return start, end

    if period == "last-week":
        this_week_start = start_of_today - timedelta(days=start_of_today.weekday())
        start = this_week_start - timedelta(days=7)
        return start, this_week_start

    if period == "this-month":
        return start_of_today.replace(day=1), end

    if period == "last-month":
        first_this_month = start_of_today.replace(day=1)
        last_month_end = first_this_month
        if first_this_month.month == 1:
            start = first_this_month.replace(year=first_this_month.year - 1, month=12)
        else:
            start = first_this_month.replace(month=first_this_month.month - 1)
        return start, last_month_end

    if period == "this-year":
        return start_of_today.replace(month=1, day=1), end

    if period == "all-time":
        return None, end

    # default this-week
    start = start_of_today - timedelta(days=start_of_today.weekday())
    return start, end


def _bucket_sales(sales: list[Sale], *, start: datetime, end: datetime, mode: str) -> list[dict]:
    week_days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    rows: list[dict] = []

    def profit_for(day_sales: list[Sale]) -> tuple[int, int]:
        revenue = sum(s.total for s in day_sales)
        cost = sum(
            item.unit_cost_price * item.quantity for s in day_sales for item in s.items
        )
        return revenue, revenue - cost

    if mode == "hour":
        for hour in range(24):
            bucket_start = start.replace(hour=hour, minute=0, second=0, microsecond=0)
            bucket_end = bucket_start + timedelta(hours=1)
            day_sales = [s for s in sales if bucket_start <= _as_utc(s.created_at) < bucket_end]
            revenue, profit = profit_for(day_sales)
            label = bucket_start.strftime("%I%p").lstrip("0").lower()
            rows.append(
                {
                    "label": label,
                    "day": label,
                    "month": label,
                    "sales": len(day_sales),
                    "revenue": revenue / 100,
                    "profit": profit / 100,
                }
            )
        return rows

    if mode == "day":
        cursor = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end_day = end.replace(hour=0, minute=0, second=0, microsecond=0)
        while cursor <= end_day:
            next_day = cursor + timedelta(days=1)
            day_sales = [s for s in sales if cursor <= _as_utc(s.created_at) < next_day]
            revenue, profit = profit_for(day_sales)
            js_day = (cursor.weekday() + 1) % 7
            label = week_days[js_day] if (end_day - start).days <= 7 else cursor.strftime("%d %b")
            rows.append(
                {
                    "label": label,
                    "day": label,
                    "month": label,
                    "sales": len(day_sales),
                    "revenue": revenue / 100,
                    "profit": profit / 100,
                }
            )
            cursor = next_day
        return rows

    # month buckets
    cursor = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_month = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cursor <= end_month:
        if cursor.month == 12:
            next_month = cursor.replace(year=cursor.year + 1, month=1)
        else:
            next_month = cursor.replace(month=cursor.month + 1)
        month_sales = [s for s in sales if cursor <= _as_utc(s.created_at) < next_month]
        revenue, profit = profit_for(month_sales)
        label = cursor.strftime("%b")
        rows.append(
            {
                "label": label,
                "day": label,
                "month": label,
                "sales": len(month_sales),
                "revenue": revenue / 100,
                "profit": profit / 100,
            }
        )
        cursor = next_month
    return rows


def get_dashboard_stats(db: Session, period: str = "this-week") -> dict:
    if period not in PERIOD_OPTIONS:
        period = "this-week"

    sales = db.query(Sale).options(joinedload(Sale.items)).all()
    completed = [s for s in sales if s.status == "completed"]
    voided = [s for s in sales if s.status == "voided"]

    now = datetime.now(timezone.utc)
    start, end = _period_bounds(period, now)
    period_sales = [
        s
        for s in completed
        if (start is None or _as_utc(s.created_at) >= start) and _as_utc(s.created_at) < end
    ]

    period_revenue = sum(s.total for s in period_sales)
    cash_revenue = sum(s.total for s in period_sales if s.payment_method == "cash")
    momo_revenue = sum(s.total for s in period_sales if s.payment_method == "momo")

    if period == "today":
        series_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        series = _bucket_sales(period_sales, start=series_start, end=end, mode="hour")
        trend = series
        volume_label = "Hourly sales volume"
    elif period in {"this-week", "last-week"}:
        assert start is not None
        series_end = end - timedelta(microseconds=1) if period == "last-week" else end
        series = _bucket_sales(completed, start=start, end=series_end, mode="day")
        # last 6 months trend for revenue chart context
        month_start = (now.replace(day=1) - timedelta(days=150)).replace(day=1)
        trend = _bucket_sales(completed, start=month_start, end=end, mode="month")[-6:]
        volume_label = "Daily sales volume"
    elif period in {"this-month", "last-month"}:
        assert start is not None
        series_end = end - timedelta(microseconds=1) if period == "last-month" else end
        series = _bucket_sales(completed, start=start, end=series_end, mode="day")
        month_start = (now.replace(day=1) - timedelta(days=150)).replace(day=1)
        trend = _bucket_sales(completed, start=month_start, end=end, mode="month")[-6:]
        volume_label = "Daily sales volume"
    elif period == "this-year":
        assert start is not None
        series = _bucket_sales(completed, start=start, end=end, mode="month")
        trend = series
        volume_label = "Monthly sales volume"
    else:  # all-time
        oldest = min((_as_utc(s.created_at) for s in completed), default=now)
        series_start = oldest.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        series = _bucket_sales(completed, start=series_start, end=end, mode="month")
        trend = series[-12:] if len(series) > 12 else series
        volume_label = "Monthly sales volume"

    return {
        "period": period,
        "periodLabel": PERIOD_OPTIONS[period],
        "volumeLabel": volume_label,
        "todayCount": len(period_sales),
        "todayRevenue": period_revenue,
        "cashRevenue": cash_revenue,
        "momoRevenue": momo_revenue,
        "voidedCount": len(voided),
        "completedCount": len(completed),
        "weekly": series,
        "monthly": trend,
        "series": series,
        "trend": trend,
    }


def get_report_data(db: Session, *, from_date: str | None, to_date: str | None) -> dict:
    sales = (
        db.query(Sale)
        .options(joinedload(Sale.items), joinedload(Sale.salesperson))
        .filter(Sale.status == "completed")
        .all()
    )
    if from_date:
        sales = [s for s in sales if _as_utc(s.created_at).date().isoformat() >= from_date]
    if to_date:
        sales = [s for s in sales if _as_utc(s.created_at).date().isoformat() <= to_date]

    by_salesperson: dict[str, dict] = {}
    for sale in sales:
        key = sale.salesperson_id
        if key not in by_salesperson:
            by_salesperson[key] = {
                "salespersonId": key,
                "salespersonName": _salesperson_name(sale),
                "count": 0,
                "revenue": 0,
                "profit": 0,
            }
        by_salesperson[key]["count"] += 1
        by_salesperson[key]["revenue"] += sale.total
        by_salesperson[key]["profit"] += sum(
            (item.unit_selling_price - item.unit_cost_price) * item.quantity
            for item in sale.items
        )

    cash = sum(s.total for s in sales if s.payment_method == "cash")
    momo = sum(s.total for s in sales if s.payment_method == "momo")
    momo_txns = [
        {
            "receiptNumber": s.receipt_number,
            "network": s.momo_network,
            "reference": s.momo_reference,
            "amount": s.total,
            "createdAt": s.created_at.isoformat(),
            "salespersonId": s.salesperson_id,
            "salespersonName": _salesperson_name(s),
        }
        for s in sales
        if s.payment_method == "momo"
    ]
    profit = sum(
        (item.unit_selling_price - item.unit_cost_price) * item.quantity
        for s in sales
        for item in s.items
    )

    return {
        "sales": [_serialize_sale(s, for_salesperson=False) for s in sales],
        "totals": {
            "count": len(sales),
            "revenue": sum(s.total for s in sales),
            "cash": cash,
            "momo": momo,
            "profit": profit,
        },
        "bySalesperson": list(by_salesperson.values()),
        "momoTxns": momo_txns,
    }


def list_audit(db: Session, query: str = "") -> list[dict]:
    from app.models import AuditLog

    entries = db.query(AuditLog).order_by(AuditLog.time.desc()).all()
    users = {u.id: u.name for u in db.query(User).all()}
    q = (query or "").strip().lower()
    out = []
    for entry in entries:
        user_name = users.get(entry.user_id, entry.user_id)
        row = {
            "id": entry.id,
            "userId": entry.user_id,
            "deviceId": entry.device_id,
            "action": entry.action,
            "record": entry.record,
            "time": entry.time.isoformat(),
            "userName": user_name,
        }
        if not q or q in entry.action.lower() or q in entry.record.lower() or q in user_name.lower():
            out.append(row)
    return out
