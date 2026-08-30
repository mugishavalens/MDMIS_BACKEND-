from django.contrib import admin

from .models import SafetyIncident


@admin.register(SafetyIncident)
class SafetyIncidentAdmin(admin.ModelAdmin):
    list_display = ('id', 'site', 'incident_type', 'risk_score', 'status', 'created_at')
    list_filter = ('status', 'incident_type', 'organisation')
