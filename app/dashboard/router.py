"""Read-only cross-domain aggregator for the Dashboard page.

This is the one deliberate exception to the modular-monolith rule that
domains don't import each other's models: a dashboard/reporting layer
inherently needs to read across domains. It only ever runs SELECT
queries against other domains' tables — it never writes to them and
never imports their routers/business logic.

Perf note: against Neon from far away, each round trip is ~300ms, so
query COUNT dominates, not per-query work. Concurrent sessions
(asyncio.gather, one AsyncSessionLocal() each) was tried and made things
WORSE — N new connection setups in parallel cost more than N queries in
sequence on one already-open connection. So this endpoint runs exactly 3
queries on the single shared session: all headline counts in one SELECT,
the raw zone rows, and every domain's recent activity in one UNION ALL.
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import String, cast, func, literal, select, true, union_all
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


def _activity_item(r) -> ActivityItem:
    # Normalise the id to the dashed UUID form regardless of how the
    # dialect stored it (native UUID on Postgres, hex CHAR(32) on SQLite).
    item_id = str(uuid.UUID(r.id))
    if r.kind == "scan":
        title, detail = f"Scan session at {r.a}", f"{r.c} zone(s) · {r.b}"
    elif r.kind == "trace":
        title, detail = f"Custody event: {r.a}", f"{r.b or 'Unknown'} → {r.c or 'Unknown'}"
    elif r.kind == "shipment":
        title, detail = f"Shipment to {r.a}", f"{r.b} · driver {r.c or 'unassigned'}"
    elif r.kind == "compliance":
        title, detail = r.a, f"{r.b.upper()} · {r.c}"
    else:  # alert
        title, detail = f"{r.a.replace('_', ' ').title()} incident", r.b or f"Risk score {r.c}"
    return ActivityItem(id=f"{r.kind}-{item_id}", kind=r.kind, title=title, detail=detail, timestamp=r.ts)


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    trend_cutoff = now - timedelta(days=30 * _TREND_MONTHS)

    # ── Query 1: every headline count, as 1-row subqueries cross-joined ──
    site_sub = _org_scope(
        select(
            func.count(Site.id).label("total"),
            func.count(Site.id).filter(Site.status == "active").label("active"),
            func.count(Site.id).filter(Site.status == "flagged").label("flagged"),
            func.sum(Site.estimated_tonnage).label("reserve"),
        ),
        Site,
        user,
    ).subquery()
    scans_sub = _org_scope(
        select(func.count(ScanSession.id).label("scans_today")).where(ScanSession.uploaded_at >= today_start),
        ScanSession,
        user,
    ).subquery()
    batch_sub = _org_scope(
        select(
            func.count(MineralBatch.id).label("batch_total"),
            func.count(MineralBatch.id).filter(MineralBatch.compliant.is_(True)).label("batch_compliant"),
        ),
        MineralBatch,
        user,
    ).subquery()
    stats = (
        await db.execute(
            select(site_sub, scans_sub, batch_sub).select_from(
                site_sub.join(scans_sub, true()).join(batch_sub, true())
            )
        )
    ).one()
    compliant_pct = (stats.batch_compliant / stats.batch_total * 100) if stats.batch_total else 0.0

    # ── Query 2: raw zone rows feeding avg confidence + distribution + trend ──
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

    # ── Query 3: recent activity from every domain in one UNION ALL ──
    # Each branch projects the same (kind, id, a, b, c, ts) shape; a/b/c are
    # whatever that domain's title/detail need, formatted below in Python.
    def _branch(kind, model, a, b, c, ts, query=None):
        q = query if query is not None else _org_scope(select(), model, user)
        return q.add_columns(
            literal(kind).label("kind"),
            cast(model.id, String).label("id"),
            cast(a, String).label("a"),
            cast(b, String).label("b"),
            cast(c, String).label("c"),
            ts.label("ts"),
        ).select_from(model).order_by(ts.desc()).limit(_RECENT_PER_DOMAIN).subquery()

    zone_count = (
        select(func.count(MineralZone.id))
        .where(MineralZone.scan_session_id == ScanSession.id)
        .correlate(ScanSession)
        .scalar_subquery()
    )
    custody_query = select().join_from(CustodyEvent, MineralBatch)
    if user.role != "system_admin":
        custody_query = custody_query.where(MineralBatch.organisation_id == user.organisation_id)

    branches = [
        _branch("scan", ScanSession, ScanSession.site_id, ScanSession.status, zone_count, ScanSession.uploaded_at),
        _branch("trace", CustodyEvent, CustodyEvent.event_type, CustodyEvent.from_party, CustodyEvent.to_party,
                CustodyEvent.timestamp, query=custody_query),
        _branch("shipment", Shipment, Shipment.destination_name, Shipment.status, Shipment.driver, Shipment.updated_at),
        _branch("compliance", ComplianceReport, ComplianceReport.title, ComplianceReport.framework,
                ComplianceReport.status, ComplianceReport.created_at),
        _branch("alert", SafetyIncident, SafetyIncident.incident_type, SafetyIncident.description,
                SafetyIncident.risk_score, SafetyIncident.created_at),
    ]
    activity_rows = (await db.execute(union_all(*(select(b) for b in branches)))).all()

    # UNION ALL row order isn't guaranteed; put rows back in domain order
    # (newest first within each) so the stable timestamp sort below breaks
    # ties exactly as a per-domain fetch would.
    domain_rank = {"scan": 0, "trace": 1, "shipment": 2, "compliance": 3, "alert": 4}
    activity_rows = sorted(activity_rows, key=lambda r: r.ts, reverse=True)
    activity_rows.sort(key=lambda r: domain_rank[r.kind])

    activity = [_activity_item(r) for r in activity_rows]
    activity.sort(key=lambda a: a.timestamp, reverse=True)

    return DashboardSummary(
        activeSites=stats.active or 0,
        totalSites=stats.total or 0,
        flaggedSites=stats.flagged or 0,
        scansToday=stats.scans_today or 0,
        avgConfidence=avg_confidence,
        estimatedReserveTonnes=int(stats.reserve or 0),
        compliantLotsPct=round(compliant_pct, 1),
        monthlyTrend=monthly_trend,
        mineralDistribution=mineral_distribution,
        activity=activity[:_ACTIVITY_LIMIT],
    )
