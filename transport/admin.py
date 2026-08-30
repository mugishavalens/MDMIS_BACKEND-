from django.contrib import admin

from .models import Shipment


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'origin_name', 'destination_name', 'status', 'progress_pct', 'organisation')
    list_filter = ('status', 'organisation')
