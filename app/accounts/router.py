import base64
import binascii
import html
import uuid
from datetime import datetime, timedelta, timezone
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import ratelimit
from app.audit.service import log_event
from app.config import settings
from app.database import get_db
from app.deps import get_current_user, require_org_admin
from app.email import EmailDeliveryError, send_email
from app.security import (
    DUMMY_PASSWORD_HASH,
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
    AvatarIn,
    ChangePasswordIn,
    InvitationCreate,
    InvitationOut,
    InviteDetailOut,
    LoginIn,
    ForgotPasswordIn,
    PasswordChangedOut,
    RefreshIn,
    RegisterIn,
    ResendOtpIn,
    ResetPasswordIn,
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
        avatarUrl=user.avatar,
    )


_EMAIL_FAILED = "We couldn't send the verification email right now. Please try again in a few minutes."


def _tokens(user: User) -> dict:
    return {
        "access": create_access_token(str(user.id), user.token_version),
        "refresh": create_refresh_token(str(user.id), user.token_version),
    }


def _limit_code_email(email: str, request: Request) -> None:
    """Every code request sends a real email: cap per address and per IP
    (email bombing, and guessing codes by requesting endless new ones)."""
    ratelimit.code_emails.hit(email)
    ratelimit.code_emails_per_ip.hit(ratelimit.client_ip(request))


async def _issue_otp(user: User, db: AsyncSession, purpose: str = "verify") -> None:
    """Sends a fresh verification code, then commits. The email goes out
    BEFORE the commit: if delivery fails everything is rolled back, so a
    failed registration never leaves an account behind that can't be verified.
    Callers rate-limit first (_limit_code_email)."""
    code = generate_otp()
    user.mfa_code_hash = hash_otp(code)
    user.mfa_code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.otp_expire_minutes)
    user.mfa_attempts = 0
    await db.flush()
    try:
        reset = purpose == "reset"
        await send_email(
            user.email,
            "Your MDMIS password reset code" if reset else "Your MDMIS verification code",
            f"<p>Hi {html.escape(user.full_name)},</p>"
            f"<p>Your MDMIS {'password reset' if reset else 'verification'} code is:</p>"
            f"<p style='font-size:28px;font-weight:700;letter-spacing:4px'>{code}</p>"
            f"<p>It expires in {settings.otp_expire_minutes} minutes. If you didn't request this, ignore this email.</p>",
        )
    except EmailDeliveryError:
        await db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _EMAIL_FAILED)
    await db.commit()


@router.post("/register/", status_code=status.HTTP_201_CREATED, response_model=VerificationRequiredOut)
async def register(payload: RegisterIn, request: Request, db: AsyncSession = Depends(get_db)):
    """Creates an Organisation + its org_admin, inactive until the emailed
    code is confirmed via /auth/verify-otp/ — that's what activates the
    account and hands back tokens. Teammates are invited afterwards."""
    ratelimit.registrations_per_ip.hit(ratelimit.client_ip(request))
    email = payload.email.lower()
    existing = await db.scalar(select(User).where(User.email == email))
    if existing and not existing.is_email_verified:
        # Registered before but never verified (e.g. the code email didn't
        # arrive). Don't change the password here — that would let anyone
        # hijack a pending sign-up; sign-in re-sends the code instead.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This email is already registered but not verified yet. Sign in with your password and we'll send you a new code.",
        )
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

    _limit_code_email(email, request)
    await _issue_otp(user, db)
    return VerificationRequiredOut(email=user.email)


@router.post("/login/", response_model=Union[TokenOut, VerificationRequiredOut])
async def login(payload: LoginIn, request: Request, db: AsyncSession = Depends(get_db)):
    """Plain password login — email verification happens once, at account
    creation (register/accept-invite), not on every sign-in. The only time
    this re-triggers a code is if someone never finished verifying.

    5 wrong passwords for an account pause it for 15 minutes; an unknown
    email is checked against a dummy hash so timing doesn't reveal which
    addresses have accounts."""
    email = payload.email.lower()
    ratelimit.login_per_ip.hit(ratelimit.client_ip(request))
    ratelimit.login_failures.check(email)
    user = await db.scalar(select(User).where(User.email == email))
    password_ok = verify_password(payload.password, user.password_hash if user else DUMMY_PASSWORD_HASH)
    if user is None or not password_ok:
        ratelimit.login_failures.hit(email)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid email or password.")
    ratelimit.login_failures.reset(email)

    if not user.is_active:
        _limit_code_email(email, request)
        await _issue_otp(user, db)
        return VerificationRequiredOut(email=user.email)

    return TokenOut(**_tokens(user), user=_user_out(user))


