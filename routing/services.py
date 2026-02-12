"""
Service layer for routing app
Contains business logic for route prediction and risk scoring
"""
import time
from typing import Dict, List, Tuple, Optional, Any
from datetime import time as dt_time, datetime
import numpy as np
import pandas as pd
import networkx as nx
import osmnx as ox
import joblib
import os
from django.conf import settings
from django.contrib.auth.models import User

from .models import Location, RiskScore, Route, RouteSegment

# Global cache for heavy resources
_MODEL = None

def get_model():
    global _MODEL
    if _MODEL is None:
        model_path = os.path.join(settings.BASE_DIR, "ml_engine/training/models/risk_model.pkl")
        print(f"Loading risk model from {model_path}...")
        try:
            _MODEL = joblib.load(model_path)
            print("Model loaded.")
        except Exception as e:
            print(f"Error loading model: {e}")
            raise e
    return _MODEL

class RiskScoringService:
    """
    Service for calculating ML-based location risk scores
    """
    
    def calculate_location_risk(
        self,
        location: Location,
        time_of_day: Optional[dt_time] = None,
        day_of_week: Optional[int] = None
    ) -> float:
        """
        Calculate risk score for a single location using ML model
        """
        model = get_model()
        
        if time_of_day is None:
            now = datetime.now()
            hour = now.hour
        else:
            hour = time_of_day.hour
            
        if day_of_week is None:
            day_of_week = datetime.now().weekday()
            
        # Create input features
        features = pd.DataFrame([{
            'Latitude': location.latitude,
            'Longitude': location.longitude,
            'hour': hour,
            'day': day_of_week,
            'crime_enc': 1,
            'loc_enc': 1,
            'Arrest': 0,
            'Domestic': 0
        }])
        
        try:
            risk = model.predict(features)[0]
            return float(risk)
        except Exception as e:
            print(f"Error calculating point risk: {e}")
            return 0.5  # Fallback

    def recalculate_route_risk(self, route: Route) -> Route:
        """
        Recalculate overall risk score for a route
        """
        segments = route.segments.all()
        if not segments:
            return route
        
        total_distance = sum(seg.segment_distance for seg in segments)
        weighted_risk = sum(
            seg.segment_risk_score * seg.segment_distance
            for seg in segments
        ) / total_distance if total_distance > 0 else 0.0
        
        route.overall_risk_score = weighted_risk
        route.save()
        return route


