from rest_framework import serializers

from .models import SafetyIncident


class SafetyIncidentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SafetyIncident
        fields = [
            'id', 'site', 'zone', 'incident_type', 'risk_score', 'sensor_readings',
            'gps_lat', 'gps_lng', 'reported_by', 'acknowledged_by', 'acknowledged_at',
            'status', 'description', 'created_at',
        ]
        read_only_fields = ['id', 'created_at', 'reported_by']
