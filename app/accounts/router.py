import uuid
from datetime import datetime, timedelta, timezone
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, status
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps import get_current_user, require_org_admin
from app.email import send_email
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_invite_token,
    generate_otp,
    hash_otp,
    hash_password,
    verify_otp,
    verify_password,
)

from .models import Invitation, Organisation, User
from .schemas import (
    AcceptInviteIn,
    AccessTokenOut,
    InvitationCreate,
    InvitationOut,
    InviteDetailOut,
    LoginIn,
    RefreshIn,
    RegisterIn,
    ResendOtpIn,
    TokenOut,
    UserOut,
    VerificationRequiredOut,
    VerifyOtpIn,
)

router = APIRouter(prefix="/auth", tags=["auth"])
accounts_router = APIRouter(prefix="/accounts", tags=["accounts"])

MAX_OTP_ATTEMPTS = 5


def _aware(dt: datetime) -> datetime:
    """SQLite (the dev fallback DB) round-trips DateTime(timezone=True)
    columns as naive datetimes, unlike Postgres/asyncpg — normalize before
    comparing against datetime.now(timezone.utc), since everything we write
    to these columns is already UTC regardless of what comes back."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _user_out(user: User) -> UserOut:
    return UserOut(
        name=user.full_name,
        email=user.email,
        role=user.role,
        roleLabel=user.role_label,
        initials=user.initials,
        isActive=user.is_active,
        orgId=str(user.organisation_id) if user.organisation_id else None,
        orgName=user.organisation.name if user.organisation else None,
    )


async def _issue_otp(user: User, db: AsyncSession) -> None:
    code = generate_otp()
    user.mfa_code_hash = hash_otp(code)
    user.mfa_code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.otp_expire_minutes)
    user.mfa_attempts = 0
    await db.commit()
    await send_email(
        user.email,
        "Your MDMIS verification code",
        f"<p>Hi {user.full_name},</p>"
        f"<p>Your MDMIS verification code is:</p>"
        f"<p style='font-size:28px;font-weight:700;letter-spacing:4px'>{code}</p>"
        f"<p>It expires in {settings.otp_expire_minutes} minutes. If you didn't request this, ignore this email.</p>",
    )


@router.post("/register/", status_code=status.HTTP_201_CREATED, response_model=VerificationRequiredOut)
async def register(payload: RegisterIn, db: AsyncSession = Depends(get_db)):
    """Creates an Organisation + its org_admin, inactive until the emailed
    code is confirmed via /auth/verify-otp/ — that's what activates the
    account and hands back tokens. Teammates are invited afterwards."""
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
        role="org_admin",
        password_hash=hash_password(payload.password),
        is_active=False,
    )
    db.add(user)
    await db.flush()

    await _issue_otp(user, db)
    return VerificationRequiredOut(email=user.email)


@router.post("/login/", response_model=Union[TokenOut, VerificationRequiredOut])
async def login(payload: LoginIn, db: AsyncSession = Depends(get_db)):
    """Plain password login — email verification happens once, at account
    creation (register/accept-invite), not on every sign-in. The only time
    this re-triggers a code is if someone never finished verifying."""
    result = await db.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid email or password.")

    if not user.is_active:
        await _issue_otp(user, db)
        return VerificationRequiredOut(email=user.email)

    return TokenOut(
        access=create_access_token(str(user.id)),
        refresh=create_refresh_token(str(user.id)),
        user=_user_out(user),
    )


@router.post("/verify-otp/", response_model=TokenOut)
async def verify_otp_endpoint(payload: VerifyOtpIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()
    if not user or not user.mfa_code_hash or not user.mfa_code_expires_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No verification in progress. Please sign in again.")
    if datetime.now(timezone.utc) > _aware(user.mfa_code_expires_at):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code expired. Please request a new one.")
    if user.mfa_attempts >= MAX_OTP_ATTEMPTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Too many attempts. Please request a new code.")

    if not verify_otp(payload.code, user.mfa_code_hash):
        user.mfa_attempts += 1
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code.")

    user.mfa_code_hash = None
    user.mfa_code_expires_at = None
    user.mfa_attempts = 0
    user.is_active = True
    user.is_email_verified = True
    await db.commit()

    return TokenOut(
        access=create_access_token(str(user.id)),
        refresh=create_refresh_token(str(user.id)),
        user=_user_out(user),
    )


@router.post("/resend-otp/")
async def resend_otp(payload: ResendOtpIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()
    if user:
        await _issue_otp(user, db)
    return {"detail": "If that account exists, a new code was sent."}


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


@router.get("/invitations/{token}/", response_model=InviteDetailOut)
async def get_invitation(token: str, db: AsyncSession = Depends(get_db)):
    invite = await db.scalar(select(Invitation).where(Invitation.token == token))
    if not invite:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found.")
    valid = invite.status == "pending" and _aware(invite.expires_at) > datetime.now(timezone.utc)
    return InviteDetailOut(
        email=invite.email, role=invite.role, organisation_name=invite.organisation.name, valid=valid
    )


@router.post("/accept-invite/", status_code=status.HTTP_201_CREATED, response_model=VerificationRequiredOut)
async def accept_invite(payload: AcceptInviteIn, db: AsyncSession = Depends(get_db)):
    invite = await db.scalar(select(Invitation).where(Invitation.token == payload.token))
    if not invite or invite.status != "pending" or _aware(invite.expires_at) < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This invitation is invalid or has expired.")

    existing = await db.scalar(select(User).where(User.email == invite.email))
    if existing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An account with this email already exists.")

    user = User(
        organisation_id=invite.organisation_id,
        email=invite.email,
        full_name=payload.full_name,
        role=invite.role,
        password_hash=hash_password(payload.password),
        is_active=False,
    )
    db.add(user)
    invite.status = "accepted"
    invite.accepted_at = datetime.now(timezone.utc)
    await db.flush()

    await _issue_otp(user, db)
    return VerificationRequiredOut(email=user.email)


@accounts_router.get("/users/", response_model=list[UserOut])
async def list_org_users(db: AsyncSession = Depends(get_db), user: User = Depends(require_org_admin)):
    query = select(User)
    if user.role != "system_admin":
        query = query.where(User.organisation_id == user.organisation_id)
    result = await db.execute(query.order_by(User.created_at))
    return [_user_out(u) for u in result.scalars().all()]


@accounts_router.post("/invitations/", response_model=InvitationOut, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    payload: InvitationCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_org_admin)
):
    email = payload.email.lower()
    if await db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A user with this email already exists.")
    existing_invite = await db.scalar(
        select(Invitation).where(
            Invitation.email == email,
            Invitation.organisation_id == user.organisation_id,
            Invitation.status == "pending",
        )
    )
    if existing_invite:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An invitation is already pending for this email.")

    invite = Invitation(
        organisation_id=user.organisation_id,
        email=email,
        role=payload.role,
        token=generate_invite_token(),
        invited_by_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.invitation_expire_days),
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    org_name = user.organisation.name if user.organisation else "MDMIS"
    link = f"{settings.frontend_url}/accept-invite?token={invite.token}"
    await send_email(
        invite.email,
        f"You're invited to join {org_name} on MDMIS",
        f"<p>{user.full_name} invited you to join <b>{org_name}</b> on MDMIS as "
        f"<b>{payload.role.replace('_', ' ').title()}</b>.</p>"
        f"<p><a href='{link}'>Accept invitation</a></p>"
        f"<p>This link expires in {settings.invitation_expire_days} days.</p>",
    )
    return invite


@accounts_router.get("/invitations/", response_model=list[InvitationOut])
async def list_invitations(db: AsyncSession = Depends(get_db), user: User = Depends(require_org_admin)):
    query = select(Invitation).order_by(Invitation.created_at.desc())
    if user.role != "system_admin":
        query = query.where(Invitation.organisation_id == user.organisation_id)
    result = await db.execute(query)
    return result.scalars().all()


@accounts_router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_org_admin)
):
    query = select(Invitation).where(Invitation.id == invitation_id)
    if user.role != "system_admin":
        query = query.where(Invitation.organisation_id == user.organisation_id)
    invite = await db.scalar(query)
    if not invite:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found.")
    await db.delete(invite)
    await db.commit()
