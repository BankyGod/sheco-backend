from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Batch, Product, StockMovement
from app.services.audit import add_audit
from app.services.ids import new_id
from app.services.settings_svc import get_or_create_settings


def _today() -> date:
    return datetime.now(timezone.utc).date()


def is_expired(batch: Batch, as_of: date | None = None) -> bool:
    return batch.expiry_date < (as_of or _today())


def days_until_expiry(batch: Batch) -> int:
    return (batch.expiry_date - _today()).days


def get_sellable_quantity(db: Session, product_id: str) -> int:
    batches = (
        db.query(Batch)
        .filter(Batch.product_id == product_id, Batch.quantity_remaining > 0)
        .all()
    )
    return sum(b.quantity_remaining for b in batches if not is_expired(b))


def get_available_batches(db: Session, product_id: str) -> list[Batch]:
    batches = (
        db.query(Batch)
        .filter(Batch.product_id == product_id, Batch.quantity_remaining > 0)
        .order_by(Batch.expiry_date.asc())
        .all()
    )
    return [b for b in batches if not is_expired(b)]


def serialize_product(db: Session, product: Product, *, for_salesperson: bool = False) -> dict:
    settings = get_or_create_settings(db)
    product_batches = db.query(Batch).filter(Batch.product_id == product.id).all()
    available_qty = get_sellable_quantity(db, product.id)
    total_qty = sum(b.quantity_remaining for b in product_batches)
    expired_qty = sum(b.quantity_remaining for b in product_batches if is_expired(b))
    expiring_soon = any(
        not is_expired(b)
        and b.quantity_remaining > 0
        and days_until_expiry(b) <= settings.expiry_alert_days
        for b in product_batches
    )
    base = {
        "id": product.id,
        "name": product.name,
        "genericName": product.generic_name,
        "category": product.category,
        "unit": product.unit,
        "sellingPrice": product.selling_price,
        "reorderLevel": product.reorder_level,
        "prescriptionOnly": product.prescription_only,
        "active": product.active,
        "availableQty": available_qty,
        "totalQty": total_qty,
        "lowStock": available_qty <= product.reorder_level,
        "expiringSoon": expiring_soon,
        "expiredQty": expired_qty,
    }
    if for_salesperson:
        return base

    base["costPrice"] = product.cost_price
    base["unitProfit"] = product.selling_price - product.cost_price
    base["batches"] = [
        {
            "id": b.id,
            "productId": b.product_id,
            "batchNumber": b.batch_number,
            "expiryDate": b.expiry_date.isoformat(),
            "quantityReceived": b.quantity_received,
            "quantityRemaining": b.quantity_remaining,
            "costPrice": b.cost_price,
            "supplier": b.supplier,
            "dateReceived": b.date_received.isoformat(),
            "expired": is_expired(b),
            "daysToExpiry": days_until_expiry(b),
        }
        for b in product_batches
    ]
    return base


def list_products(
    db: Session,
    *,
    include_inactive: bool = False,
    for_salesperson: bool = False,
) -> list[dict]:
    q = db.query(Product)
    if not include_inactive:
        q = q.filter(Product.active.is_(True))
    products = q.order_by(Product.name.asc()).all()
    return [serialize_product(db, p, for_salesperson=for_salesperson) for p in products]


def save_product(db: Session, payload: dict, actor) -> dict:
    if payload.get("id"):
        product = db.get(Product, payload["id"])
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        price_changed = (
            product.selling_price != payload["selling_price"]
            or product.cost_price != payload["cost_price"]
        )
        product.name = payload["name"]
        product.generic_name = payload["generic_name"]
        product.category = payload["category"]
        product.unit = payload["unit"]
        product.cost_price = payload["cost_price"]
        product.selling_price = payload["selling_price"]
        product.reorder_level = payload["reorder_level"]
        product.prescription_only = payload["prescription_only"]
        product.active = payload.get("active", product.active)
        action = "price_change" if price_changed else "product_update"
        record = (
            f"{product.name} cost/selling price updated"
            if price_changed
            else f"Updated product {product.name}"
        )
        add_audit(db, user_id=actor.id, device_id=actor.device_id, action=action, record=record)
        db.flush()
        return serialize_product(db, product, for_salesperson=False)

    product = Product(
        id=new_id("p"),
        name=payload["name"],
        generic_name=payload["generic_name"],
        category=payload["category"],
        unit=payload["unit"],
        cost_price=payload["cost_price"],
        selling_price=payload["selling_price"],
        reorder_level=payload["reorder_level"],
        prescription_only=payload["prescription_only"],
        active=payload.get("active", True),
    )
    db.add(product)
    add_audit(
        db,
        user_id=actor.id,
        device_id=actor.device_id,
        action="product_create",
        record=f"Created product {product.name}",
    )
    db.flush()
    return serialize_product(db, product, for_salesperson=False)


def restock(db: Session, data: dict, actor) -> dict:
    product = db.get(Product, data["product_id"])
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    batch = Batch(
        id=new_id("b"),
        product_id=data["product_id"],
        batch_number=data["batch_number"],
        expiry_date=data["expiry_date"],
        quantity_received=data["quantity"],
        quantity_remaining=data["quantity"],
        cost_price=data["cost_price"],
        supplier=data.get("supplier") or "",
        date_received=_today(),
    )
    db.add(batch)
    db.add(
        StockMovement(
            batch_id=batch.id,
            movement_type="restock",
            quantity=data["quantity"],
            reason="Restock",
            user_id=actor.id,
        )
    )
    add_audit(
        db,
        user_id=actor.id,
        device_id=actor.device_id,
        action="restock",
        record=f"Restocked {product.name} batch {batch.batch_number} (+{data['quantity']})",
    )
    db.flush()
    return {
        "id": batch.id,
        "productId": batch.product_id,
        "batchNumber": batch.batch_number,
        "expiryDate": batch.expiry_date.isoformat(),
        "quantityReceived": batch.quantity_received,
        "quantityRemaining": batch.quantity_remaining,
        "costPrice": batch.cost_price,
        "supplier": batch.supplier,
        "dateReceived": batch.date_received.isoformat(),
    }


