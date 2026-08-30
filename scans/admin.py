from django.contrib import admin

from .models import MineralZone, ScanSession


@admin.register(ScanSession)
class ScanSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'site', 'organisation', 'status', 'uploaded_at')
    list_filter = ('status', 'organisation')


@admin.register(MineralZone)
class MineralZoneAdmin(admin.ModelAdmin):
    list_display = ('id', 'scan_session', 'mineral_type', 'confidence_score', 'status', 'flagged_anomaly')
    list_filter = ('status', 'mineral_type', 'flagged_anomaly')
