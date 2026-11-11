from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import Actor, require_admin
from app.schemas.common import SettingsOut, SettingsUpdateIn
from app.services import sales as sales_svc
from app.services.audit import add_audit
from app.services.settings_svc import get_or_create_settings

router = APIRouter(tags=["reports"])


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
    return {
        "discountLimitPercent": row.discount_limit_percent,
        "sessionTimeoutMinutes": row.session_timeout_minutes,
        "offlineUnlockDays": row.offline_unlock_days,
        "expiryAlertDays": row.expiry_alert_days,
    }


@router.patch("/settings")
def update_settings(
    body: SettingsUpdateIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_admin),
):
    row = get_or_create_settings(db)
    if body.discount_limit_percent is not None:
        row.discount_limit_percent = body.discount_limit_percent
    if body.session_timeout_minutes is not None:
        row.session_timeout_minutes = body.session_timeout_minutes
    if body.offline_unlock_days is not None:
        row.offline_unlock_days = body.offline_unlock_days
    if body.expiry_alert_days is not None:
        row.expiry_alert_days = body.expiry_alert_days
    add_audit(
        db,
        user_id=actor.id,
        device_id=actor.device_id,
        action="settings",
        record="Updated system settings",
    )
    db.commit()
    return {
        "discountLimitPercent": row.discount_limit_percent,
        "sessionTimeoutMinutes": row.session_timeout_minutes,
        "offlineUnlockDays": row.offline_unlock_days,
        "expiryAlertDays": row.expiry_alert_days,
    }
