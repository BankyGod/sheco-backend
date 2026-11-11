from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import Actor, get_current_actor, require_admin
from app.schemas.common import CompleteSaleIn, SyncSalesIn, VoidSaleIn
from app.services import sales as sales_svc

router = APIRouter(prefix="/sales", tags=["sales"])


def _sale_payload(body: CompleteSaleIn) -> dict:
    return {
        "id": body.id,
        "items": [
            {
                "product_id": line.product_id,
                "quantity": line.quantity,
                "prescription_ref": line.prescription_ref,
            }
            for line in body.items
        ],
        "payment": {
            "method": body.payment.method,
            "amount_tendered": body.payment.amount_tendered,
            "change": body.payment.change,
            "network": body.payment.network,
            "reference": body.payment.reference,
        },
        "offline": body.offline,
        "receipt_number": body.receipt_number,
        "device_id": body.device_id,
        "created_at": body.created_at,
    }


@router.get("")
def list_sales(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    return sales_svc.list_sales(db, actor)


@router.post("/sync")
def sync_sales(
    body: SyncSalesIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    result = sales_svc.sync_sales(db, [_sale_payload(s) for s in body.sales], actor)
    db.commit()
    return result


@router.post("")
def complete_sale(
    body: CompleteSaleIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    result = sales_svc.complete_sale(db, _sale_payload(body), actor, from_sync=False)
    db.commit()
    return result


@router.get("/{sale_id}")
def get_sale(
    sale_id: str,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    sale = sales_svc.get_sale(db, sale_id, actor)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    return sale


@router.post("/{sale_id}/void")
def void_sale(
    sale_id: str,
    body: VoidSaleIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_admin),
):
    result = sales_svc.void_sale(db, sale_id, body.reason, actor)
    db.commit()
    return result
