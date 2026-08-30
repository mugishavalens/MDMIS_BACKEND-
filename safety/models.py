import uuid

from django.db import models

from accounts.models import Organisation, User
from scans.models import MineralZone
from sites.models import Site

INCIDENT_TYPE_CHOICES = [
    ('gas_threshold', 'Gas Threshold'),
    ('structural_instability', 'Structural Instability'),
    ('slope_failure', 'Slope Failure'),
    ('equipment', 'Equipment'),
    ('proximity_breach', 'Proximity Breach'),
    ('environmental', 'Environmental'),
    ('other', 'Other'),
]
INCIDENT_STATUS_CHOICES = [
    ('open', 'Open'),
    ('acknowledged', 'Acknowledged'),
    ('resolved', 'Resolved'),
    ('escalated', 'Escalated'),
]


class SafetyIncident(models.Model):
    """SRS Section 7.5 / REQ-SAFE-004. Immutable log; only status/acknowledgement
    fields are updatable after creation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='safety_incidents')
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='safety_incidents')
    zone = models.ForeignKey(MineralZone, on_delete=models.SET_NULL, null=True, blank=True, related_name='safety_incidents')

    incident_type = models.CharField(max_length=30, choices=INCIDENT_TYPE_CHOICES)
    risk_score = models.PositiveSmallIntegerField(default=0)
    sensor_readings = models.JSONField(default=dict, blank=True)
    gps_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    reported_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='safety_incidents_reported')
    acknowledged_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='safety_incidents_acknowledged')
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=INCIDENT_STATUS_CHOICES, default='open')
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.incident_type} @ {self.site_id} ({self.status})'
