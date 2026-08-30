import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import UserManager

COUNTRY_CHOICES = [
    ('RW', 'Rwanda'),
    ('CD', 'DR Congo'),
    ('UG', 'Uganda'),
    ('TZ', 'Tanzania'),
    ('KE', 'Kenya'),
    ('BI', 'Burundi'),
]


class Organisation(models.Model):
    """Multi-tenant isolation boundary. SRS Section 7 / Auth Design Section 6:
    every client-data table carries an org_id and every query is scoped to it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100, unique=True)
    registration_number = models.CharField(max_length=100, blank=True)
    country_code = models.CharField(max_length=2, choices=COUNTRY_CHOICES, default='RW')
    license_tier = models.CharField(max_length=50, default='trial')
    primary_contact_email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class User(AbstractBaseUser, PermissionsMixin):
    """SRS Section 3.1 role matrix — 10 roles, RBAC enforced at the API
    permission layer (see common.permissions.role_required)."""

    ROLE_CHOICES = [
        ('field_operator', 'Field Operator'),
        ('drone_operator', 'Drone Operator'),
        ('geologist', 'Geologist'),
        ('mine_manager', 'Mine Manager'),
        ('safety_officer', 'Safety Officer'),
        ('compliance_manager', 'Compliance Manager'),
        ('government_auditor', 'Government Auditor'),
        ('investor', 'Investor'),
        ('company_admin', 'Company Admin'),
        ('system_admin', 'System Admin'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name='users', null=True, blank=True,
    )
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    role = models.CharField(max_length=32, choices=ROLE_CHOICES, default='field_operator')

    # is_active=False until an admin approves the access request
    # (matches the "Request submitted" flow on the frontend register page).
    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.email

    @property
    def initials(self):
        parts = [p for p in self.full_name.split() if p]
        if not parts:
            return self.email[:2].upper()
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()
