from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

DeviceSensorType = Literal[
    "hyperspectral", "gpr", "em", "magnetometer", "gamma", "satellite", "lab", "gas", "geotechnical",
]


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    siteId: str = Field(validation_alias="site_id")
    name: str
    sensorType: str = Field(validation_alias="sensor_type")
    apiKeyPrefix: str = Field(validation_alias="api_key_prefix")
    isActive: bool = Field(validation_alias="is_active")
    lastSeenAt: Optional[datetime] = Field(default=None, validation_alias="last_seen_at")
    lastValues: dict = Field(default_factory=dict, validation_alias="last_values")
    online: bool = False
    created_at: datetime


class DeviceWithKeyOut(DeviceOut):
    # Plaintext key — returned only when created or rotated, never stored.
    apiKey: str


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    site_id: str
    sensor_type: DeviceSensorType


class DeviceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    is_active: Optional[bool] = None


class DeviceSummaryOut(BaseModel):
    total: int
    active: int
    online: int


class ReadingIn(BaseModel):
    recorded_at: Optional[datetime] = None
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    values: dict[str, float] = Field(min_length=1, max_length=50)

    @field_validator("values")
    @classmethod
    def metric_names(cls, v: dict[str, float]) -> dict[str, float]:
        for key in v:
            if not key or len(key) > 40 or not all(c.isalnum() or c == "_" for c in key):
                raise ValueError(f"Invalid metric name '{key}': use letters, digits and underscores (e.g. co_ppm).")
        return v


class ReadingsBatchIn(BaseModel):
    readings: list[ReadingIn] = Field(min_length=1, max_length=500)


class AutoIncidentOut(BaseModel):
    id: UUID
    incidentType: str
    riskScore: int
    description: str


class IngestReadingsOut(BaseModel):
    accepted: int
    incidentsCreated: list[AutoIncidentOut]


class ReadingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    deviceId: UUID = Field(validation_alias="device_id")
    siteId: str = Field(validation_alias="site_id")
    sensorType: str = Field(validation_alias="sensor_type")
    recordedAt: datetime = Field(validation_alias="recorded_at")
    lat: Optional[float] = None
    lng: Optional[float] = None
    values: dict


class SensorFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    siteId: str = Field(validation_alias="site_id")
    scanSessionId: Optional[UUID] = Field(default=None, validation_alias="scan_session_id")
    sensorType: str = Field(validation_alias="sensor_type")
    originalFilename: str = Field(validation_alias="original_filename")
    fileKind: Optional[str] = Field(default=None, validation_alias="file_kind")
    sizeBytes: int = Field(validation_alias="size_bytes")
    sha256: str
    bbox: Optional[list[float]] = None
    metadata: dict = Field(default_factory=dict, validation_alias="file_metadata")
    status: str
    errors: list = Field(default_factory=list, validation_alias="validation_errors")
    warnings: list = Field(default_factory=list, validation_alias="validation_warnings")
    uploadMethod: str = Field(validation_alias="upload_method")
    uploadedByName: Optional[str] = None
    deviceName: Optional[str] = None
    created_at: datetime


class DownloadUrlOut(BaseModel):
    url: str
    # True when url is absolute (object storage); false = path under the API base.
    external: bool
    expiresIn: int
