import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.types import GUID


class AuditLog(Base):
    """A record of a security/compliance-relevant mutation. Written by
    app.audit.service.log_event(), called from the domains whose actions
    actually matter for an audit trail (invites, custody events, safety
    acknowledgements, non-compliance flags) — not a blanket wrapper around
    every CRUD endpoint in the system.

    actor_name is a snapshot taken at write time (not just actor_id) so the
    log still reads sensibly if the user is later deleted or renamed.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organisations.id", ondelete="CASCADE"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(255), default="System")
    action: Mapped[str] = mapped_column(String(50))
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
