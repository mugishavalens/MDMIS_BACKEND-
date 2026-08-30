import uuid

from django.db import models

from accounts.models import Organisation
from traceability.models import MineralBatch

SHIPMENT_STATUS_CHOICES = [
    ('loading', 'Loading'),
    ('in-transit', 'In Transit'),
    ('delayed', 'Delayed'),
    ('delivered', 'Delivered'),
]


class Shipment(models.Model):
    """SRS Section 4.10 (Transportation Tracking) / REQ-TRANS-001.
    Not a dedicated table in SRS Section 7 — modelled here to back the
    frontend's Fleet Management view (frontend/lib/mdmis-data.ts `Shipment`)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='shipments')
    batch = models.ForeignKey(MineralBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name='shipments')

    origin_name = models.CharField(max_length=255)
    origin_lat = models.DecimalField(max_digits=9, decimal_places=6)
    origin_lng = models.DecimalField(max_digits=9, decimal_places=6)
    destination_name = models.CharField(max_length=255)
    destination_lat = models.DecimalField(max_digits=9, decimal_places=6)
    destination_lng = models.DecimalField(max_digits=9, decimal_places=6)

    driver = models.CharField(max_length=255, blank=True)
    vehicle = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=12, choices=SHIPMENT_STATUS_CHOICES, default='loading')
    progress_pct = models.PositiveSmallIntegerField(default=0)
    eta_hours = models.DecimalField(max_digits=6, decimal_places=1, default=0)
    weight_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gps_integrity = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Shipment {self.id} ({self.status})'
