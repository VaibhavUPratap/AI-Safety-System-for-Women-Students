
import { request } from './client';

export interface Location {
  id?: number;
  latitude: number;
  longitude: number;
  name?: string;
  address?: string;
}

export interface RiskScore {
  id: number;
  location: number;
  risk_level: number;
  time_of_day?: string;
  day_of_week?: number;
  crime_rate?: number;
  lighting_score?: number;
  crowd_density?: number;
  incident_history?: number;
  calculated_at?: string;
}

export interface RouteSegment {
  id: number;
  start_location: Location;
  end_location: Location;
  sequence_order: number;
  segment_distance: number;
  segment_duration: number;
  segment_risk_score: number;
}

export interface Route {
  id: number;
  origin: Location;
  destination: Location;
  waypoints: Location[];
  segments: RouteSegment[];
  path_data?: { latitude: number; longitude: number; risk_score: number }[];
  total_distance: number;
  estimated_duration: number;
  overall_risk_score: number;
  route_type: 'safest' | 'fastest' | 'balanced';
}

export interface RoutePredictionResponse {
  route: Route;
  alternatives: Route[];
  computation_time: number;
  message: string;
}

export interface RouteRequest {
  origin_lat: number;
  origin_lng: number;
  destination_lat: number;
  destination_lng: number;
  route_type: 'safest' | 'fastest' | 'balanced';
  time_of_day?: string; // HH:MM
  day_of_week?: number; // 0-6
}

export const predictSafeRoute = async (data: RouteRequest): Promise<RoutePredictionResponse> => {
  return request<RoutePredictionResponse>('/api/routing/routes/predict_safe_route/', {
    method: 'POST',
    body: data,
  });
};

export const getRouteHistory = async (): Promise<Route[]> => {
  return request<Route[]>('/api/routing/routes/user_history/');
};

export const fetchRiskScores = async (): Promise<RiskScore[]> => {
  return request<RiskScore[]>('/api/routing/risk-scores/');
};

export interface GeocodedLocation {
  latitude: number;
  longitude: number;
  displayName: string;
}

interface NominatimResult {
  lat: string;
  lon: string;
  display_name: string;
}

/**
 * Simple geocoding helper using OpenStreetMap Nominatim.
 * Converts a free‑text place name into latitude/longitude.
 */
export async function geocodePlaceName(query: string): Promise<GeocodedLocation> {
  const trimmed = query.trim();
  if (!trimmed) {
    throw new Error('Destination cannot be empty.');
  }

  const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(
    trimmed,
  )}&limit=1`;

  const response = await fetch(url, {
    headers: {
      Accept: 'application/json',
      // Nominatim requires a descriptive User-Agent
      'User-Agent': 'Protego-AI-Safety-System/1.0 (vaibhav@example.com)', // Replace with real email if possible, or generic project contact
      'Referer': 'https://github.com/Deepika2222/AI-Safety-System-for-Women-Students',
    },
  });

  if (!response.ok) {
    throw new Error(`Geocoding failed with status ${response.status}`);
  }

  const data: NominatimResult[] = await response.json();

  if (!data.length) {
    throw new Error('No results found for that place.');
  }

  const { lat, lon, display_name } = data[0];

  return {
    latitude: parseFloat(lat),
    longitude: parseFloat(lon),
    displayName: display_name,
  };
}
