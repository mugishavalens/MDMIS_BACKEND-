import uuid

from django.db import models

from accounts.models import Organisation, User
from sites.models import Site

BATCH_STATUS_CHOICES = [
    ('scanned', 'Scanned'),
    ('weighed', 'Weighed'),
    ('graded', 'Graded'),
    ('in_storage', 'In Storage'),
    ('in_transit', 'In Transit'),
    ('at_processing', 'At Processing'),
    ('exported', 'Exported'),
    ('rejected', 'Rejected'),
]
CUSTODY_EVENT_CHOICES = [
    ('extraction', 'Extraction'),
    ('weigh_in', 'Weigh-in'),
    ('storage_in', 'Storage'),
    ('dispatch', 'Dispatch'),
    ('waypoint', 'Waypoint'),
    ('receipt', 'Receipt'),
    ('processing', 'Processing'),
    ('export', 'Export'),
    ('rejection', 'Rejection'),
]


class MineralBatch(models.Model):
    """SRS Section 7.3 / REQ-TRACE-001. coc_id format:
    COC-{SITE_CODE}-{YYYYMMDD}-{SEQUENCE}, immutable once assigned."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    coc_id = models.CharField(max_length=64, unique=True)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='mineral_batches')
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='mineral_batches')
    mineral_type = models.CharField(max_length=20)

    origin_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    origin_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    extraction_timestamp = models.DateTimeField(null=True, blank=True)

    weight_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    grade_detected = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    grade_confirmed = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=BATCH_STATUS_CHOICES, default='scanned')
    qr_code_url = models.URLField(blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='batches_created')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.coc_id


class CustodyEvent(models.Model):
    """SRS Section 7.4 / REQ-TRACE-003: immutable once created — no update
    or delete endpoint is exposed; corrections must be new events."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(MineralBatch, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=20, choices=CUSTODY_EVENT_CHOICES)
    from_party = models.CharField(max_length=255, blank=True)
    to_party = models.CharField(max_length=255, blank=True)
    gps_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    quantity_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    authorised_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='custody_events_authorised')
    timestamp = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f'{self.batch.coc_id} · {self.event_type}'