class DijkstraRoutingService:
    """
    Service implementing modified Dijkstra algorithm for safe route finding
    """

    def _get_local_graph(self, origin_lat, origin_lng, dest_lat, dest_lng):
        """
        Download a small graph for just the area needed.
        """
        # Buffer in degrees (approx 2-3km)
        margin = 0.02
        
        north = max(origin_lat, dest_lat) + margin
        south = min(origin_lat, dest_lat) - margin
        east = max(origin_lng, dest_lng) + margin
        west = min(origin_lng, dest_lng) - margin
        
        print(f"Downloading graph for bbox: N={north}, S={south}, E={east}, W={west}")
        
        try:
            ox.settings.user_agent = "Protego-AI-Safety-System/1.0 (vaibhav@example.com)"
            # network_type='drive' for cars/taxis. 'walk' for pedestrians.
            # Using 'drive' as per original code.
            G = ox.graph_from_bbox(north, south, east, west, network_type="drive")
            
            # Pre-calculate edge DataFrame for prediction
            edges_data = []
            for u, v, k, data in G.edges(keys=True, data=True):
                 # Get node coords
                 lat = G.nodes[u]['y']
                 lon = G.nodes[u]['x']
                 edges_data.append({
                     'u': u, 'v': v, 'k': k,
                     'Latitude': lat,
                     'Longitude': lon,
                     'crime_enc': 1,
                     'loc_enc': 1,
                     'Arrest': 0,
                     'Domestic': 0
                 })
            
            if not edges_data:
                raise Exception("Graph downloaded but no edges found in this area.")

            edges_df = pd.DataFrame(edges_data)
            return G, edges_df
            
        except Exception as e:
            print(f"Error downloading graph: {e}")
            raise e
    
    def find_safe_route(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        route_type: str = 'safest',
        time_of_day: Optional[dt_time] = None,
        day_of_week: Optional[int] = None
    ) -> Tuple[List[Dict], float]:
        """
        Find safe route using localized OSMnx graph and NetworkX
        Returns: Tuple(List of node data dicts, Total Risk Score)
        """
        try:
            # 0. Get Local Graph
            G, edges_df = self._get_local_graph(origin_lat, origin_lng, dest_lat, dest_lng)
            model = get_model()
            
            # 1. Update edge weights based on time
            if time_of_day is None:
                now = datetime.now()
                hour = now.hour
            else:
                hour = time_of_day.hour
                
            if day_of_week is None:
                day_of_week = datetime.now().weekday()
                
            # Fast vectorized prediction
            features_df = edges_df.copy()
            features_df['hour'] = hour
            features_df['day'] = day_of_week
            
            feature_cols = ['Latitude', 'Longitude', 'hour', 'day', 'crime_enc', 'loc_enc', 'Arrest', 'Domestic']
            
            try:
                risk_scores = model.predict(features_df[feature_cols])
            except Exception as e:
                print(f"Prediction error: {e}")
                # Fallback to zeros if model fails? No, better to fail loud or use defaults.
                # using default 0.5
                risk_scores = [0.5] * len(features_df)
                
            # Update graph weights
            weight_name = 'risk_weight'
            
            for idx, risk in enumerate(risk_scores):
                u = edges_df.iloc[idx]['u']
                v = edges_df.iloc[idx]['v']
                k = edges_df.iloc[idx]['k']
                
                # Combined weight formula
                length = G[u][v][k].get('length', 10.0) 
                
                if route_type == 'safest':
                    # Heavily penalize risk.
                    cost = length * (1.0 + float(risk) * 20.0)
                elif route_type == 'fastest':
                    cost = length
                else:
                    # Balanced
                    cost = length * (1.0 + float(risk) * 5.0)
                    
                G[u][v][k][weight_name] = cost
                G[u][v][k]['risk_score'] = float(risk)
                
            # 2. Find nearest nodes
            orig_node = ox.nearest_nodes(G, origin_lng, origin_lat)
            dest_node = ox.nearest_nodes(G, dest_lng, dest_lat)
            
            # 3. Shortest path
            route_nodes = nx.shortest_path(G, orig_node, dest_node, weight=weight_name)
            
            # 4. Extract path data
            path_data = []
            total_risk = 0.0
            count = 0
            
            for i, node_id in enumerate(route_nodes):
                node_obj = G.nodes[node_id]
                lat = node_obj['y']
                lng = node_obj['x']
                
                step_risk = 0.0
                if i < len(route_nodes) - 1:
                    next_node = route_nodes[i+1]
                    edge_data = G.get_edge_data(node_id, next_node)
                    if edge_data:
                        first_key = list(edge_data.keys())[0]
                        step_risk = edge_data[first_key].get('risk_score', 0.0)
                
                path_data.append({
                    'latitude': lat,
                    'longitude': lng,
                    'risk_score': step_risk
                })
                total_risk += step_risk
                count += 1
                
            avg_risk = total_risk / count if count > 0 else 0.0
            
            return path_data, avg_risk

        except nx.NetworkXNoPath:
            print("No path found in graph.")
            return [], 0.0
        except Exception as e:
            print(f"Error in find_safe_route: {e}")
            raise e


