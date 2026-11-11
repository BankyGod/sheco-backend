from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import User
from app.security import hash_password
from app.services.settings_svc import get_or_create_settings


def seed_if_empty(db: Session) -> None:
    """Fresh installs get a single admin account and settings — no demo inventory."""
    if db.query(User).first():
        get_or_create_settings(db)
        db.commit()
        return

    db.add(
        User(
            id="u1",
            name="Admin",
            username="admin",
            password_hash=hash_password("admin123"),
            pin_hash=hash_password("1234"),
            role="super_admin",
            active=True,
            deleted=False,
        )
    )
    get_or_create_settings(db)
    db.commit()
