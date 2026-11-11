from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    Batch,
    Product,
    Sale,
    SaleItem,
    StockMovement,
    User,
)
from app.security import hash_password
from app.services.audit import add_audit
from app.services.ids import new_id
from app.services.settings_svc import get_or_create_settings


def purge_operational_data(db: Session, *, actor=None) -> dict:
    """
    Remove inventory, sales history, stock movements, and non-admin users.
    Keeps settings and exactly one active super_admin account.
    """
    counts = {
        "saleItems": db.query(SaleItem).count(),
        "sales": db.query(Sale).count(),
        "stockMovements": db.query(StockMovement).count(),
        "batches": db.query(Batch).count(),
        "products": db.query(Product).count(),
        "auditLogs": db.query(AuditLog).count(),
    }

    db.execute(delete(SaleItem))
    db.execute(delete(Sale))
    db.execute(delete(StockMovement))
    db.execute(delete(Batch))
    db.execute(delete(Product))
    db.execute(delete(AuditLog))

    admin = (
        db.query(User)
        .filter(User.role == "super_admin", User.deleted.is_(False))
        .order_by(User.created_at.asc())
        .first()
    )
    if not admin:
        admin = db.query(User).filter(User.username.ilike("admin")).first()

    removed_users = 0
    for user in db.query(User).all():
        if admin and user.id == admin.id:
            continue
        db.delete(user)
        removed_users += 1

    if not admin:
        admin = User(
            id=new_id("u"),
            name="Admin",
            username="admin",
            password_hash=hash_password("admin123"),
            pin_hash=hash_password("1234"),
            role="super_admin",
            active=True,
            deleted=False,
        )
        db.add(admin)
        counts["adminCreated"] = True
    else:
        admin.active = True
        admin.deleted = False
        if admin.role != "super_admin":
            admin.role = "super_admin"
        counts["adminCreated"] = False

    settings = get_or_create_settings(db)
    settings.receipt_seq = 0

    if actor is not None:
        add_audit(
            db,
            user_id=actor.id,
            device_id=getattr(actor, "device_id", "SYSTEM"),
            action="data_purge",
            record="Cleared inventory, sales, and non-admin accounts",
        )

    db.flush()
    counts["usersRemoved"] = removed_users
    counts["adminUsername"] = admin.username
    counts["adminName"] = admin.name
    return counts
