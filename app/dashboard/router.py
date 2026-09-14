"""Read-only cross-domain aggregator for the Dashboard page.

This is the one deliberate exception to the modular-monolith rule that
domains don't import each other's models: a dashboard/reporting layer
inherently needs to read across domains. It only ever runs SELECT
queries against other domains' tables — it never writes to them and
never imports their routers/business logic.

Perf note: every request gets a brand-new session (see app.deps.get_db),
and on this Neon setup establishing/checking out that connection is the
dominant cost (~2s+), not the per-query time once it's warm. Concurrent
sessions (asyncio.gather, one AsyncSessionLocal() each) was tried and
made things WORSE — N new connection setups in parallel beats out to
more total latency than N queries in sequence on one already-open
connection. So the fix here is minimizing query COUNT on the single
shared session, not spreading work across sessions.
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


def _zone_aggregates(rows, trend_cutoff: datetime):
    """avg confidence, mineral distribution, and the monthly trend all come
    from ONE raw fetch of MineralZone rows, aggregated here in Python —
    they have different filter windows (confidence/distribution are
    all-time, trend is cutoff-limited) so they can't share a single SQL
    GROUP BY, but at demo/dev scale one round trip + cheap Python
    aggregation beats 3 separate round trips to Neon."""
    if not rows:
        return 0.0, [], []

    avg_confidence = sum(r.confidence_score for r in rows) / len(rows)

    mineral_counts: dict[str, int] = {}
    for r in rows:
        mineral_counts[r.mineral_type] = mineral_counts.get(r.mineral_type, 0) + 1
    mineral_distribution = [
        MineralDistributionPoint(mineral=mineral.capitalize(), detections=count)
        for mineral, count in sorted(mineral_counts.items(), key=lambda kv: kv[1], reverse=True)
    ]

    month_buckets: dict[str, list[int]] = {}
    for r in rows:
        if r.created_at < trend_cutoff:
            continue
        key = r.created_at.strftime("%Y-%m")
        month_buckets.setdefault(key, []).append(r.confidence_score)
    monthly_trend = [
        MonthlyTrendPoint(
            month=datetime.strptime(key, "%Y-%m").strftime("%b"),
            detections=len(scores),
            confidence=round(sum(scores) / len(scores), 1),
        )
        for key, scores in sorted(month_buckets.items())
    ]

    return round(avg_confidence, 1), mineral_distribution, monthly_trend


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    trend_cutoff = now - timedelta(days=30 * _TREND_MONTHS)

    # 1 round trip for all 4 site-level aggregates (Postgres FILTER clause).
    site_stats = (
        await db.execute(
            _org_scope(
                select(
                    func.count(Site.id).label("total"),
                    func.count(Site.id).filter(Site.status == "active").label("active"),
                    func.count(Site.id).filter(Site.status == "flagged").label("flagged"),
                    func.sum(Site.estimated_tonnage).label("reserve"),
                ),
                Site,
                user,
            )
        )
    ).one()

    scans_today = await db.scalar(
        _org_scope(
            select(func.count(ScanSession.id)).where(ScanSession.uploaded_at >= today_start),
            ScanSession,
            user,
        )
    )

    # 1 round trip for both batch-level aggregates.
    batch_stats = (
        await db.execute(
            _org_scope(
                select(
                    func.count(MineralBatch.id).label("total"),
                    func.count(MineralBatch.id).filter(MineralBatch.compliant.is_(True)).label("compliant"),
                ),
                MineralBatch,
                user,
            )
        )
    ).one()
    compliant_pct = (batch_stats.compliant / batch_stats.total * 100) if batch_stats.total else 0.0

    # 1 round trip feeding avg confidence + mineral distribution + monthly trend.
    zone_rows = (
        await db.execute(
            _org_scope(
                select(MineralZone.mineral_type, MineralZone.confidence_score, MineralZone.created_at),
                MineralZone,
                user,
            )
        )
    ).all()
    avg_confidence, mineral_distribution, monthly_trend = _zone_aggregates(zone_rows, trend_cutoff)

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
        activeSites=site_stats.active or 0,
        totalSites=site_stats.total or 0,
        flaggedSites=site_stats.flagged or 0,
        scansToday=scans_today or 0,
        avgConfidence=avg_confidence,
        estimatedReserveTonnes=int(site_stats.reserve or 0),
        compliantLotsPct=round(compliant_pct, 1),
        monthlyTrend=monthly_trend,
        mineralDistribution=mineral_distribution,
        activity=activity[:_ACTIVITY_LIMIT],
    )
