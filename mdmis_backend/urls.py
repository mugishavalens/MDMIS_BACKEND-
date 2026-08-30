from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(request):
    return JsonResponse({'status': 'ok', 'service': 'mdmis-backend'})


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/health/', health, name='health'),
    path('api/auth/', include('accounts.urls')),
    path('api/sites/', include('sites.urls')),
    path('api/scans/', include('scans.urls')),
    path('api/traceability/', include('traceability.urls')),
    path('api/safety/', include('safety.urls')),
    path('api/transport/', include('transport.urls')),
    path('api/compliance/', include('compliance.urls')),
]
