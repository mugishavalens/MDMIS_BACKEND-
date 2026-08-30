from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.permissions import OrgScopedQuerysetMixin

from .models import SafetyIncident
from .serializers import SafetyIncidentSerializer


class SafetyIncidentViewSet(OrgScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = SafetyIncident.objects.select_related('site', 'zone')
    serializer_class = SafetyIncidentSerializer
    permission_classes = [permissions.IsAuthenticated]
    org_field = 'organisation_id'
    filterset_fields = ['site', 'status', 'incident_type']

    def perform_create(self, serializer):
        serializer.save(organisation_id=self.request.user.organisation_id, reported_by=self.request.user)

    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        """REQ-SAFE-003: Safety Officers acknowledge an open incident."""
        incident = self.get_object()
        incident.status = 'acknowledged'
        incident.acknowledged_by = request.user
        incident.acknowledged_at = timezone.now()
        incident.save(update_fields=['status', 'acknowledged_by', 'acknowledged_at'])
        return Response(self.get_serializer(incident).data)
