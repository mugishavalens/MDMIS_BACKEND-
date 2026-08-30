from rest_framework.routers import DefaultRouter

from .views import MineralZoneViewSet, ScanSessionViewSet

router = DefaultRouter()
router.register('zones', MineralZoneViewSet, basename='mineral-zone')
router.register('', ScanSessionViewSet, basename='scan-session')

urlpatterns = router.urls
