from rest_framework import serializers

from .models import ComplianceReport


class ComplianceReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplianceReport
        fields = [
            'id', 'title', 'framework', 'period', 'status', 'coverage_pct',
            'flagged_lots', 'submitted_to', 'generated_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
