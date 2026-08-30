from rest_framework import permissions, viewsets

from common.permissions import OrgScopedQuerysetMixin

from .models import Site
from .serializers import SiteSerializer


class SiteViewSet(OrgScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Site.objects.all()
    serializer_class = SiteSerializer
    permission_classes = [permissions.IsAuthenticated]
    org_field = 'organisation_id'
