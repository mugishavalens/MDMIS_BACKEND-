from rest_framework.routers import DefaultRouter

from .views import CustodyEventViewSet, MineralBatchViewSet

router = DefaultRouter()
router.register('events', CustodyEventViewSet, basename='custody-event')
router.register('', MineralBatchViewSet, basename='mineral-batch')

urlpatterns = router.urls