class RoutePredictionService:
    """
    Main service for route prediction
    """
    
    def __init__(self):
        self.risk_service = RiskScoringService()
        self.routing_service = DijkstraRoutingService()
    
    def predict_safe_route(
        self,
        origin_lat: float,
        origin_lng: float,
        destination_lat: float,
        destination_lng: float,
        route_type: str,
        user: User,
        time_of_day: Optional[dt_time] = None,
        day_of_week: Optional[int] = None
    ) -> Dict:
        """
        Orchestrate safe route prediction
        """
        start_time = time.time()
        
        # Find safe route using real OSM/NetworkX logic
        # Now uses on-demand downloading
        path_data, avg_risk = self.routing_service.find_safe_route(
            origin_lat, origin_lng, destination_lat, destination_lng,
            route_type, time_of_day, day_of_week
        )
        
        if not path_data:
            raise Exception("No path found between origin and destination")
            
        # Create DB objects
        
        origin_loc, _ = Location.objects.get_or_create(
            latitude=origin_lat,
            longitude=origin_lng,
            defaults={'location_type': 'origin'}
        )
        
        destination_loc, _ = Location.objects.get_or_create(
            latitude=destination_lat,
            longitude=destination_lng,
            defaults={'location_type': 'destination'}
        )
        
        route = Route.objects.create(
            user=user,
            origin=origin_loc,
            destination=destination_loc,
            total_distance=0.0, 
            estimated_duration=0.0,
            overall_risk_score=avg_risk,
            route_type=route_type
        )
        
        saved_locations = []
        total_dist_calc = 0.0
        
        for i in range(len(path_data)):
            p = path_data[i]
            # Use get_or_create for segments
            loc, _ = Location.objects.get_or_create(
                latitude=p['latitude'],
                longitude=p['longitude'],
                defaults={'location_type': 'waypoint'}
            )
            saved_locations.append(loc)
            
        # Create Segments
        for i in range(len(saved_locations) - 1):
            start_loc = saved_locations[i]
            end_loc = saved_locations[i+1]
            
            d_lat = end_loc.latitude - start_loc.latitude
            d_lng = end_loc.longitude - start_loc.longitude
            dist_km = np.sqrt(d_lat**2 + d_lng**2) * 111.0
            total_dist_calc += dist_km
            
            dur_mins = (dist_km / 30.0) * 60.0 
            
            risk = path_data[i]['risk_score']
            
            RouteSegment.objects.create(
                route=route,
                start_location=start_loc,
                end_location=end_loc,
                sequence_order=i,
                segment_distance=dist_km,
                segment_duration=dur_mins,
                segment_risk_score=risk
            )
            
        route.total_distance = total_dist_calc
        route.estimated_duration = (total_dist_calc / 30.0) * 60.0
        route.save()
        
        computation_time = time.time() - start_time
        
        return {
            'route': route,
            'alternatives': [],
            'computation_time': computation_time,
            'message': 'Route calculation successful'
        }

import time
from typing import Dict, List, Tuple, Optional, Any
from datetime import time as dt_time, datetime
import numpy as np
import pandas as pd
import networkx as nx
import osmnx as ox
import joblib
import os
from django.conf import settings
from django.contrib.auth.models import User

from .models import Location, RiskScore, Route, RouteSegment

# Global cache for heavy resources
_GRAPH = None
_MODEL = None
_EDGES_DF = None # Pre-calculated edge DataFrame for faster prediction

def get_graph():
    global _GRAPH, _EDGES_DF
    if _GRAPH is None:
        place = "Chicago, Illinois, USA"
        print(f"Loading OSM graph for {place}...")
        try:
            # Configure osmnx with a custom User-Agent to avoid blocking
            ox.settings.user_agent = "Protego-AI-Safety-System/1.0 (vaibhav@example.com)"
            
            # Using cache=True to leverage osmnx caching
            # In production, this should load from a local file
            _GRAPH = ox.graph_from_place(place, network_type="drive")
            
            # Pre-calculate edge DataFrame for performance
            edges_data = []
            for u, v, k, data in _GRAPH.edges(keys=True, data=True):
                lat = _GRAPH.nodes[u]['y']
                lon = _GRAPH.nodes[u]['x']
                edges_data.append({
                    'u': u, 'v': v, 'k': k,
                    'Latitude': lat,
                    'Longitude': lon,
                    'crime_enc': 1, # Dummy value
                    'loc_enc': 1,   # Dummy value
                    'Arrest': 0,    # Dummy value
                    'Domestic': 0   # Dummy value
                })
            _EDGES_DF = pd.DataFrame(edges_data)
            print("Graph loaded and edges indexed.")
        except Exception as e:
            print(f"Error loading graph: {e}")
            raise e
    return _GRAPH, _EDGES_DF

def get_model():
    global _MODEL
    if _MODEL is None:
        model_path = os.path.join(settings.BASE_DIR, "ml_engine/training/models/risk_model.pkl")
        print(f"Loading risk model from {model_path}...")
        try:
            _MODEL = joblib.load(model_path)
            print("Model loaded.")
        except Exception as e:
            print(f"Error loading model: {e}")
            raise e
    return _MODEL

class RiskScoringService:
    """
    Service for calculating ML-based location risk scores
    """
    
    def calculate_location_risk(
        self,
        location: Location,
        time_of_day: Optional[dt_time] = None,
        day_of_week: Optional[int] = None
    ) -> float:
        """
        Calculate risk score for a single location using ML model
        """
        model = get_model()
        
        if time_of_day is None:
            now = datetime.now()
            hour = now.hour
        else:
            hour = time_of_day.hour
            
        if day_of_week is None:
            day_of_week = datetime.now().weekday()
            
        # Create input features
        features = pd.DataFrame([{
            'Latitude': location.latitude,
            'Longitude': location.longitude,
            'hour': hour,
            'day': day_of_week,
            'crime_enc': 1,
            'loc_enc': 1,
            'Arrest': 0,
            'Domestic': 0
        }])
        
        try:
            risk = model.predict(features)[0]
            return float(risk)
        except Exception as e:
            print(f"Error calculating point risk: {e}")
            return 0.5  # Fallback

    def recalculate_route_risk(self, route: Route) -> Route:
        """
        Recalculate overall risk score for a route
        """
        segments = route.segments.all()
        if not segments:
            return route
        
        total_distance = sum(seg.segment_distance for seg in segments)
        weighted_risk = sum(
            seg.segment_risk_score * seg.segment_distance
            for seg in segments
        ) / total_distance if total_distance > 0 else 0.0
        
        route.overall_risk_score = weighted_risk
        route.save()
        return route


