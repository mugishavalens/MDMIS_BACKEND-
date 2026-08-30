from rest_framework import serializers

from .models import Shipment


class ShipmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shipment
        fields = [
            'id', 'batch', 'origin_name', 'origin_lat', 'origin_lng',
            'destination_name', 'destination_lat', 'destination_lng',
            'driver', 'vehicle', 'status', 'progress_pct', 'eta_hours',
            'weight_kg', 'gps_integrity', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
