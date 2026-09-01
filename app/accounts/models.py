import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.types import GUID

# system_admin: platform-internal superuser, never self-registerable.
# org_admin: created by self-registration (one per new Organisation); invites
# the 3 roles below by email. Those 3 can only be created via an accepted
# invitation, never via /auth/register/.
ROLE_CHOICES = (
    "system_admin",
    "org_admin",
    "geologist",
    "compliance_manager",
    "mine_manager",
)

# Roles an org_admin is allowed to invite teammates as.
INVITABLE_ROLES = ("geologist", "compliance_manager", "mine_manager")


class Organisation(Base):
    """Multi-tenant isolation boundary. Every client-data table carries an
    organisation_id and every query is scoped to it (see app.crud)."""

    __tablename__ = "organisations"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    registration_number: Mapped[str] = mapped_column(String(100), default="")
    country_code: Mapped[str] = mapped_column(String(2), default="RW")
    license_tier: Mapped[str] = mapped_column(String(50), default="trial")
    primary_contact_email: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    users: Mapped[list["User"]] = relationship(back_populates="organisation")


class User(Base):
    """5-role model; RBAC enforced via app.deps.require_role. Self-registration
    always creates an org_admin (is_active=True immediately); every other role
    is only created by accepting an org_admin's invitation. Every login must
    also pass an emailed one-time code (see mfa_code_hash below)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="mine_manager")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # Email MFA: a hashed 6-digit code + expiry, set on password-check success
    # and cleared once verify-otp succeeds. mfa_attempts caps brute-forcing.
    mfa_code_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mfa_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mfa_attempts: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    organisation: Mapped["Organisation | None"] = relationship(back_populates="users", lazy="joined")

    @property
    def role_label(self) -> str:
        return self.role.replace("_", " ").title()

    @property
    def initials(self) -> str:
        parts = [p for p in self.full_name.split() if p]
        if not parts:
            return self.email[:2].upper()
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()


class Invitation(Base):
    """An org_admin's invite for a teammate to join their Organisation as one
    of INVITABLE_ROLES. Consumed exactly once via /auth/accept-invite/."""

    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("organisations.id", ondelete="CASCADE")
    )
    email: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[str] = mapped_column(String(32))
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | accepted | revoked
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organisation: Mapped["Organisation"] = relationship(lazy="joined")
    invited_by: Mapped["User | None"] = relationship(lazy="joined")
