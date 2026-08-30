from rest_framework import serializers

from .models import CustodyEvent, MineralBatch


class CustodyEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustodyEvent
        fields = [
            'id', 'batch', 'event_type', 'from_party', 'to_party',
            'gps_lat', 'gps_lng', 'quantity_kg', 'authorised_by', 'timestamp', 'notes',
        ]
        read_only_fields = ['id', 'timestamp']


class MineralBatchSerializer(serializers.ModelSerializer):
    events = CustodyEventSerializer(many=True, read_only=True)

    class Meta:
        model = MineralBatch
        fields = [
            'id', 'coc_id', 'site', 'mineral_type', 'origin_lat', 'origin_lng',
            'extraction_timestamp', 'weight_kg', 'grade_detected', 'grade_confirmed',
            'status', 'qr_code_url', 'created_by', 'created_at', 'events',
        ]
        read_only_fields = ['id', 'coc_id', 'created_at']
