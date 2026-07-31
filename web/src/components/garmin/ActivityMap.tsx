import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { TrackpointRow } from "../../api/types";

/**
 * Activity map — renders the GPS route of a Garmin activity on a
 * Leaflet map with CARTO Voyager (light) / Dark Matter (dark) tiles.
 *
 * No external tile API dependency — CARTO's public raster tiles are
 * free for non-commercial use with attribution. The project's geo-api
 * (maps.ogsapps.cc) can be layered on later for elevation profiles
 * via `/api/elevation/profile`, but the base route rendering works
 * standalone today.
 *
 * Uses vanilla Leaflet (no react-leaflet wrapper) to keep the
 * dependency surface small. The map lifecycle is managed in a
 * useEffect that cleans up on unmount or when the route changes.
 */

// CARTO free basemaps — no API key required, just attribution.
// https://carto.com/basemaps/
const LIGHT_TILES =
  "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png";
const DARK_TILES =
  "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png";
const ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>';

interface ActivityMapProps {
  trackpoints: TrackpointRow[];
}

export function ActivityMap({ trackpoints }: ActivityMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // Filter to trackpoints that have GPS coordinates (some may be
    // null at the start/end of an activity due to GPS dropout).
    const points: [number, number][] = trackpoints
      .filter((tp) => tp.lat != null && tp.lon != null)
      .map((tp) => [tp.lat!, tp.lon!]);

    if (points.length < 2) {
      // Not enough GPS data to draw a route — destroy any existing map.
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
      return;
    }

    const isDark = document.documentElement.classList.contains("dark");

    // Create the map if it doesn't exist yet.
    if (!mapRef.current) {
      mapRef.current = L.map(containerRef.current, {
        zoomControl: true,
        scrollWheelZoom: false, // don't hijack page scroll
        attributionControl: true,
      });
    }

    const map = mapRef.current;

    // Clear existing layers (tile + polyline + markers) on re-render.
    map.eachLayer((layer) => map.removeLayer(layer));

    // Tile layer — CARTO Voyager (light) or Dark Matter (dark).
    L.tileLayer(isDark ? DARK_TILES : LIGHT_TILES, {
      attribution: ATTRIBUTION,
      maxZoom: 19,
      subdomains: "abcd",
    }).addTo(map);

    // Route polyline.
    const polyline = L.polyline(points, {
      color: "#3b82f6",
      weight: 4,
      opacity: 0.8,
    }).addTo(map);

    // Start (green) and end (red) markers.
    const start = points[0];
    const end = points[points.length - 1];
    L.circleMarker(start, {
      radius: 6,
      fillColor: "#22c55e",
      color: "#fff",
      weight: 2,
      fillOpacity: 1,
    })
      .addTo(map)
      .bindTooltip("Start");
    L.circleMarker(end, {
      radius: 6,
      fillColor: "#ef4444",
      color: "#fff",
      weight: 2,
      fillOpacity: 1,
    })
      .addTo(map)
      .bindTooltip("Finish");

    // Fit bounds to the route with padding.
    map.fitBounds(polyline.getBounds(), { padding: [20, 20] });

    // Ensure the map renders correctly after the container becomes
    // visible (Leaflet needs invalidateSize when the div was hidden).
    setTimeout(() => map.invalidateSize(), 100);
  }, [trackpoints]);

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
  }, []);

  // Check if there's enough GPS data to render.
  const gpsPoints = trackpoints.filter((tp) => tp.lat != null && tp.lon != null);
  if (gpsPoints.length < 2) {
    return (
      <p className="text-sm text-gray-500 dark:text-gray-400 italic py-8 text-center">
        No GPS data for this activity (indoor or GPS signal lost)
      </p>
    );
  }

  return (
    <div
      ref={containerRef}
      className="w-full rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700"
      style={{ height: 320, zIndex: 0 }}
    />
  );
}
