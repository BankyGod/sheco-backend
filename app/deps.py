from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class Actor:
    id: str
    role: str
    device_id: str
    user: User


def get_current_actor(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_device_id: str | None = Header(default=None, alias="X-Device-Id"),
) -> Actor:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    user_id = payload.get("sub")
    user = db.get(User, user_id) if user_id else None
    if not user or not user.active or getattr(user, "deleted", False):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive or missing")

    return Actor(
        id=user.id,
        role=user.role,
        device_id=x_device_id or payload.get("deviceId") or "UNKNOWN",
        user=user,
    )


def require_admin(actor: Actor = Depends(get_current_actor)) -> Actor:
    if actor.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return actor
