from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from .models import INVITABLE_ROLES


class RegisterIn(BaseModel):
    """Self-registration always creates a new Organisation + org_admin —
    there is no role field. Teammates are added afterwards via invitations."""

    full_name: str
    email: EmailStr
    password: str = Field(min_length=8)
    organisation_name: Optional[str] = ""


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class VerificationRequiredOut(BaseModel):
    """Returned right after an account is created (register or accept-invite)
    — the account is inactive until the emailed code is confirmed via
    /auth/verify-otp/, which then activates it and returns tokens."""

    verification_required: bool = True
    email: str


class VerifyOtpIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)


class ResendOtpIn(BaseModel):
    email: EmailStr


class RefreshIn(BaseModel):
    refresh: str


class UserOut(BaseModel):
    """Shape matches the frontend's `RoleUser` type (frontend/lib/rbac.ts)."""

    name: str
    email: str
    role: str
    roleLabel: str
    initials: str
    isActive: bool = True
    orgId: Optional[str] = None
    orgName: Optional[str] = None


class TokenOut(BaseModel):
    access: str
    refresh: str
    user: UserOut


class AccessTokenOut(BaseModel):
    access: str


class InvitationCreate(BaseModel):
    email: EmailStr
    role: str

    @field_validator("role")
    @classmethod
    def role_must_be_invitable(cls, v: str) -> str:
        if v not in INVITABLE_ROLES:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(INVITABLE_ROLES)}")
        return v


class InvitationOut(BaseModel):
    id: UUID
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class InviteDetailOut(BaseModel):
    email: str
    role: str
    organisation_name: str
    valid: bool


class AcceptInviteIn(BaseModel):
    token: str
    full_name: str
    password: str = Field(min_length=8)
