from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import Actor, get_current_actor, require_admin
from app.models import User
from app.schemas.common import (
    LoginIn,
    PasswordResetIn,
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

    if not user or not user.active or not verify_password(body.password, user.password_hash):
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
