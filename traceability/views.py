from datetime import datetime, timezone

from rest_framework import mixins, permissions, viewsets

from common.permissions import OrgScopedQuerysetMixin

from .models import CustodyEvent, MineralBatch
from .serializers import CustodyEventSerializer, MineralBatchSerializer


class MineralBatchViewSet(OrgScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = MineralBatch.objects.select_related('site', 'created_by').prefetch_related('events')
    serializer_class = MineralBatchSerializer
    permission_classes = [permissions.IsAuthenticated]
    org_field = 'organisation_id'
    filterset_fields = ['site', 'status', 'mineral_type']

    def perform_create(self, serializer):
        site = serializer.validated_data['site']
        today = datetime.now(timezone.utc).strftime('%Y%m%d')
        seq = MineralBatch.objects.filter(coc_id__startswith=f'COC-{site.id}-{today}').count() + 1
        coc_id = f'COC-{site.id}-{today}-{seq:04d}'
        serializer.save(
            organisation_id=self.request.user.organisation_id,
            created_by=self.request.user,
            coc_id=coc_id,
        )


class CustodyEventViewSet(OrgScopedQuerysetMixin, mixins.CreateModelMixin, mixins.ListModelMixin,
                           mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """REQ-TRACE-003: custody events are immutable — create/list/retrieve only,
    no update or delete."""

    queryset = CustodyEvent.objects.select_related('batch')
    serializer_class = CustodyEventSerializer
    permission_classes = [permissions.IsAuthenticated]
    org_field = 'batch__organisation_id'
    filterset_fields = ['batch', 'event_type']

    def perform_create(self, serializer):
        serializer.save(authorised_by=self.request.user)
