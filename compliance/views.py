from rest_framework import permissions, viewsets

from common.permissions import OrgScopedQuerysetMixin

from .models import ComplianceReport
from .serializers import ComplianceReportSerializer


class ComplianceReportViewSet(OrgScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = ComplianceReport.objects.all()
    serializer_class = ComplianceReportSerializer
    permission_classes = [permissions.IsAuthenticated]
    org_field = 'organisation_id'
    filterset_fields = ['framework', 'status']

    def perform_create(self, serializer):
        serializer.save(organisation_id=self.request.user.organisation_id, generated_by=self.request.user)
