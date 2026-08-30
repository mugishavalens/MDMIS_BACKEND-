"""
Shared RBAC + multi-tenant isolation helpers.

Per SRS Section 2.2 (Multi-Tenant Data Isolation): every query MUST filter
by org_id at the application layer, enforced in code — not only in the
database. Per Section 3.2 REQ-ACC-005: every endpoint MUST check role
before running business logic; insufficient role -> 403.
"""
from rest_framework.permissions import BasePermission


class RoleRequired(BasePermission):
    """Base permission class. Subclass via role_required(*roles) below.

    system_admin always passes (SRS 3.1: MDMIS System Admin has full
    platform access).
    """

    allowed_roles: tuple = ()

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.role == 'system_admin':
            return True
        return user.role in self.allowed_roles


def role_required(*roles):
    """Factory: role_required('mine_manager', 'company_admin') -> Permission class."""
    return type('_RoleRequired', (RoleRequired,), {'allowed_roles': roles})


class OrgScopedQuerysetMixin:
    """Mixin for ModelViewSets: scopes list/detail queries to the caller's
    organisation. system_admin sees every organisation's records.

    Set `org_field` if the FK to Organisation isn't named `organisation`.
    """

    org_field = 'organisation_id'

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.is_authenticated:
            return qs.none()
        if user.role == 'system_admin':
            return qs
        return qs.filter(**{self.org_field: user.organisation_id})

    def perform_create(self, serializer):
        user = self.request.user
        field_name = self.org_field[:-3] if self.org_field.endswith('_id') else self.org_field
        extra = {}
        if field_name not in serializer.validated_data:
            extra[field_name + '_id'] = user.organisation_id
        serializer.save(**extra)