def adjust_stock(db: Session, data: dict, actor) -> dict:
    batch = db.get(Batch, data["batch_id"])
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="A reason is required")
    old_qty = batch.quantity_remaining
    new_qty = int(data["new_quantity"])
    delta = new_qty - old_qty
    batch.quantity_remaining = new_qty
    product = db.get(Product, batch.product_id)
    db.add(
        StockMovement(
            batch_id=batch.id,
            movement_type="adjustment",
            quantity=delta,
            reason=reason,
            user_id=actor.id,
        )
    )
    add_audit(
        db,
        user_id=actor.id,
        device_id=actor.device_id,
        action="stock_adjustment",
        record=(
            f"Adjusted {product.name if product else batch.product_id} batch "
            f"{batch.batch_number}: {old_qty} → {new_qty}. Reason: {reason}"
        ),
    )
    db.flush()
    return {
        "id": batch.id,
        "productId": batch.product_id,
        "batchNumber": batch.batch_number,
        "expiryDate": batch.expiry_date.isoformat(),
        "quantityReceived": batch.quantity_received,
        "quantityRemaining": batch.quantity_remaining,
        "costPrice": batch.cost_price,
        "supplier": batch.supplier,
        "dateReceived": batch.date_received.isoformat(),
    }


def get_stock_alerts(db: Session) -> dict:
    settings = get_or_create_settings(db)
    products = db.query(Product).filter(Product.active.is_(True)).all()
    low_stock = []
    expiring_soon = []
    expired = []
    for product in products:
        available_qty = get_sellable_quantity(db, product.id)
        if available_qty <= product.reorder_level:
            low_stock.append(
                {
                    "product": serialize_product(db, product, for_salesperson=False),
                    "availableQty": available_qty,
                }
            )
        batches = (
            db.query(Batch)
            .filter(Batch.product_id == product.id, Batch.quantity_remaining > 0)
            .all()
        )
        for batch in batches:
            batch_payload = {
                "id": batch.id,
                "productId": batch.product_id,
                "batchNumber": batch.batch_number,
                "expiryDate": batch.expiry_date.isoformat(),
                "quantityReceived": batch.quantity_received,
                "quantityRemaining": batch.quantity_remaining,
                "costPrice": batch.cost_price,
                "supplier": batch.supplier,
                "dateReceived": batch.date_received.isoformat(),
            }
            product_payload = serialize_product(db, product, for_salesperson=False)
            if is_expired(batch):
                expired.append({"product": product_payload, "batch": batch_payload})
            elif days_until_expiry(batch) <= settings.expiry_alert_days:
                expiring_soon.append(
                    {
                        "product": product_payload,
                        "batch": batch_payload,
                        "daysToExpiry": days_until_expiry(batch),
                    }
                )
    return {"lowStock": low_stock, "expiringSoon": expiring_soon, "expired": expired}


def allocate_batches_for_sale(
    db: Session,
    product_id: str,
    quantity: int,
    *,
    allow_overshoot: bool = False,
) -> list[dict]:
    batches = get_available_batches(db, product_id)
    remaining = quantity
    allocations: list[dict] = []
    for batch in batches:
        if remaining <= 0:
            break
        take = min(batch.quantity_remaining, remaining)
        allocations.append(
            {
                "batchId": batch.id,
                "quantity": take,
                "unitCostPrice": batch.cost_price,
            }
        )
        remaining -= take

    if remaining > 0:
        if not allow_overshoot:
            raise HTTPException(
                status_code=400,
                detail="Insufficient sellable stock (expired batches are excluded)",
            )
        # Overshoot: allocate remainder against the soonest non-expired batch if any,
        # else the oldest batch for the product so the sale can be flagged for review.
        fallback = (
            batches[0]
            if batches
            else db.query(Batch)
            .filter(Batch.product_id == product_id)
            .order_by(Batch.expiry_date.asc())
            .first()
        )
        if not fallback:
            raise HTTPException(status_code=400, detail="No batch available for offline overshoot")
        allocations.append(
            {
                "batchId": fallback.id,
                "quantity": remaining,
                "unitCostPrice": fallback.cost_price,
            }
        )
    return allocations


def deduct_allocations(db: Session, allocations: list[dict], *, user_id: str) -> bool:
    """Deduct stock. Returns True if any batch went negative (needs review)."""
    needs_review = False
    for alloc in allocations:
        batch = db.get(Batch, alloc["batchId"])
        if not batch:
            raise HTTPException(status_code=400, detail="Stock changed during sale")
        batch.quantity_remaining -= alloc["quantity"]
        if batch.quantity_remaining < 0:
            needs_review = True
        db.add(
            StockMovement(
                batch_id=batch.id,
                movement_type="sale",
                quantity=-alloc["quantity"],
                reason="Sale",
                user_id=user_id,
            )
        )
    return needs_review


def restore_sale_items(db: Session, items: list, *, user_id: str, reason: str) -> None:
    for item in items:
        batch = db.get(Batch, item.batch_id)
        if batch:
            batch.quantity_remaining += item.quantity
            db.add(
                StockMovement(
                    batch_id=batch.id,
                    movement_type="return",
                    quantity=item.quantity,
                    reason=reason,
                    user_id=user_id,
                )
            )
