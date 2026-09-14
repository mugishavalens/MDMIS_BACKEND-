"""Read-only cross-domain aggregator for the Dashboard page.

This is the one deliberate exception to the modular-monolith rule that
domains don't import each other's models: a dashboard/reporting layer
inherently needs to read across domains. It only ever runs SELECT
queries against other domains' tables — it never writes to them and
never imports their routers/business logic.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User
from app.compliance.models import ComplianceReport
from app.database import get_db
from app.deps import get_current_user
from app.safety.models import SafetyIncident
from app.scans.models import MineralZone, ScanSession
from app.sites.models import Site
from app.traceability.models import CustodyEvent, MineralBatch
from app.transport.models import Shipment

from .schemas import ActivityItem, DashboardSummary, MineralDistributionPoint, MonthlyTrendPoint

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_RECENT_PER_DOMAIN = 10
_ACTIVITY_LIMIT = 20
_TREND_MONTHS = 6


def _org_scope(query, model, user: User):
    if user.role == "system_admin":
        return query
    return query.where(model.organisation_id == user.organisation_id)


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    trend_cutoff = now - timedelta(days=30 * _TREND_MONTHS)

    active_sites = await db.scalar(
        _org_scope(select(func.count(Site.id)).where(Site.status == "active"), Site, user)
    )
    total_sites = await db.scalar(_org_scope(select(func.count(Site.id)), Site, user))
    flagged_sites = await db.scalar(
        _org_scope(select(func.count(Site.id)).where(Site.status == "flagged"), Site, user)
    )
    scans_today = await db.scalar(
        _org_scope(
            select(func.count(ScanSession.id)).where(ScanSession.uploaded_at >= today_start),
            ScanSession,
            user,
        )
    )
    avg_confidence = await db.scalar(
        _org_scope(select(func.avg(MineralZone.confidence_score)), MineralZone, user)
    )
    estimated_reserve = await db.scalar(
        _org_scope(select(func.sum(Site.estimated_tonnage)), Site, user)
    )

    total_batches = await db.scalar(_org_scope(select(func.count(MineralBatch.id)), MineralBatch, user))
    compliant_batches = await db.scalar(
        _org_scope(select(func.count(MineralBatch.id)).where(MineralBatch.compliant.is_(True)), MineralBatch, user)
    )
    compliant_pct = (compliant_batches / total_batches * 100) if total_batches else 0.0

    # ── Monthly detection trend (last N months) ────────────────────────────
    month_col = func.date_trunc("month", MineralZone.created_at)
    trend_query = _org_scope(
        select(
            month_col.label("month"),
            func.count(MineralZone.id).label("detections"),
            func.avg(MineralZone.confidence_score).label("confidence"),
        ).where(MineralZone.created_at >= trend_cutoff),
        MineralZone,
        user,
    ).group_by(month_col).order_by(month_col)
    trend_rows = (await db.execute(trend_query)).all()
    monthly_trend = [
        MonthlyTrendPoint(
            month=row.month.strftime("%b"),
            detections=row.detections,
            confidence=round(float(row.confidence or 0), 1),
        )
        for row in trend_rows
    ]

    # ── Mineral distribution ────────────────────────────────────────────────
    mineral_query = _org_scope(
        select(MineralZone.mineral_type, func.count(MineralZone.id))
        .group_by(MineralZone.mineral_type)
        .order_by(func.count(MineralZone.id).desc()),
        MineralZone,
        user,
    )
    mineral_rows = (await db.execute(mineral_query)).all()
    mineral_distribution = [
        MineralDistributionPoint(mineral=mineral.capitalize(), detections=count)
        for mineral, count in mineral_rows
    ]

    # ── Recent activity: read-time merge across every domain's own rows ────
    activity: list[ActivityItem] = []

    scan_rows = (
        await db.execute(
            _org_scope(select(ScanSession), ScanSession, user)
            .order_by(ScanSession.uploaded_at.desc())
            .limit(_RECENT_PER_DOMAIN)
        )
    ).scalars().all()
    for s in scan_rows:
        activity.append(ActivityItem(
            id=f"scan-{s.id}",
            kind="scan",
            title=f"Scan session at {s.site_id}",
            detail=f"{len(s.zones)} zone(s) · {s.status}",
            timestamp=s.uploaded_at,
        ))

    custody_query = select(CustodyEvent).join(MineralBatch)
    if user.role != "system_admin":
        custody_query = custody_query.where(MineralBatch.organisation_id == user.organisation_id)
    custody_rows = (
        await db.execute(custody_query.order_by(CustodyEvent.timestamp.desc()).limit(_RECENT_PER_DOMAIN))
    ).scalars().all()
    for ev in custody_rows:
        activity.append(ActivityItem(
            id=f"trace-{ev.id}",
            kind="trace",
            title=f"Custody event: {ev.event_type}",
            detail=f"{ev.from_party or 'Unknown'} → {ev.to_party or 'Unknown'}",
            timestamp=ev.timestamp,
        ))

    shipment_rows = (
        await db.execute(
            _org_scope(select(Shipment), Shipment, user)
            .order_by(Shipment.updated_at.desc())
            .limit(_RECENT_PER_DOMAIN)
        )
    ).scalars().all()
    for sh in shipment_rows:
        activity.append(ActivityItem(
            id=f"shipment-{sh.id}",
            kind="shipment",
            title=f"Shipment to {sh.destination_name}",
            detail=f"{sh.status} · driver {sh.driver or 'unassigned'}",
            timestamp=sh.updated_at,
        ))

    report_rows = (
        await db.execute(
            _org_scope(select(ComplianceReport), ComplianceReport, user)
            .order_by(ComplianceReport.created_at.desc())
            .limit(_RECENT_PER_DOMAIN)
        )
    ).scalars().all()
    for r in report_rows:
        activity.append(ActivityItem(
            id=f"compliance-{r.id}",
            kind="compliance",
            title=r.title,
            detail=f"{r.framework.upper()} · {r.status}",
            timestamp=r.created_at,
        ))

    incident_rows = (
        await db.execute(
            _org_scope(select(SafetyIncident), SafetyIncident, user)
            .order_by(SafetyIncident.created_at.desc())
            .limit(_RECENT_PER_DOMAIN)
        )
    ).scalars().all()
    for i in incident_rows:
        activity.append(ActivityItem(
            id=f"alert-{i.id}",
            kind="alert",
            title=f"{i.incident_type.replace('_', ' ').title()} incident",
            detail=i.description or f"Risk score {i.risk_score}",
            timestamp=i.created_at,
        ))

    activity.sort(key=lambda a: a.timestamp, reverse=True)

    return DashboardSummary(
        activeSites=active_sites or 0,
        totalSites=total_sites or 0,
        flaggedSites=flagged_sites or 0,
        scansToday=scans_today or 0,
        avgConfidence=round(float(avg_confidence or 0), 1),
        estimatedReserveTonnes=int(estimated_reserve or 0),
        compliantLotsPct=round(compliant_pct, 1),
        monthlyTrend=monthly_trend,
        mineralDistribution=mineral_distribution,
        activity=activity[:_ACTIVITY_LIMIT],
    )
