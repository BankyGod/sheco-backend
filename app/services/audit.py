from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import AuditLog
from app.services.ids import new_id


def add_audit(
    db: Session,
    *,
    user_id: str,
    device_id: str,
    action: str,
    record: str,
) -> AuditLog:
    entry = AuditLog(
        id=new_id("a"),
        user_id=user_id,
        device_id=device_id or "",
        action=action,
        record=record,
        time=datetime.now(timezone.utc),
    )
    db.add(entry)
    return entry
