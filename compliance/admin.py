from django.contrib import admin

from .models import ComplianceReport


@admin.register(ComplianceReport)
class ComplianceReportAdmin(admin.ModelAdmin):
    list_display = ('title', 'framework', 'period', 'status', 'coverage_pct', 'organisation')
    list_filter = ('framework', 'status', 'organisation')
