from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import Actor, require_admin
from app.schemas.common import AdjustStockIn, RestockIn
from app.services import inventory as inventory_svc

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/alerts")
def stock_alerts(
    db: Session = Depends(get_db),
    _: Actor = Depends(require_admin),
):
    return inventory_svc.get_stock_alerts(db)


@router.post("/restock")
def restock(
    body: RestockIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_admin),
):
    result = inventory_svc.restock(
        db,
        {
            "product_id": body.product_id,
            "batch_number": body.batch_number,
            "expiry_date": body.expiry_date,
            "quantity": body.quantity,
            "cost_price": body.cost_price,
            "supplier": body.supplier,
        },
        actor,
    )
    db.commit()
    return result


@router.post("/adjustments")
def adjust_stock(
    body: AdjustStockIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_admin),
):
    result = inventory_svc.adjust_stock(
        db,
        {
            "batch_id": body.batch_id,
            "new_quantity": body.new_quantity,
            "reason": body.reason,
        },
        actor,
    )
    db.commit()
    return result
