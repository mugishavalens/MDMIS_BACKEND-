from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    actorId: Optional[UUID] = Field(default=None, validation_alias="actor_id")
    actorName: str = Field(validation_alias="actor_name")
    action: str
    resourceType: str = Field(validation_alias="resource_type")
    resourceId: str = Field(validation_alias="resource_id")
    detail: str
    created_at: datetime


class AuditSummary(BaseModel):
    eventsToday: int
