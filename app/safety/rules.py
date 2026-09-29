"""REQ-SAFE-001 threshold engine: turns sensor readings that breach a
SafetyRule into safety incidents automatically.

One incident per breached rule per site: while an incident opened by a
rule is still unresolved, further breaches of that same rule don't open
duplicates — the responders already have it in front of them.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.sites.models import Site

from .models import IncidentEvent, SafetyIncident, SafetyRule

# (metric, comparator, threshold, incident_type, risk_score)
DEFAULT_RULES = [
    ("co_ppm", "gt", 35, "gas_threshold", 75),
    ("h2s_ppm", "gt", 10, "gas_threshold", 85),
    ("ch4_pct_lel", "gt", 10, "gas_threshold", 85),
    ("o2_pct", "lt", 19.5, "gas_threshold", 80),
    ("co2_ppm", "gt", 5000, "gas_threshold", 60),
    ("slope_angle_deg", "gt", 45, "slope_failure", 70),
    ("displacement_rate_mm_per_h", "gt", 1.0, "structural_instability", 85),
]

METRIC_LABEL = {
    "co_ppm": ("CO", "ppm"), "h2s_ppm": ("H₂S", "ppm"), "ch4_pct_lel": ("CH₄", "% LEL"), "o2_pct": ("O₂", "%"),
    "co2_ppm": ("CO₂", "ppm"), "slope_angle_deg": ("Slope angle", "°"),
    "displacement_rate_mm_per_h": ("Displacement rate", "mm/h"),
}


async def ensure_default_rules(db: AsyncSession, organisation_id: uuid.UUID) -> None:
    exists = await db.scalar(select(SafetyRule.id).where(SafetyRule.organisation_id == organisation_id).limit(1))
    if exists:
        return
    for metric, comparator, threshold, incident_type, risk in DEFAULT_RULES:
        db.add(SafetyRule(
            organisation_id=organisation_id, metric=metric, comparator=comparator, threshold=threshold,
            incident_type=incident_type, risk_score=risk,
        ))
    await db.flush()


def _breaches(rule: SafetyRule, value: float) -> bool:
    return value > rule.threshold if rule.comparator == "gt" else value < rule.threshold


def _worse(rule: SafetyRule, a: float, b: float) -> bool:
    return a > b if rule.comparator == "gt" else a < b


async def evaluate_readings(db: AsyncSession, device, readings: list[dict]) -> list[SafetyIncident]:
    """readings: [{"values": {...}, "recorded_at": dt, "lat": x|None, "lng": y|None}].
    Returns incidents created (already added to the session, not committed)."""
    await ensure_default_rules(db, device.organisation_id)
    rules = (await db.execute(
        select(SafetyRule).where(
            SafetyRule.organisation_id == device.organisation_id,
            SafetyRule.enabled.is_(True),
            (SafetyRule.site_id.is_(None)) | (SafetyRule.site_id == device.site_id),
        )
    )).scalars().all()
    # A site-specific rule for a metric replaces the org-wide one.
    site_metrics = {r.metric for r in rules if r.site_id is not None}
    rules = [r for r in rules if r.site_id is not None or r.metric not in site_metrics]

    worst: dict[uuid.UUID, tuple[SafetyRule, float, dict]] = {}
    for reading in readings:
        for rule in rules:
            value = reading["values"].get(rule.metric)
            if not isinstance(value, (int, float)) or not _breaches(rule, value):
                continue
            current = worst.get(rule.id)
            if current is None or _worse(rule, value, current[1]):
                worst[rule.id] = (rule, value, reading)
    if not worst:
        return []

    already_open = set((await db.execute(
        select(SafetyIncident.rule_id).where(
            SafetyIncident.rule_id.in_(list(worst)),
            SafetyIncident.site_id == device.site_id,
            SafetyIncident.status != "resolved",
        )
    )).scalars().all())

    site = await db.get(Site, device.site_id)
    created = []
    for rule_id, (rule, value, reading) in worst.items():
        if rule_id in already_open:
            continue
        label, unit = METRIC_LABEL.get(rule.metric, (rule.metric, ""))
        sign = ">" if rule.comparator == "gt" else "<"
        description = (
            f"Automatic alert: {label} {value:g} {unit} breached the {sign} {rule.threshold:g} {unit} threshold "
            f"(sensor {device.name})."
        ).replace("  ", " ")
        source = f"Sensor · {device.name}"
        incident = SafetyIncident(
            organisation_id=device.organisation_id, site_id=device.site_id, incident_type=rule.incident_type,
            risk_score=rule.risk_score, sensor_readings=reading["values"],
            gps_lat=reading.get("lat") if reading.get("lat") is not None else (site.lat if site else None),
            gps_lng=reading.get("lng") if reading.get("lng") is not None else (site.lng if site else None),
            description=description, source_device_id=device.id, rule_id=rule.id, source_label=source,
            status="open", created_at=datetime.now(timezone.utc),
        )
        db.add(incident)
        await db.flush()
        db.add(IncidentEvent(incident_id=incident.id, event_type="reported", note=description, actor_name=source))
        created.append(incident)
    return created