async def _consume_code(db: AsyncSession, email: str, code: str) -> User:
    """Checks a code sent by email; on success clears it and returns the
    user. Limited to 5 guesses per code and 10 per account per 15 minutes."""
    ratelimit.code_checks.hit(email)
    user = await db.scalar(select(User).where(User.email == email))
    if not user or not user.mfa_code_hash or not user.mfa_code_expires_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No verification in progress. Please sign in again.")
    if datetime.now(timezone.utc) > _aware(user.mfa_code_expires_at):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code expired. Please request a new one.")
    if user.mfa_attempts >= MAX_OTP_ATTEMPTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Too many attempts. Please request a new code.")
    if not verify_otp(code, user.mfa_code_hash):
        user.mfa_attempts += 1
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code.")
    user.mfa_code_hash = None
    user.mfa_code_expires_at = None
    user.mfa_attempts = 0
    return user


@router.post("/verify-otp/", response_model=TokenOut)
async def verify_otp_endpoint(payload: VerifyOtpIn, db: AsyncSession = Depends(get_db)):
    """Finishes sign-up for an account that hasn't verified its email yet.
    Not a sign-in method for verified accounts: a code alone (no password)
    must never open an account that's already set up. Forgotten passwords
    go through /forgot-password/ + /reset-password/."""
    email = payload.email.lower()
    user = await db.scalar(select(User).where(User.email == email))
    if user is not None and user.is_email_verified and user.is_active:
        ratelimit.code_checks.hit(email)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No verification in progress. Please sign in again.")
    user = await _consume_code(db, email, payload.code)
    user.is_active = True
    user.is_email_verified = True
    await db.commit()
    return TokenOut(**_tokens(user), user=_user_out(user))


@router.post("/resend-otp/")
async def resend_otp(payload: ResendOtpIn, request: Request, db: AsyncSession = Depends(get_db)):
    email = payload.email.lower()
    _limit_code_email(email, request)
    user = await db.scalar(select(User).where(User.email == email))
    # Only accounts still finishing sign-up get a code here.
    if user and not user.is_email_verified:
        await _issue_otp(user, db)
    return {"detail": "If that account exists, a new code was sent."}


@router.post("/forgot-password/")
async def forgot_password(payload: ForgotPasswordIn, request: Request, db: AsyncSession = Depends(get_db)):
    """Emails a reset code. Same answer whether or not the account exists."""
    email = payload.email.lower()
    _limit_code_email(email, request)
    user = await db.scalar(select(User).where(User.email == email))
    if user:
        await _issue_otp(user, db, purpose="reset")
    return {"detail": "If that account exists, a reset code was sent."}


@router.post("/reset-password/", response_model=TokenOut)
async def reset_password(payload: ResetPasswordIn, db: AsyncSession = Depends(get_db)):
    """Sets a new password with a code from /forgot-password/. Proving the
    email also completes sign-up for an unverified account (so an address
    someone else registered first can be reclaimed by its real owner), and
    ends every existing session."""
    user = await _consume_code(db, payload.email.lower(), payload.code)
    user.password_hash = hash_password(payload.new_password)
    user.token_version += 1
    user.is_active = True
    user.is_email_verified = True
    await log_event(db, user, "account.password_reset", "user", str(user.id), "Reset password by email code")
    await db.commit()
    return TokenOut(**_tokens(user), user=_user_out(user))


@router.post("/refresh/", response_model=AccessTokenOut)
async def refresh(payload: RefreshIn, db: AsyncSession = Depends(get_db)):
    try:
        data = decode_token(payload.refresh)
        user_id = uuid.UUID(str(data.get("sub")))
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token.")
    if data.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type.")
    user = await db.scalar(select(User).where(User.id == user_id))
    # A deactivated account, or one whose sessions were ended (password
    # change/reset, logout), gets no new access tokens.
    if user is None or not user.is_active or data.get("ver", 0) != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session ended. Please sign in again.")
    return AccessTokenOut(access=create_access_token(str(user.id), user.token_version))


