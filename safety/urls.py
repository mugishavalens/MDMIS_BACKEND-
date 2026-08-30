from rest_framework.routers import DefaultRouter

from .views import SafetyIncidentViewSet

router = DefaultRouter()
router.register('', SafetyIncidentViewSet, basename='safety-incident')

urlpatterns = router.urls
