"""
Models for routing app - handles routes, locations, and risk scores
"""
from django.db import models
from django.contrib.auth.models import User


class Location(models.Model):
    """Represents a geographic location with coordinates and metadata"""
    latitude = models.FloatField()
    longitude = models.FloatField()
    name = models.CharField(max_length=255, blank=True)
    address = models.TextField(blank=True)
    location_type = models.CharField(
        max_length=50,
        choices=[
            ('waypoint', 'Waypoint'),
            ('landmark', 'Landmark'),
            ('intersection', 'Intersection'),
        ],
        default='waypoint'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['latitude', 'longitude']),
        ]

    def __str__(self):
        return f"{self.name or 'Location'} ({self.latitude}, {self.longitude})"


class RiskScore(models.Model):
    """Stores ML-based risk scores for locations"""
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='risk_scores')
    risk_level = models.FloatField(help_text="Risk score between 0.0 and 1.0")
    time_of_day = models.TimeField(null=True, blank=True)
    day_of_week = models.IntegerField(
        null=True,
        blank=True,
        help_text="0=Monday, 6=Sunday"
    )
    crime_rate = models.FloatField(null=True, blank=True)
    lighting_score = models.FloatField(null=True, blank=True)
    crowd_density = models.FloatField(null=True, blank=True)
    incident_history = models.IntegerField(default=0)
    calculated_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['location', 'time_of_day']),
            models.Index(fields=['risk_level']),
        ]

    def __str__(self):
        return f"Risk Score {self.risk_level} for {self.location}"


class Route(models.Model):
    """Represents a route between origin and destination"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='routes')
    origin = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name='routes_from'
    )
    destination = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name='routes_to'
    )
    waypoints = models.ManyToManyField(
        Location,
        related_name='route_waypoints',
        blank=True
    )
    total_distance = models.FloatField(help_text="Distance in kilometers")
    estimated_duration = models.FloatField(help_text="Duration in minutes")
    overall_risk_score = models.FloatField()
    route_type = models.CharField(
        max_length=50,
        choices=[
            ('safest', 'Safest Route'),
            ('fastest', 'Fastest Route'),
            ('balanced', 'Balanced Route'),
        ],
        default='safest'
    )
    # Optimization: Store path as JSON to avoid thousands of RouteSegment rows
    path_data = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Route from {self.origin} to {self.destination}"


class RouteSegment(models.Model):
    """Represents a segment of a route between two consecutive locations"""
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name='segments')
    start_location = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name='segment_starts'
    )
    end_location = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name='segment_ends'
    )
    sequence_order = models.IntegerField()
    segment_distance = models.FloatField()
    segment_duration = models.FloatField()
    segment_risk_score = models.FloatField()
    
    class Meta:
        ordering = ['sequence_order']
        unique_together = ['route', 'sequence_order']

    def __str__(self):
        return f"Segment {self.sequence_order} of Route {self.route.id}"
