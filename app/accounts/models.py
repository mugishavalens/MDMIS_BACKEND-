import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.types import GUID

ROLE_CHOICES = (
    "field_operator",
    "drone_operator",
    "geologist",
    "mine_manager",
    "safety_officer",
    "compliance_manager",
    "government_auditor",
    "investor",
    "company_admin",
    "system_admin",
)


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
    """10 SRS roles; RBAC enforced via app.deps.require_role. is_active=False
    until an admin approves — matches the frontend's 'Request submitted' flow."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="field_operator")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
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
