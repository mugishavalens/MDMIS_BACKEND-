import uuid

from django.db import models

from accounts.models import Organisation, User

FRAMEWORK_CHOICES = [
    ('oecd', 'OECD Due Diligence'),
    ('itsci', 'ITSCI'),
    ('rmb', 'RMB Licensing'),
    ('eu', 'EU Conflict Minerals'),
]
REPORT_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('submitted', 'Submitted'),
    ('approved', 'Approved'),
    ('overdue', 'Overdue'),
]


class ComplianceReport(models.Model):
    """SRS Section 4.12 (Reporting & Export) / REQ-RPT-001..004.
    Tracks generated compliance report metadata; the SRS defers actual
    PDF/XML generation to a later phase (Celery background job)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='compliance_reports')
    title = models.CharField(max_length=255)
    framework = models.CharField(max_length=10, choices=FRAMEWORK_CHOICES)
    period = models.CharField(max_length=32)
    status = models.CharField(max_length=12, choices=REPORT_STATUS_CHOICES, default='draft')
    coverage_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    flagged_lots = models.PositiveIntegerField(default=0)
    submitted_to = models.CharField(max_length=255, blank=True)
    generated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='compliance_reports')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title
