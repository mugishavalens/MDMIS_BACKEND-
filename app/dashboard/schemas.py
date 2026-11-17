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


class KpiTrends(BaseModel):
    """Real movement behind the KPI cards' badges."""

    sitesAdded30d: int
    scansLast7d: int
    scansPrev7d: int
    zonesDetected30d: int
    nonCompliantLots: int


class PublicStats(BaseModel):
    """Platform-wide totals for the public landing page: aggregates only,
    nothing that identifies a site, location or organisation."""

    activeSites: int
    totalSites: int
    districtsCovered: int
    avgConfidence: float
    estimatedReserveTonnes: int
    compliantLotsPct: float


class DashboardSummary(BaseModel):
    activeSites: int
    totalSites: int
    flaggedSites: int
    scansToday: int
    avgConfidence: float
    estimatedReserveTonnes: int
    compliantLotsPct: float
    trends: KpiTrends
    monthlyTrend: list[MonthlyTrendPoint]
    mineralDistribution: list[MineralDistributionPoint]
    activity: list[ActivityItem]