@router.post("/logout/", status_code=status.HTTP_204_NO_CONTENT)
async def logout(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Ends every session of this account (all devices): tokens are
    stateless, so the only way to cancel one is to bump the version."""
    current_user.token_version += 1
    await db.commit()


@router.get("/me/", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return _user_out(current_user)


_AVATAR_MAX_BYTES = 200 * 1024
# Magic bytes, so the stored "image" really is one whatever the prefix says.
_AVATAR_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}


@router.put("/me/avatar/", response_model=UserOut)
async def set_avatar(
    payload: AvatarIn, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    header, _, b64 = payload.data_url.partition(",")
    mime = header.removeprefix("data:").removesuffix(";base64")
    if not header.startswith("data:") or not header.endswith(";base64") or mime not in _AVATAR_SIGNATURES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Photo must be a JPEG, PNG or WebP image.")
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Photo data is corrupted.")
    if len(raw) > _AVATAR_MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Photo is too large (max 200 KB after resizing).")
    if not raw.startswith(_AVATAR_SIGNATURES[mime]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File content doesn't match an image.")
    current_user.avatar = payload.data_url
    await db.commit()
    return _user_out(current_user)


@router.delete("/me/avatar/", response_model=UserOut)
async def remove_avatar(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    current_user.avatar = None
    await db.commit()
    return _user_out(current_user)


@router.post("/change-password/", response_model=PasswordChangedOut)
async def change_password(
    payload: ChangePasswordIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect.")
    if payload.new_password == payload.current_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password must be different from the current one.")
    current_user.password_hash = hash_password(payload.new_password)
    # Signs out every other session (e.g. a stolen token); this one gets
    # fresh tokens back.
    current_user.token_version += 1
    await log_event(db, current_user, "account.password_change", "user", str(current_user.id), "Changed own password")
    await db.commit()
    return PasswordChangedOut(**_tokens(current_user))


@router.get("/invitations/{token}/", response_model=InviteDetailOut)
async def get_invitation(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    ratelimit.invite_lookups_per_ip.hit(ratelimit.client_ip(request))
    invite = await db.scalar(select(Invitation).where(Invitation.token == token))
    if not invite:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found.")
    valid = invite.status == "pending" and _aware(invite.expires_at) > datetime.now(timezone.utc)
    return InviteDetailOut(
        email=invite.email, role=invite.role, organisation_name=invite.organisation.name, valid=valid
    )


@router.post("/accept-invite/", status_code=status.HTTP_201_CREATED, response_model=VerificationRequiredOut)
async def accept_invite(payload: AcceptInviteIn, request: Request, db: AsyncSession = Depends(get_db)):
    ratelimit.registrations_per_ip.hit(ratelimit.client_ip(request))
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

    _limit_code_email(user.email, request)
    await _issue_otp(user, db)
    return VerificationRequiredOut(email=user.email)


@accounts_router.get("/users/", response_model=list[UserOut])
async def list_org_users(db: AsyncSession = Depends(get_db), user: User = Depends(require_org_admin)):
    query = select(User)
    if user.role != "system_admin":
        # An org admin manages their own org's accounts only; platform
        # system_admins aren't org members to manage, even if attached to one.
        query = query.where(User.organisation_id == user.organisation_id, User.role != "system_admin")
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
    await db.flush()  # populate invite.id (default=uuid.uuid4 applies at flush, not construction)
    await log_event(db, user, "invite.create", "invitation", str(invite.id), f"Invited {email} as {payload.role}")

    # Send before committing: if the email fails, no invitation is recorded
    # that the invitee never received.
    org_name = user.organisation.name if user.organisation else "MDMIS"
    link = f"{settings.frontend_url}/accept-invite?token={invite.token}"
    try:
        await send_email(
            invite.email,
            f"You're invited to join {org_name} on MDMIS",
            f"<p>{html.escape(user.full_name)} invited you to join <b>{html.escape(org_name)}</b> on MDMIS as "
            f"<b>{payload.role.replace('_', ' ').title()}</b>.</p>"
            f"<p><a href='{html.escape(link)}'>Accept invitation</a></p>"
            f"<p>This link expires in {settings.invitation_expire_days} days.</p>",
        )
    except EmailDeliveryError:
        await db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "We couldn't send the invitation email right now. Please try again in a few minutes.")
    await db.commit()
    await db.refresh(invite)
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
    await log_event(db, user, "invite.revoke", "invitation", str(invite.id), f"Revoked invite for {invite.email}")
    await db.delete(invite)
    await db.commit()
