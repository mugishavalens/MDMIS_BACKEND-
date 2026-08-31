from fastapi import APIRouter, Depends, HTTPException, status
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password

from .models import Organisation, User
from .schemas import AccessTokenOut, LoginIn, RefreshIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    return UserOut(
        name=user.full_name,
        email=user.email,
        role=user.role,
        roleLabel=user.role_label,
        initials=user.initials,
        orgId=str(user.organisation_id) if user.organisation_id else None,
        orgName=user.organisation.name if user.organisation else None,
    )


@router.post("/register/", status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterIn, db: AsyncSession = Depends(get_db)):
    """REQ-ACC-001. Creates an Organisation + User, inactive until an admin
    approves — matches the frontend's 'Request submitted' copy."""
    email = payload.email.lower()
    existing = await db.scalar(select(User).where(User.email == email))
    if existing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An account with this email already exists.")

    org_name = payload.organisation_name or f"{payload.full_name}'s Organisation"
    base_slug = slugify(org_name) or "org"
    slug = base_slug
    suffix = 1
    while await db.scalar(select(Organisation).where(Organisation.slug == slug)):
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    org = Organisation(name=org_name, slug=slug, primary_contact_email=email)
    db.add(org)
    await db.flush()

    user = User(
        organisation_id=org.id,
        email=email,
        full_name=payload.full_name,
        role=payload.role,
        password_hash=hash_password(payload.password),
        is_active=False,
    )
    db.add(user)
    await db.commit()

    return {"detail": "Access request submitted. An administrator will review and approve your account."}


@router.post("/login/", response_model=TokenOut)
async def login(payload: LoginIn, db: AsyncSession = Depends(get_db)):
    """Returns tokens + user profile in one response so the frontend can
    populate auth state without a second round trip."""
    result = await db.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid email or password.")
    if not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your account is pending administrator approval.")

    return TokenOut(
        access=create_access_token(str(user.id)),
        refresh=create_refresh_token(str(user.id)),
        user=_user_out(user),
    )


@router.post("/refresh/", response_model=AccessTokenOut)
async def refresh(payload: RefreshIn):
    try:
        data = decode_token(payload.refresh)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token.")
    if data.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type.")
    return AccessTokenOut(access=create_access_token(data["sub"]))


@router.get("/me/", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return _user_out(current_user)
