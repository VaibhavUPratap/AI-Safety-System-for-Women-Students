import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Alert, PermissionsAndroid, Platform, StyleSheet, Text, View, StatusBar, Animated, TouchableOpacity, TextInput } from 'react-native';
import { WebView } from 'react-native-webview';
import Geolocation, { GeoPosition } from 'react-native-geolocation-service';
import { accelerometer, setUpdateIntervalForType, SensorTypes } from 'react-native-sensors';
import AudioRecord from 'react-native-audio-record';
import { SafetyService } from '../api/SafetyService';
import { AudioUtils } from '../utils/AudioUtils';
import { fetchRiskScores, predictSafeRoute, geocodePlaceName, RoutePredictionResponse } from '../api/routing';
import { PrimaryButton } from '../components/PrimaryButton';
import { SectionCard } from '../components/SectionCard';
import { colors, spacing, typography, shadows } from '../theme-soft';

const initialRegion = {
  latitude: 12.9716,
  longitude: 77.5946,
};

export function MapScreen() {
  const [sending, setSending] = useState(false);
  const [status, setStatus] = useState('You are safe');
  const [locationStatus, setLocationStatus] = useState('Updating location...');
  const [riskSummary, setRiskSummary] = useState<string | null>(null);
  const [destinationQuery, setDestinationQuery] = useState('');
  const [routeSummary, setRouteSummary] = useState<string | null>(null);
  const [routeLoading, setRouteLoading] = useState(false);
  const [currentLocation, setCurrentLocation] = useState<{ latitude: number; longitude: number } | null>(null);
  const webViewRef = useRef<WebView>(null);

  // Initialize Audio
  useEffect(() => {
    const initAudio = async () => {
      const options = {
        sampleRate: 16000,
        channels: 1,
        bitsPerSample: 16,
        audioSource: 6,
        wavFile: 'test.wav'
      };
      AudioRecord.init(options);
    };
    initAudio();
  }, []);

  const handleFindSafeRoute = async () => {
    if (!currentLocation) {
      Alert.alert('Location unavailable', 'Waiting for your GPS location. Please try again in a moment.');
      return;
    }

    const query = destinationQuery.trim();
    if (!query) {
      Alert.alert('Destination required', 'Please enter a place name or address.');
      return;
    }

    try {
      setRouteLoading(true);
      setStatus('Finding safest route...');

      // 1. Geocode the destination text into coordinates
      const geo = await geocodePlaceName(query);

      // 2. Build route request using current time/day
      const now = new Date();
      const hours = String(now.getHours()).padStart(2, '0');
      const minutes = String(now.getMinutes()).padStart(2, '0');

      // Convert JS day (0=Sunday) to backend convention (0=Monday)
      const jsDay = now.getDay(); // 0-6, Sunday=0
      const dayOfWeek = (jsDay + 6) % 7; // 0-6, Monday=0

      const response = await predictSafeRoute({
        origin_lat: currentLocation.latitude,
        origin_lng: currentLocation.longitude,
        destination_lat: geo.latitude,
        destination_lng: geo.longitude,
        route_type: 'safest',
        time_of_day: `${hours}:${minutes}:00`,
        day_of_week: dayOfWeek,
      });

      const { route } = response;

      // 3. Prepare a simple polyline from origin + segment end locations
      // 3. Prepare polyline points
      const points: { latitude: number; longitude: number }[] = [];

      if (route.path_data && route.path_data.length > 0) {
        // FAST PATH: Use pre-computed path data
        route.path_data.forEach(p => {
          points.push({ latitude: p.latitude, longitude: p.longitude });
        });
      } else {
        // FALLBACK: Legacy segment logic
        if (route.origin) {
          points.push({
            latitude: route.origin.latitude,
            longitude: route.origin.longitude,
          });
        }
        if (Array.isArray(route.segments)) {
          route.segments.forEach((segment) => {
            if (segment.end_location) {
              points.push({
                latitude: segment.end_location.latitude,
                longitude: segment.end_location.longitude,
              });
            }
          });
        }
      }

      if (points.length) {
        webViewRef.current?.postMessage(
          JSON.stringify({
            type: 'route',
            points,
          }),
        );
      }

      // 4. Update UI summary
      const distanceKm = route.total_distance ?? 0;
      const durationMins = route.estimated_duration ?? 0;
      const risk = route.overall_risk_score ?? 0;

      setRouteSummary(
        `Safest route: ${distanceKm.toFixed(1)} km · ${durationMins.toFixed(
          0,
        )} mins · Risk score ${risk.toFixed(2)}`,
      );
      setStatus('Safest route ready');
    } catch (error: any) {
      console.error('Safe route error', error);
      Alert.alert('Route Error', error.message || 'Could not compute a safe route. Please try again.');
      setStatus('You are safe');
    } finally {
      setRouteLoading(false);
    }
  };

  // Motion Monitoring Logic moved to BackgroundSafetyService
  // useEffect(() => { ... }, [sending]);

  // handleMotionCheck moved to BackgroundSafetyService

  const startAudioAnalysis = async () => {
    try {
      if (Platform.OS === 'android') {
        const granted = await PermissionsAndroid.request(
          PermissionsAndroid.PERMISSIONS.RECORD_AUDIO
        );
        if (granted !== PermissionsAndroid.RESULTS.GRANTED) return;
      }

      const options = {
        sampleRate: 16000,
        channels: 1,
        bitsPerSample: 16,
        audioSource: 6,
        wavFile: 'test.wav'
      };
      AudioRecord.init(options);
      AudioRecord.start();
      await new Promise(resolve => setTimeout(() => resolve(true), 3000));
      const audioFile = await AudioRecord.stop();
      const mfcc = await AudioUtils.extractMFCC(audioFile);

      const location = currentLocation || { latitude: 0, longitude: 0 };
      const response = await SafetyService.analyzeAudio({
        audio_mfcc: mfcc,
        location: { lat: location.latitude, lon: location.longitude }
      });

      if (response.emergency_triggered) {
        Alert.alert("Emergency Triggered", "Help is on the way. Your location and audio have been sent.");
        setStatus("Emergency Alert Active");
      } else {
        setStatus("Environment looks safe");
        setTimeout(() => setStatus('You are safe'), 3000);
      }

    } catch (err) {
      console.log("Audio analysis failed", err);
    }
  };

  useEffect(() => {
    let isMounted = true;
    fetchRiskScores()
      .then((scores) => {
        if (!isMounted) return;
        if (!scores.length) {
          setRiskSummary('Safety score: Unknown');
          return;
        }
        const avgRisk = scores.reduce((sum, item) => sum + item.risk_level, 0) / scores.length;
        setRiskSummary(`Safety Score: ${(10 - avgRisk).toFixed(1)}/10`);
      })
      .catch((error) => {
        if (isMounted) {
          setRiskSummary(`Offline Mode`);
          Alert.alert("Connection Error", `Could not fetch safety scores. \n${error.message}`);
        }
      });
    return () => { isMounted = false; };
  }, []);

  useEffect(() => {
    let watchId: number | null = null;
    let isActive = true;

    const updateLocation = (position: GeoPosition) => {
      if (!isActive) return;
      const { latitude, longitude } = position.coords;
      setCurrentLocation({ latitude, longitude });
      setLocationStatus(`You are at: ${latitude.toFixed(4)}, ${longitude.toFixed(4)}`);
      webViewRef.current?.postMessage(
        JSON.stringify({ type: 'location', latitude, longitude })
      );
    };

    const startWatching = async () => {
      const hasPermission = await requestLocationPermission();
      if (!hasPermission) {
        setLocationStatus('Location permission unavailable');
        return;
      }
      watchId = Geolocation.watchPosition(
        updateLocation,
        (error) => setLocationStatus(`GPS Error: ${error.message}`),
        { enableHighAccuracy: true, distanceFilter: 5, interval: 2000, fastestInterval: 1000 }
      );
    };

    startWatching();
    return () => {
      isActive = false;
      if (watchId !== null) Geolocation.clearWatch(watchId);
    };
  }, []);

  // handleEmergency moved to SosScreen

  const mapHtml = `<!doctype html>
    <html>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <style>
          html, body, #map { height: 100%; margin: 0; padding: 0; background: #FAFAFA; }
          .leaflet-control-attribution { display: none; }
        </style>
      </head>
      <body>
        <div id="map"></div>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <script>
          const map = L.map('map', { zoomControl: false, attributionControl: false }).setView([${initialRegion.latitude}, ${initialRegion.longitude}], 13);
          L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', { maxZoom: 19 }).addTo(map);
          
          const icon = L.divIcon({
            className: 'custom-pin',
            html: '<div style="background-color: #4ECDC4; width: 16px; height: 16px; border: 3px solid white; border-radius: 50%; box-shadow: 0 4px 10px rgba(0,0,0,0.2);"></div>',
            iconSize: [20, 20],
            iconAnchor: [10, 10]
          });
          
          const liveMarker = L.marker([${initialRegion.latitude}, ${initialRegion.longitude}], {icon: icon}).addTo(map);
          let hasCentered = false;
          let routeLayer = null;

          const updateLocation = (lat, lng) => {
            liveMarker.setLatLng([lat, lng]);
            if (!hasCentered) {
              map.setView([lat, lng], 15);
              hasCentered = true;
            } else {
              map.panTo([lat, lng]);
            }
          };

          const drawRoute = (points) => {
            if (!Array.isArray(points) || points.length === 0) return;
            const latlngs = points.map(p => [p.latitude || p.lat, p.longitude || p.lng]);
            if (routeLayer) {
              map.removeLayer(routeLayer);
            }
            routeLayer = L.polyline(latlngs, {
              color: '#FF6B6B',
              weight: 5,
              opacity: 0.9
            }).addTo(map);
            map.fitBounds(routeLayer.getBounds(), { padding: [40, 40] });
          };

          const handleMessage = (event) => {
            try {
              const data = JSON.parse(event.data);
              if (data?.type === 'location') {
                updateLocation(data.latitude, data.longitude);
              } else if (data?.type === 'route') {
                drawRoute(data.points || data.coordinates || data.route);
              }
            } catch (err) {}
          };

          document.addEventListener('message', handleMessage);
          window.addEventListener('message', handleMessage);
        </script>
      </body>
    </html>`;

  return (
    <View style={styles.container}>
      <StatusBar barStyle="dark-content" backgroundColor={colors.background} />

      {/* Map Header */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Home</Text>
        <View style={styles.statusPill}>
          <View style={[styles.statusDot, status.includes('Alert') ? styles.dotRed : styles.dotGreen]} />
          <Text style={styles.statusText}>{status}</Text>
        </View>
      </View>

      <View style={styles.mapContainer}>
        <WebView
          ref={webViewRef}
          originWhitelist={['*']}
          source={{ html: mapHtml }}
          style={styles.map}
          javaScriptEnabled={true}
          domStorageEnabled={true}
          onError={(syntheticEvent) => {
            const { nativeEvent } = syntheticEvent;
            console.warn('WebView error: ', nativeEvent);
            Alert.alert('Map Error', 'Failed to load map resources. Please check your internet connection.');
          }}
          onHttpError={(syntheticEvent) => {
            const { nativeEvent } = syntheticEvent;
            console.warn('WebView HTTP error: ', nativeEvent);
          }}
        />
      </View>

      {/* Bottom Panel */}
      <View style={styles.bottomSheet}>
        <View style={styles.handle} />
        <SectionCard title="Your Safety Status" subtitle={locationStatus} style={styles.card}>
          <Text style={styles.riskText}>{riskSummary || 'Checking safety score...'}</Text>
        </SectionCard>

        <SectionCard
          title="Safe Navigation"
          subtitle="Enter a destination to see the safest route"
          style={styles.card}
        >
          <TextInput
            style={styles.destinationInput}
            placeholder="Enter place name or address"
            placeholderTextColor={colors.textSecondary}
            value={destinationQuery}
            onChangeText={setDestinationQuery}
          />
          <PrimaryButton
            label={routeLoading ? 'Finding Route...' : 'Find Safest Route'}
            onPress={handleFindSafeRoute}
            disabled={routeLoading || !destinationQuery.trim()}
            style={styles.routeButton}
          />
          {routeSummary ? (
            <Text style={styles.routeSummary}>{routeSummary}</Text>
          ) : null}
        </SectionCard>

      </View>
    </View>
  );
}

async function requestLocationPermission() {
  if (Platform.OS === 'ios') return true;
  const granted = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION);
  return granted === PermissionsAndroid.RESULTS.GRANTED;
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    paddingHorizontal: spacing.lg,
    paddingTop: Platform.OS === 'ios' ? 60 : 40,
    paddingBottom: spacing.md,
    backgroundColor: colors.background,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  headerTitle: {
    ...typography.header,
  },
  statusPill: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F0F0F0',
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 20,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 6,
  },
  dotGreen: { backgroundColor: colors.success },
  dotRed: { backgroundColor: colors.primary },
  statusText: {
    ...typography.caption,
    color: colors.textSecondary,
    fontWeight: '600',
  },
  mapContainer: {
    flex: 1,
    marginHorizontal: spacing.md,
    borderRadius: 24,
    overflow: 'hidden',
    ...shadows.soft,
  },
  map: {
    flex: 1,
    backgroundColor: '#FAFAFA',
  },
  bottomSheet: {
    padding: spacing.lg,
    paddingBottom: spacing.xl,
    backgroundColor: colors.background,
    borderTopLeftRadius: 30,
    borderTopRightRadius: 30,
  },
  handle: {
    width: 40,
    height: 4,
    backgroundColor: '#E0E0E0',
    borderRadius: 2,
    alignSelf: 'center',
    marginBottom: spacing.lg,
  },
  card: {
    marginBottom: spacing.lg,
  },
  riskText: {
    ...typography.title,
    color: colors.secondary,
  },
  sosButton: {
    backgroundColor: colors.primary,
    ...shadows.medium,
  },
  destinationInput: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.md,
    paddingVertical: Platform.OS === 'ios' ? 10 : 8,
    backgroundColor: colors.surface,
    ...typography.body,
    color: colors.text,
    marginBottom: spacing.sm,
  },
  routeButton: {
    marginTop: spacing.xs,
    backgroundColor: colors.secondary,
    ...shadows.medium,
  },
  routeSummary: {
    marginTop: spacing.sm,
    ...typography.caption,
  },
});
