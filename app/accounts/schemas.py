from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from .models import ROLE_CHOICES

# system_admin is platform-internal and must never be self-registerable —
# the frontend already hides it from the role dropdown, but that's only a
# UI nicety; a direct API call would otherwise bypass it entirely.
SELF_REGISTERABLE_ROLES = tuple(r for r in ROLE_CHOICES if r != "system_admin")


class RegisterIn(BaseModel):
    full_name: str
    email: EmailStr
    password: str = Field(min_length=8)
    role: str
    organisation_name: Optional[str] = ""

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v: str) -> str:
        if v not in SELF_REGISTERABLE_ROLES:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(SELF_REGISTERABLE_ROLES)}")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh: str


class UserOut(BaseModel):
    """Shape matches the frontend's `RoleUser` type (frontend/lib/rbac.ts)."""

    name: str
    email: str
    role: str
    roleLabel: str
    initials: str
    orgId: Optional[str] = None
    orgName: Optional[str] = None


class TokenOut(BaseModel):
    access: str
    refresh: str
    user: UserOut


class AccessTokenOut(BaseModel):
    access: str
