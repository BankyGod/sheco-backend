from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import Actor, get_current_actor, require_admin
from app.schemas.common import ProductBulkIn, ProductBulkOut, ProductBulkRowResult, ProductSaveIn
from app.services import inventory as inventory_svc

router = APIRouter(prefix="/products", tags=["products"])


def _product_payload(body: ProductSaveIn) -> dict:
    return {
        "id": body.id,
        "name": body.name,
        "generic_name": body.generic_name,
        "category": body.category,
        "unit": body.unit,
        "cost_price": body.cost_price,
        "selling_price": body.selling_price,
        "reorder_level": body.reorder_level,
        "prescription_only": body.prescription_only,
        "active": body.active,
    }


@router.get("")
def list_products(
    include_inactive: bool = Query(default=False, alias="includeInactive"),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    for_salesperson = actor.role == "salesperson"
    return inventory_svc.list_products(
        db,
        include_inactive=include_inactive if actor.role == "super_admin" else False,
        for_salesperson=for_salesperson,
    )


@router.post("/bulk")
def bulk_create_products(
    body: ProductBulkIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_admin),
):
    if not body.products:
        raise HTTPException(status_code=400, detail="No products to import")
    if len(body.products) > 500:
        raise HTTPException(status_code=400, detail="Import is limited to 500 products at a time")

    results: list[ProductBulkRowResult] = []
    created = 0
    failed = 0

    for index, item in enumerate(body.products, start=1):
        try:
            if item.cost_price < 0:
                raise ValueError("Cost price cannot be negative")
            if item.selling_price <= 0:
                raise ValueError("Selling price must be greater than 0")
            if item.selling_price < item.cost_price:
                raise ValueError("Selling price should be at least the cost price")
            if item.reorder_level < 0:
                raise ValueError("Reorder level cannot be negative")

            with db.begin_nested():
                product = inventory_svc.save_product(db, _product_payload(item), actor)
            results.append(
                ProductBulkRowResult(row=index, name=item.name, ok=True, product=product)
            )
            created += 1
        except Exception as exc:  # noqa: BLE001 - collect per-row import errors
            failed += 1
            detail = getattr(exc, "detail", None) or str(exc)
            results.append(
                ProductBulkRowResult(row=index, name=item.name, ok=False, error=str(detail))
            )

    db.commit()
    return ProductBulkOut(created=created, failed=failed, results=results)


@router.post("")
def create_or_update_product(
    body: ProductSaveIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_admin),
):
    result = inventory_svc.save_product(db, _product_payload(body), actor)
    db.commit()
    return result
