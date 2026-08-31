from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User
from app.database import get_db
from app.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login/", auto_error=False)

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not token:
        raise _CREDENTIALS_EXCEPTION
    try:
        payload = decode_token(token)
    except Exception:
        raise _CREDENTIALS_EXCEPTION
    if payload.get("type") != "access":
        raise _CREDENTIALS_EXCEPTION

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise _CREDENTIALS_EXCEPTION
    return user


def require_role(*roles: str):
    """REQ-ACC-005: every endpoint checks role before business logic runs.
    system_admin always passes (SRS 3.1: full platform access)."""

    async def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role == "system_admin":
            return current_user
        if current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role.")
        return current_user

    return checker
