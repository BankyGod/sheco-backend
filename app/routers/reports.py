from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import Actor, require_admin
from app.schemas.common import SettingsUpdateIn
from app.services import sales as sales_svc
from app.services.audit import add_audit
from app.services.settings_svc import get_or_create_settings

router = APIRouter(tags=["reports"])


def _serialize_settings(row) -> dict:
    return {
        "discountLimitPercent": row.discount_limit_percent,
        "sessionTimeoutMinutes": row.session_timeout_minutes,
        "offlineUnlockDays": row.offline_unlock_days,
        "expiryAlertDays": row.expiry_alert_days,
        "pharmacyName": getattr(row, "pharmacy_name", None) or "Sheco Pharmacy",
        "pharmacyPhone": getattr(row, "pharmacy_phone", None) or "",
        "pharmacyAddress": getattr(row, "pharmacy_address", None) or "",
        "pharmacyEmail": getattr(row, "pharmacy_email", None) or "",
        "receiptFooter": getattr(row, "receipt_footer", None)
        or "Thank you for shopping with Sheco",
        "momoAccountName": getattr(row, "momo_account_name", None) or "",
        "momoAccountNumber": getattr(row, "momo_account_number", None) or "",
    }


@router.get("/dashboard/stats")
def dashboard_stats(
    db: Session = Depends(get_db),
    _: Actor = Depends(require_admin),
):
    return sales_svc.get_dashboard_stats(db)


@router.get("/reports/sales")
def report_sales(
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    _: Actor = Depends(require_admin),
):
    return sales_svc.get_report_data(db, from_date=from_date, to_date=to_date)


@router.get("/audit")
def audit_log(
    query: str = Query(default=""),
    db: Session = Depends(get_db),
    _: Actor = Depends(require_admin),
):
    return sales_svc.list_audit(db, query)


@router.get("/settings")
def get_settings(
    db: Session = Depends(get_db),
    _: Actor = Depends(require_admin),
):
    row = get_or_create_settings(db)
    return _serialize_settings(row)


@router.patch("/settings")
def update_settings(
    body: SettingsUpdateIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_admin),
):
    row = get_or_create_settings(db)
    mapping = {
        "discount_limit_percent": body.discount_limit_percent,
        "session_timeout_minutes": body.session_timeout_minutes,
        "offline_unlock_days": body.offline_unlock_days,
        "expiry_alert_days": body.expiry_alert_days,
        "pharmacy_name": body.pharmacy_name,
        "pharmacy_phone": body.pharmacy_phone,
        "pharmacy_address": body.pharmacy_address,
        "pharmacy_email": body.pharmacy_email,
        "receipt_footer": body.receipt_footer,
        "momo_account_name": body.momo_account_name,
        "momo_account_number": body.momo_account_number,
    }
    for attr, value in mapping.items():
        if value is not None:
            setattr(row, attr, value.strip() if isinstance(value, str) else value)

    add_audit(
        db,
        user_id=actor.id,
        device_id=actor.device_id,
        action="settings",
        record="Updated system settings",
    )
    db.commit()
    db.refresh(row)
    return _serialize_settings(row)


@router.post("/admin/purge-data")
def purge_data(
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_admin),
):
    """Clear inventory, sales, audits, and non-admin users. Keeps one admin + settings."""
    from app.services.purge import purge_operational_data

    result = purge_operational_data(db, actor=actor)
    db.commit()
    return {"ok": True, **result}
