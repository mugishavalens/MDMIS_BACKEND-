from datetime import datetime

from pydantic import BaseModel


class MonthlyTrendPoint(BaseModel):
    month: str
    detections: int
    confidence: float


class MineralDistributionPoint(BaseModel):
    mineral: str
    detections: int


class ActivityItem(BaseModel):
    id: str
    kind: str
    title: str
    detail: str
    timestamp: datetime


class DashboardSummary(BaseModel):
    activeSites: int
    totalSites: int
    flaggedSites: int
    scansToday: int
    avgConfidence: float
    estimatedReserveTonnes: int
    compliantLotsPct: float
    monthlyTrend: list[MonthlyTrendPoint]
    mineralDistribution: list[MineralDistributionPoint]
    activity: list[ActivityItem]