class DijkstraRoutingService:
    """
    Service implementing modified Dijkstra algorithm for safe route finding
    """
    
    def find_safe_route(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        route_type: str = 'safest',
        time_of_day: Optional[dt_time] = None,
        day_of_week: Optional[int] = None
    ) -> Tuple[List[Dict], float]:
        """
        Find safe route using OSMnx graph and NetworkX
        Returns: Tuple(List of node data dicts, Total Risk Score)
        """
        G, edges_df = get_graph()
        model = get_model()
        
        # 1. Update edge weights based on time
        if time_of_day is None:
            now = datetime.now()
            hour = now.hour
        else:
            hour = time_of_day.hour
            
        if day_of_week is None:
            day_of_week = datetime.now().weekday()
            
        # Fast vectorized prediction
        # Copy df to avoid modifying global cache state permanently if we were thread-safe (basic implementation here)
        # Note: In a real concurrent Django app, we'd need thread-local copies or locking.
        # For prototype, we modify the shared features DF then predict.
        
        features_df = edges_df.copy()
        features_df['hour'] = hour
        features_df['day'] = day_of_week
        
        feature_cols = ['Latitude', 'Longitude', 'hour', 'day', 'crime_enc', 'loc_enc', 'Arrest', 'Domestic']
        
        try:
            risk_scores = model.predict(features_df[feature_cols])
        except Exception as e:
            print(f"Prediction error: {e}")
            raise e
            
        # Update graph weights
        # We need to map risk scores back to edges.
        # edges_df has 'u', 'v', 'k' which match G edges
        
        # Create a dictionary for fast lookup or direct assignment
        # Using a distinct weight name to avoid overwriting 'length'
        weight_name = 'risk_weight'
        
        # Iterate and update
        # This loop is still Python-heavy but faster than individual predictions
        for idx, risk in enumerate(risk_scores):
            u = edges_df.iloc[idx]['u']
            v = edges_df.iloc[idx]['v']
            k = edges_df.iloc[idx]['k']
            # risk is 0-1 (approx).
            # risk_weight: higher risk -> higher cost.
            # length: physical distance.
            
            # Combined weight formula
            length = G[u][v][k].get('length', 10.0) # Default 10m if missing
            
            if route_type == 'safest':
                # Heavily penalize risk.
                # Cost = length * (1 + risk * 10)
                # If risk is 0.1, cost = length * 2. If risk is 0.9, cost = length * 10.
                cost = length * (1.0 + float(risk) * 20.0)
            elif route_type == 'fastest':
                # Pure length, ignore risk (or minimal risk)
                cost = length
            else:
                 # Balanced
                cost = length * (1.0 + float(risk) * 5.0)
                
            G[u][v][k][weight_name] = cost
            G[u][v][k]['risk_score'] = float(risk) # Store raw risk for later
            
        # 2. Find nearest nodes
        orig_node = ox.nearest_nodes(G, origin_lng, origin_lat)
        dest_node = ox.nearest_nodes(G, dest_lng, dest_lat)
        
        # 3. Shortest path
        try:
            route_nodes = nx.shortest_path(G, orig_node, dest_node, weight=weight_name)
        except nx.NetworkXNoPath:
            return [], 0.0
            
        # 4. Extract path data
        path_data = []
        total_risk = 0.0
        count = 0
        
        for i, node_id in enumerate(route_nodes):
            node_obj = G.nodes[node_id]
            lat = node_obj['y']
            lng = node_obj['x']
            
            step_risk = 0.0
            # If not last node, get edge data to next node
            if i < len(route_nodes) - 1:
                next_node = route_nodes[i+1]
                # accessing edge data
                # MultiDiGraph, so there might be multiple edges (keys). Use key 0 or min weight.
                edge_data = G.get_edge_data(node_id, next_node)
                if edge_data:
                    # simplistic: take first key
                    first_key = list(edge_data.keys())[0]
                    step_risk = edge_data[first_key].get('risk_score', 0.0)
            
            path_data.append({
                'latitude': lat,
                'longitude': lng,
                'risk_score': step_risk
            })
            total_risk += step_risk
            count += 1
            
        avg_risk = total_risk / count if count > 0 else 0.0
        
        return path_data, avg_risk


