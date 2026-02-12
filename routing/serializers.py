"""
Serializers for routing app
"""
from rest_framework import serializers
from .models import Location, RiskScore, Route, RouteSegment


class LocationSerializer(serializers.ModelSerializer):
    """Serializer for Location model"""
    
    class Meta:
        model = Location
        fields = [
            'id', 'latitude', 'longitude', 'name', 'address',
            'location_type', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class RiskScoreSerializer(serializers.ModelSerializer):
    """Serializer for RiskScore model"""
    location = LocationSerializer(read_only=True)
    location_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = RiskScore
        fields = [
            'id', 'location', 'location_id', 'risk_level', 'time_of_day',
            'day_of_week', 'crime_rate', 'lighting_score', 'crowd_density',
            'incident_history', 'calculated_at'
        ]
        read_only_fields = ['id', 'calculated_at']


class RouteSegmentSerializer(serializers.ModelSerializer):
    """Serializer for RouteSegment model"""
    start_location = LocationSerializer(read_only=True)
    end_location = LocationSerializer(read_only=True)
    
    class Meta:
        model = RouteSegment
        fields = [
            'id', 'start_location', 'end_location', 'sequence_order',
            'segment_distance', 'segment_duration', 'segment_risk_score'
        ]
        read_only_fields = ['id']


class RouteSerializer(serializers.ModelSerializer):
    """Serializer for Route model"""
    origin = LocationSerializer(read_only=True)
    destination = LocationSerializer(read_only=True)
    waypoints = LocationSerializer(many=True, read_only=True)
    segments = RouteSegmentSerializer(many=True, read_only=True)
    
    class Meta:
        model = Route
        fields = [
            'id', 'user', 'origin', 'destination', 'waypoints', 'segments',
            'path_data', 'total_distance', 'estimated_duration', 'overall_risk_score',
            'route_type', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']


class RouteRequestSerializer(serializers.Serializer):
    """Serializer for route prediction requests"""
    origin_lat = serializers.FloatField()
    origin_lng = serializers.FloatField()
    destination_lat = serializers.FloatField()
    destination_lng = serializers.FloatField()
    route_type = serializers.ChoiceField(
        choices=['safest', 'fastest', 'balanced'],
        default='safest'
    )
    time_of_day = serializers.TimeField(required=False, allow_null=True)
    day_of_week = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=6)


class RouteResponseSerializer(serializers.Serializer):
    """Serializer for route prediction responses"""
    route = RouteSerializer()
    alternatives = RouteSerializer(many=True, required=False)
    computation_time = serializers.FloatField()
    message = serializers.CharField(required=False)
