from rest_framework import permissions, viewsets

from common.permissions import OrgScopedQuerysetMixin

from .models import Shipment
from .serializers import ShipmentSerializer


class ShipmentViewSet(OrgScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Shipment.objects.select_related('batch')
    serializer_class = ShipmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    org_field = 'organisation_id'
    filterset_fields = ['status', 'batch']