class RoutePredictionService:
    """
    Main service for route prediction
    """
    
    def __init__(self):
        self.risk_service = RiskScoringService()
        self.routing_service = DijkstraRoutingService()
    
    def predict_safe_route(
        self,
        origin_lat: float,
        origin_lng: float,
        destination_lat: float,
        destination_lng: float,
        route_type: str,
        user: User,
        time_of_day: Optional[dt_time] = None,
        day_of_week: Optional[int] = None
    ) -> Dict:
        """
        Orchestrate safe route prediction
        """
        start_time = time.time()
        
        # Find safe route using real OSM/NetworkX logic
        path_data, avg_risk = self.routing_service.find_safe_route(
            origin_lat, origin_lng, destination_lat, destination_lng,
            route_type, time_of_day, day_of_week
        )
        
        if not path_data:
            raise Exception("No path found between origin and destination")
            
        # Create DB objects
        
        # 1. Locations
        # Optimization: Don't save every intermediate node as a generic 'Location' 
        # unless necessary, or bulk create. 
        # For now, we will save origin/dest and just store segments.
        # Given existing schema, we probably need Locations for segments.
        
        origin_loc, _ = Location.objects.get_or_create(
            latitude=origin_lat,
            longitude=origin_lng,
            defaults={'location_type': 'origin'}
        )
        
        destination_loc, _ = Location.objects.get_or_create(
            latitude=destination_lat,
            longitude=destination_lng,
            defaults={'location_type': 'destination'}
        )
        
        # Calculate totals
        total_distance = 0.0 # Calculate from path_data if needed
        # We can sum distance from path_data if we stored it
        # For prototype, approximate
        
        estimated_duration = 0.0 # update later
        
        route = Route.objects.create(
            user=user,
            origin=origin_loc,
            destination=destination_loc,
            total_distance=0.0, # Placeholder, updated below
            estimated_duration=0.0,
            overall_risk_score=avg_risk,
            route_type=route_type
        )
        
        # Create segments and locations for the path
        # Bulk create locations?
        # Iterate path
        
        saved_locations = []
        # Reuse origin loc for first point? path_data[0] is nearest node, not exact request origin.
        # But close enough for routing display.
        
        total_dist_calc = 0.0
        
        for i in range(len(path_data)):
            p = path_data[i]
            # Check if loc exists (expensive loop!)
            # For speed, let's create new ones or check cache.
            # Use get_or_create is safe but slow for 100 nodes.
            # Implementation detail: Only store key waypoints or just store segments?
            # Assuming we need them for the frontend to draw path.
            
            # Optimization: Just use a serializer that sends the coordinates without DB ids for segments?
            # But RouteResponseSerializer likely expects Route object with Segments.
            
            loc, _ = Location.objects.get_or_create(
                latitude=p['latitude'],
                longitude=p['longitude'],
                defaults={'location_type': 'waypoint'}
            )
            saved_locations.append(loc)
            
        # Create Segments
        # OPTIMIZATION: Instead of creating hundreds of RouteSegment rows, 
        # we store the path data directly in the JSON field.
        
        saved_path_data = []
        total_dist_calc = 0.0
        
        for i in range(len(path_data)):
            p = path_data[i]
            
            # Add to path data list
            saved_path_data.append({
                'latitude': p['latitude'],
                'longitude': p['longitude'],
                'risk_score': p.get('risk_score', 0.0)
            })
            
            # Calculate distance to next point for total distance
            if i < len(path_data) - 1:
                next_p = path_data[i+1]
                d_lat = next_p['latitude'] - p['latitude']
                d_lng = next_p['longitude'] - p['longitude']
                # Approx distance in km
                dist_km = np.sqrt(d_lat**2 + d_lng**2) * 111.0
                total_dist_calc += dist_km

        route.path_data = saved_path_data
        route.total_distance = total_dist_calc
        route.estimated_duration = (total_dist_calc / 30.0) * 60.0 # 30km/h avg
        route.save()
        
        computation_time = time.time() - start_time
        
        return {
            'route': route,
            'alternatives': [],
            'computation_time': computation_time,
            'message': 'Route calculation successful'
        }
