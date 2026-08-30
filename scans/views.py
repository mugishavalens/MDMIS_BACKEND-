from rest_framework import permissions, viewsets

from common.permissions import OrgScopedQuerysetMixin

from .models import MineralZone, ScanSession
from .serializers import MineralZoneSerializer, ScanSessionSerializer


class ScanSessionViewSet(OrgScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = ScanSession.objects.select_related('site', 'operator').prefetch_related('zones')
    serializer_class = ScanSessionSerializer
    permission_classes = [permissions.IsAuthenticated]
    org_field = 'organisation_id'
    filterset_fields = ['site', 'status']

    def perform_create(self, serializer):
        serializer.save(organisation_id=self.request.user.organisation_id, operator=self.request.user)


class MineralZoneViewSet(OrgScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = MineralZone.objects.select_related('scan_session')
    serializer_class = MineralZoneSerializer
    permission_classes = [permissions.IsAuthenticated]
    org_field = 'organisation_id'
    filterset_fields = ['scan_session', 'status', 'mineral_type']
