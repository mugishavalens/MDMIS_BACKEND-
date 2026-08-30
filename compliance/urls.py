from rest_framework.routers import DefaultRouter

from .views import ComplianceReportViewSet

router = DefaultRouter()
router.register('', ComplianceReportViewSet, basename='compliance-report')

urlpatterns = router.urls
