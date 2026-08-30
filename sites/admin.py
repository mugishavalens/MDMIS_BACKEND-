from django.contrib import admin

from .models import Site


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'organisation', 'primary_mineral', 'status', 'risk_level', 'safety_score')
    list_filter = ('status', 'risk_level', 'primary_mineral', 'organisation')
    search_fields = ('id', 'name', 'district')
