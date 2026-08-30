from django.contrib import admin

from .models import CustodyEvent, MineralBatch


@admin.register(MineralBatch)
class MineralBatchAdmin(admin.ModelAdmin):
    list_display = ('coc_id', 'site', 'mineral_type', 'weight_kg', 'status', 'created_at')
    list_filter = ('status', 'mineral_type', 'organisation')
    search_fields = ('coc_id',)


@admin.register(CustodyEvent)
class CustodyEventAdmin(admin.ModelAdmin):
    list_display = ('batch', 'event_type', 'from_party', 'to_party', 'timestamp')
    list_filter = ('event_type',)
