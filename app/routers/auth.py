from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import Actor, get_current_actor, require_admin
from app.models import User
from app.schemas.common import (
    ChangePasswordIn,
    ChangePinIn,
    LoginIn,
    PasswordResetIn,
    ProfileUpdateIn,
    UserActiveIn,
    UserCreateIn,
)
from app.security import create_access_token, hash_password, verify_password
from app.services.audit import add_audit
from app.services.ids import new_id
from app.services.settings_svc import get_or_create_settings

router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])


def _public_user(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "username": user.username,
        "role": user.role,
        "active": user.active,
        "deleted": bool(getattr(user, "deleted", False)),
    }


@router.post("/login")
def login(
    body: LoginIn,
    db: Session = Depends(get_db),
    x_device_id: str | None = Header(default=None, alias="X-Device-Id"),
):
    username = body.username.strip()
    user = (
        db.query(User)
        .filter(User.username.ilike(username))
        .first()
    )
    now = datetime.now(timezone.utc)

    if user and user.locked_until and user.locked_until > now:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account temporarily locked due to failed sign-in attempts",
        )

    if (
        not user
        or not user.active
        or getattr(user, "deleted", False)
        or not verify_password(body.password, user.password_hash)
    ):
        if user:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= 5:
                user.locked_until = now + timedelta(minutes=15)
                user.failed_login_attempts = 0
            db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password")

    user.failed_login_attempts = 0
    user.locked_until = None
    device_id = body.device_id or x_device_id or "UNKNOWN"
    settings = get_or_create_settings(db)
    token = create_access_token(
        subject=user.id,
        role=user.role,
        extra={"deviceId": device_id},
    )
    add_audit(
        db,
        user_id=user.id,
        device_id=device_id,
        action="sign_in",
        record=f"User {user.name}",
    )
    db.commit()
    return {
        "user": _public_user(user),
        "deviceId": device_id,
        "signedInAt": now.isoformat(),
        "accessToken": token,
        "tokenType": "bearer",
        "offlineUnlockDays": settings.offline_unlock_days,
    }


@router.get("/me")
def me(actor: Actor = Depends(get_current_actor)):
    return _public_user(actor.user)


@router.patch("/me")
def update_me(
    body: ProfileUpdateIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    user = db.get(User, actor.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        user.name = name

    if body.username is not None:
        username = body.username.strip()
        if not username:
            raise HTTPException(status_code=400, detail="Username cannot be empty")
        exists = (
            db.query(User)
            .filter(User.username.ilike(username), User.id != user.id)
            .first()
        )
        if exists:
            raise HTTPException(status_code=400, detail="Username already exists")
        user.username = username

    add_audit(
        db,
        user_id=actor.id,
        device_id=actor.device_id,
        action="profile_update",
        record=f"Updated profile for {user.username}",
    )
    db.commit()
    db.refresh(user)
    return _public_user(user)


@router.post("/change-password")
def change_password(
    body: ChangePasswordIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    user = db.get(User, actor.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    user.password_hash = hash_password(body.new_password)
    add_audit(
        db,
        user_id=actor.id,
        device_id=actor.device_id,
        action="password_change",
        record=f"Password changed for {user.username}",
    )
    db.commit()
    return {"ok": True}


@router.post("/change-pin")
def change_pin(
    body: ChangePinIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    user = db.get(User, actor.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    pin = body.new_pin.strip()
    if len(pin) < 4:
        raise HTTPException(status_code=400, detail="PIN must be at least 4 characters")
    user.pin_hash = hash_password(pin)
    add_audit(
        db,
        user_id=actor.id,
        device_id=actor.device_id,
        action="pin_change",
        record=f"PIN changed for {user.username}",
    )
    db.commit()
    return {"ok": True}


@users_router.get("")
def list_users(
    db: Session = Depends(get_db),
    _: Actor = Depends(require_admin),
):
    users = db.query(User).order_by(User.name.asc()).all()
    return [_public_user(u) for u in users]


@users_router.post("")
def create_user(
    body: UserCreateIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_admin),
):
    exists = (
        db.query(User)
        .filter(User.username.ilike(body.username.strip()))
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="Username already exists")
    user = User(
        id=new_id("u"),
        name=body.name.strip(),
        username=body.username.strip(),
        password_hash=hash_password(body.password),
        pin_hash=hash_password(body.pin or "0000"),
        role=body.role,
        active=True,
    )
    db.add(user)
    add_audit(
        db,
        user_id=actor.id,
        device_id=actor.device_id,
        action="user_create",
        record=f"Created user {user.username} ({user.role})",
    )
    db.commit()
    db.refresh(user)
    return _public_user(user)


@users_router.patch("/{user_id}/active")
def set_user_active(
    user_id: str,
    body: UserActiveIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if getattr(user, "deleted", False):
        raise HTTPException(
            status_code=400,
            detail="Deleted accounts cannot be reactivated. Create a new user instead.",
        )
    if user.id == actor.id and not body.active:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    user.active = body.active
    add_audit(
        db,
        user_id=actor.id,
        device_id=actor.device_id,
        action="user_update",
        record=f"{'Activated' if body.active else 'Deactivated'} user {user.username}",
    )
    db.commit()
    return _public_user(user)


@users_router.delete("/{user_id}")
def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_admin),
):
    """Soft-delete a salesperson. Sales history stays linked for accounting."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == actor.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    if getattr(user, "deleted", False):
        raise HTTPException(status_code=400, detail="User is already deleted")
    if user.role != "salesperson":
        raise HTTPException(
            status_code=400,
            detail="Only salesperson accounts can be deleted. Deactivate admin accounts instead.",
        )

    original_username = user.username
    # Keep the row + name so sales reports still show who sold.
    # Free the username for reuse and block any future login.
    freed = f"deleted.{user.id}.{original_username}"
    user.username = freed[:80]
    user.active = False
    user.deleted = True
    user.password_hash = hash_password(new_id("del"))
    user.pin_hash = hash_password(new_id("pin"))
    user.failed_login_attempts = 0
    user.locked_until = None

    add_audit(
        db,
        user_id=actor.id,
        device_id=actor.device_id,
        action="user_delete",
        record=(
            f"Deleted salesperson {user.name} (@{original_username}); "
            "sales history retained for accounting"
        ),
    )
    db.commit()
    return {
        **_public_user(user),
        "message": "Account deleted. Sales made by this person remain in records.",
    }


@users_router.post("/{user_id}/reset-password")
def reset_password(
    user_id: str,
    body: PasswordResetIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if getattr(user, "deleted", False):
        raise HTTPException(status_code=400, detail="Cannot reset password for a deleted account")
    user.password_hash = hash_password(body.password)
    add_audit(
        db,
        user_id=actor.id,
        device_id=actor.device_id,
        action="user_update",
        record=f"Reset password for {user.username}",
    )
    db.commit()
    return _public_user(user)
