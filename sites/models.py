from django.db import models

from accounts.models import Organisation

MINERAL_CHOICES = [
    ('cassiterite', 'Cassiterite'),
    ('coltan', 'Coltan'),
    ('wolframite', 'Wolframite'),
    ('gold', 'Gold'),
    ('beryl', 'Beryl'),
    ('lithium', 'Lithium'),
    ('cobalt', 'Cobalt'),
    ('copper', 'Copper'),
    ('gemstone', 'Gemstone'),
    ('unknown', 'Unknown'),
]
RISK_CHOICES = [('low', 'Low'), ('moderate', 'Moderate'), ('high', 'High'), ('critical', 'Critical')]
STATUS_CHOICES = [
    ('active', 'Active'),
    ('surveying', 'Surveying'),
    ('flagged', 'Flagged'),
    ('depleted', 'Depleted'),
]


class Site(models.Model):
    """REQ-SITE-001. Mining site / concession.

    Note: the SRS models `sites.id` as a UUID with a separate `site_code`
    (e.g. "RW-COL-001"). Here the site_code IS the primary key so it maps
    1:1 with the frontend's existing site IDs (RW-RTG-01, ...) and the
    static terrain assets keyed by that same id under
    frontend/public/terrain/<id>/. Simpler for now; split into a real UUID
    PK + site_code column later if a site is ever renumbered.
    """

    id = models.CharField(max_length=32, primary_key=True)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='sites')
    name = models.CharField(max_length=255)
    district = models.CharField(max_length=100, blank=True)
    country_code = models.CharField(max_length=2, default='RW')

    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lng = models.DecimalField(max_digits=9, decimal_places=6)

    primary_mineral = models.CharField(max_length=20, choices=MINERAL_CHOICES)
    secondary_minerals = models.JSONField(default=list, blank=True)
    grade_pct = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    confidence = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    estimated_tonnage = models.BigIntegerField(default=0)
    safety_score = models.PositiveSmallIntegerField(default=0)
    risk_level = models.CharField(max_length=10, choices=RISK_CHOICES, default='low')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='active')
    last_scan = models.DateTimeField(null=True, blank=True)
    depth_meters = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.id} — {self.name}'
