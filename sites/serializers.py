from rest_framework import serializers

from .models import Site


class SiteSerializer(serializers.ModelSerializer):
    """Field names/casing mirror frontend/lib/mdmis-data.ts `DetectionSite`
    so this endpoint can be dropped straight into the map explorer later."""

    primaryMineral = serializers.CharField(source='primary_mineral')
    secondaryMinerals = serializers.JSONField(source='secondary_minerals', required=False)
    gradePct = serializers.DecimalField(source='grade_pct', max_digits=6, decimal_places=2)
    estimatedTonnage = serializers.IntegerField(source='estimated_tonnage')
    safetyScore = serializers.IntegerField(source='safety_score')
    riskLevel = serializers.CharField(source='risk_level')
    lastScan = serializers.DateTimeField(source='last_scan', required=False, allow_null=True)
    depthMeters = serializers.IntegerField(source='depth_meters')

    class Meta:
        model = Site
        fields = [
            'id', 'name', 'district', 'lat', 'lng', 'primaryMineral', 'secondaryMinerals',
            'gradePct', 'confidence', 'estimatedTonnage', 'safetyScore', 'riskLevel',
            'status', 'lastScan', 'depthMeters',
        ]
