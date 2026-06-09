/**
 * RouteMap — Leaflet map for the Route Planner
 *
 * Props:
 *   routes        : array of route objects (each has route_type, waypoints, distance_km, time_min, avg_aqi_exposure)
 *   selectedType  : "fastest" | "clean" | "balanced"
 *   sourceLat/Lon : coordinates for the origin marker
 *   destLat/Lon   : coordinates for the destination marker
 *   sourceName    : label for origin marker
 *   destName      : label for destination marker
 */

import { useEffect, useRef } from 'react'
import 'leaflet/dist/leaflet.css'

// Leaflet colours per route type
const ROUTE_STYLE = {
  fastest:  { color: '#38bdf8', weight: 5, opacity: 0.95 },   // sky-400
  clean:    { color: '#4ade80', weight: 5, opacity: 0.95 },   // green-400
  balanced: { color: '#c084fc', weight: 5, opacity: 0.95 },   // purple-400
}

// Fix Leaflet default marker icon paths broken by bundlers
function fixLeafletIcons(L) {
  delete L.Icon.Default.prototype._getIconUrl
  L.Icon.Default.mergeOptions({
    iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
    iconUrl:       'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
    shadowUrl:     'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
  })
}

// Coloured circle div-icon for source / destination
function makeCircleIcon(L, colour, label) {
  return L.divIcon({
    className: '',
    html: `
      <div style="
        width:34px;height:34px;border-radius:50%;
        background:${colour};border:3px solid #fff;
        box-shadow:0 2px 8px rgba(0,0,0,0.5);
        display:flex;align-items:center;justify-content:center;
        font-size:11px;font-weight:700;color:#fff;
        font-family:-apple-system,sans-serif;
        white-space:nowrap;
      ">${label}</div>`,
    iconSize:   [34, 34],
    iconAnchor: [17, 17],
    popupAnchor:[0, -18],
  })
}

export default function RouteMap({
  routes       = [],
  selectedType = 'clean',
  sourceLat, sourceLon, sourceName = 'Start',
  destLat,   destLon,   destName   = 'End',
}) {
  const containerRef = useRef(null)
  const mapRef       = useRef(null)
  const polylineRef  = useRef(null)
  const markersRef   = useRef([])

  // ── Initialise map once ────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    import('leaflet').then(({ default: L }) => {
      fixLeafletIcons(L)

      const map = L.map(containerRef.current, {
        zoomControl:       true,
        attributionControl: true,
        scrollWheelZoom:   true,
      })

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
      }).addTo(map)

      mapRef.current = map
    })

    return () => {
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current  = null
        polylineRef.current = null
        markersRef.current  = []
      }
    }
  }, [])

  // ── Update polyline + markers when selected route changes ─────────────────
  useEffect(() => {
    if (!mapRef.current || !routes.length) return

    import('leaflet').then(({ default: L }) => {
      const map = mapRef.current

      // Remove old polyline
      if (polylineRef.current) {
        map.removeLayer(polylineRef.current)
        polylineRef.current = null
      }
      // Remove old markers
      markersRef.current.forEach(m => map.removeLayer(m))
      markersRef.current = []

      // Find the selected route
      const route = routes.find(r => r.route_type === selectedType) || routes[0]
      if (!route?.waypoints?.length) return

      const style = ROUTE_STYLE[route.route_type] || ROUTE_STYLE.fastest

      // Draw polyline
      const polyline = L.polyline(route.waypoints, style).addTo(map)
      polylineRef.current = polyline

      // Source marker (sky blue)
      if (sourceLat != null && sourceLon != null) {
        const srcMarker = L.marker([sourceLat, sourceLon], {
          icon: makeCircleIcon(L, '#0ea5e9', 'A'),
        })
          .addTo(map)
          .bindPopup(`<b>${sourceName}</b><br/>Origin`)
        markersRef.current.push(srcMarker)
      }

      // Destination marker (green)
      if (destLat != null && destLon != null) {
        const dstMarker = L.marker([destLat, destLon], {
          icon: makeCircleIcon(L, '#22c55e', 'B'),
        })
          .addTo(map)
          .bindPopup(`<b>${destName}</b><br/>Destination`)
        markersRef.current.push(dstMarker)
      }

      // Fit map to route bounds with padding
      const bounds = polyline.getBounds()
      if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 })
      }
    })
  }, [routes, selectedType, sourceLat, sourceLon, destLat, destLon, sourceName, destName])

  // Stacking context wrapper: keeps Leaflet's internal z-indices (200–600)
  // below the sticky navbar (z-50). Without this, Leaflet pane z-indices win
  // against the global stacking context and tiles overflow the nav on scroll.
  return (
    <div style={{ position: 'relative', zIndex: 0 }}>
      <div
        ref={containerRef}
        style={{ height: '380px', width: '100%', borderRadius: '12px', overflow: 'hidden' }}
      />
    </div>
  )
}
