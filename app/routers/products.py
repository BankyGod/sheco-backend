from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import Actor, get_current_actor, require_admin
from app.schemas.common import ProductSaveIn
from app.services import inventory as inventory_svc

router = APIRouter(prefix="/products", tags=["products"])


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


@router.post("")
def create_or_update_product(
    body: ProductSaveIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_admin),
):
    payload = {
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
    result = inventory_svc.save_product(db, payload, actor)
    db.commit()
    return result
