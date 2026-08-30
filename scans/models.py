import uuid

from django.db import models

from accounts.models import Organisation, User
from sites.models import Site

SENSOR_CHOICES = [
    ('hyperspectral', 'Hyperspectral'),
    ('gpr', 'Ground Penetrating Radar'),
    ('em', 'Electromagnetic'),
    ('magnetometer', 'Magnetometer'),
    ('gamma', 'Gamma-Ray Spectrometer'),
    ('satellite', 'Sentinel-2 Satellite'),
    ('lab', 'Lab Spectrometer'),
]
SCAN_STATUS_CHOICES = [
    ('uploaded', 'Uploaded'),
    ('preprocessing', 'Preprocessing'),
    ('ready', 'Ready'),
    ('classifying', 'Classifying'),
    ('complete', 'Complete'),
    ('failed', 'Failed'),
]
ZONE_STATUS_CHOICES = [
    ('unconfirmed', 'Unconfirmed'),
    ('geologist_reviewed', 'Geologist Reviewed'),
    ('lab_confirmed', 'Lab Confirmed'),
    ('rejected', 'Rejected'),
]


class ScanSession(models.Model):
    """SRS Section 7.1. Created each time sensor data is uploaded for a site visit."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='scan_sessions')
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='scan_sessions')
    operator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='scan_sessions')
    sensor_types = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=SCAN_STATUS_CHOICES, default='uploaded')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'ScanSession {self.id} ({self.site_id})'


class MineralZone(models.Model):
    """SRS Section 7.2. One record per detected mineral zone."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scan_session = models.ForeignKey(ScanSession, on_delete=models.CASCADE, related_name='zones')
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='mineral_zones')
    mineral_type = models.CharField(max_length=20)
    confidence_score = models.PositiveSmallIntegerField(default=0)
    estimated_depth_m = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    estimated_tonnage = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=ZONE_STATUS_CHOICES, default='unconfirmed')
    flagged_anomaly = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.mineral_type} zone ({self.confidence_score}%)'
