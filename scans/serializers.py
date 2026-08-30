from rest_framework import serializers

from .models import MineralZone, ScanSession


class MineralZoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = MineralZone
        fields = [
            'id', 'scan_session', 'mineral_type', 'confidence_score',
            'estimated_depth_m', 'estimated_tonnage', 'status', 'flagged_anomaly', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class ScanSessionSerializer(serializers.ModelSerializer):
    zones = MineralZoneSerializer(many=True, read_only=True)

    class Meta:
        model = ScanSession
        fields = [
            'id', 'site', 'operator', 'sensor_types', 'status',
            'uploaded_at', 'processed_at', 'zones',
        ]
        read_only_fields = ['id', 'uploaded_at']
