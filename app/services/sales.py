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
    }


def list_sales(db: Session, actor) -> list[dict]:
    q = db.query(Sale).options(joinedload(Sale.items)).order_by(Sale.created_at.desc())
    if actor.role == "salesperson":
        q = q.filter(Sale.salesperson_id == actor.id)
    sales = q.all()
    for_salesperson = actor.role == "salesperson"
    return [_serialize_sale(s, for_salesperson=for_salesperson) for s in sales]


def get_sale(db: Session, sale_id: str, actor) -> dict | None:
    sale = (
        db.query(Sale)
        .options(joinedload(Sale.items))
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


def complete_sale(
    db: Session,
    payload: dict,
    actor,
    *,
    from_sync: bool = False,
) -> dict:
    sale_id = payload.get("id") or new_id("sale")
    existing = db.get(Sale, sale_id)
    if existing:
        return _serialize_sale(existing, for_salesperson=actor.role == "salesperson")

    offline = bool(payload.get("offline") or from_sync)
    allow_overshoot = from_sync
    line_items: list[dict] = []
    total = 0

    for line in payload["items"]:
        product = db.get(Product, line["product_id"])
        if not product or not product.active:
            raise HTTPException(status_code=400, detail="Product unavailable")
        if product.prescription_only and not line.get("prescription_ref"):
            raise HTTPException(
                status_code=400,
                detail=f"{product.name} requires a prescription reference",
            )
        allocations = allocate_batches_for_sale(
            db,
            line["product_id"],
            int(line["quantity"]),
            allow_overshoot=allow_overshoot,
        )
        for alloc in allocations:
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

    needs_review = deduct_allocations(
        db,
        [{"batchId": i["batch_id"], "quantity": i["quantity"]} for i in line_items],
        user_id=actor.id,
    )

    payment = payload["payment"]
    device_id = payload.get("device_id") or actor.device_id
    created_at = payload.get("created_at") or datetime.now(timezone.utc)
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))

    receipt_number = payload.get("receipt_number") or _next_receipt_number(db, device_id)

    sale = Sale(
        id=sale_id,
        receipt_number=receipt_number,
        device_id=device_id,
        salesperson_id=actor.id,
        created_at=created_at,
        total=total,
        discount=0,
        status="completed",
        void_reason=None,
        sync_flag="synced",
        needs_review=needs_review or (offline and needs_review),
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

    if needs_review:
        sale.needs_review = True

    add_audit(
        db,
        user_id=actor.id,
        device_id=device_id,
        action="sale",
        record=f"Receipt {sale.receipt_number}" + (" (synced)" if from_sync else ""),
    )
    db.flush()
    return _serialize_sale(sale, for_salesperson=actor.role == "salesperson")


def void_sale(db: Session, sale_id: str, reason: str, actor) -> dict:
    sale = (
        db.query(Sale)
        .options(joinedload(Sale.items))
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
    synced = 0
    results = []
    for payload in sales_payload:
        # Force sync path: accept even if stock is short and flag for review
        result = complete_sale(db, {**payload, "offline": True}, actor, from_sync=True)
        results.append(result)
        synced += 1
    return {"synced": synced, "sales": results}


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_dashboard_stats(db: Session) -> dict:
    sales = db.query(Sale).options(joinedload(Sale.items)).all()
    completed = [s for s in sales if s.status == "completed"]
    voided = [s for s in sales if s.status == "voided"]

    start_of_today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_sales = [s for s in completed if _as_utc(s.created_at) >= start_of_today]

    today_revenue = sum(s.total for s in today_sales)
    cash_revenue = sum(s.total for s in today_sales if s.payment_method == "cash")
    momo_revenue = sum(s.total for s in today_sales if s.payment_method == "momo")

    week_days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    chronological = []
    for i in range(6, -1, -1):
        day = start_of_today - timedelta(days=i)
        next_day = day + timedelta(days=1)
        day_sales = [s for s in completed if day <= _as_utc(s.created_at) < next_day]
        # Python weekday: Mon=0 ... Sun=6; JS getDay(): Sun=0
        js_day = (day.weekday() + 1) % 7
        chronological.append(
            {
                "day": week_days[js_day],
                "sales": len(day_sales),
                "revenue": sum(s.total for s in day_sales) / 100,
            }
        )

    monthly = []
    now = datetime.now(timezone.utc)
    for i in range(6):
        month_offset = 5 - i
        year = now.year
        month = now.month - month_offset
        while month <= 0:
            month += 12
            year -= 1
        label = datetime(year, month, 1).strftime("%b")
        month_sales = [
            s
            for s in completed
            if _as_utc(s.created_at).year == year and _as_utc(s.created_at).month == month
        ]
        revenue = sum(s.total for s in month_sales)
        cost = sum(
            item.unit_cost_price * item.quantity for s in month_sales for item in s.items
        )
        monthly.append(
            {
                "month": label,
                "revenue": revenue / 100,
                "profit": (revenue - cost) / 100,
            }
        )

    return {
        "todayCount": len(today_sales),
        "todayRevenue": today_revenue,
        "cashRevenue": cash_revenue,
        "momoRevenue": momo_revenue,
        "voidedCount": len(voided),
        "completedCount": len(completed),
        "weekly": chronological,
        "monthly": monthly,
    }


def get_report_data(db: Session, *, from_date: str | None, to_date: str | None) -> dict:
    sales = (
        db.query(Sale)
        .options(joinedload(Sale.items))
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
