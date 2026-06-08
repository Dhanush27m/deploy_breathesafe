/**
 * RouteMap — Leaflet map for the Route Planner
 *
 * V2: Shows ALL routes simultaneously as colored polylines.
 * The selected route is highlighted (thicker + full opacity);
 * others are drawn dimmed for visual comparison.
 *
 * Props:
 *   routes        : array of route objects (each has route_type, waypoints, distance_km, time_min, avg_aqi_exposure)
 *   selectedType  : "fastest" | "clean" | "balanced" — which route is highlighted
 *   sourceLat/Lon : coordinates for the origin marker
 *   destLat/Lon   : coordinates for the destination marker
 *   sourceName    : label for origin marker
 *   destName      : label for destination marker
 */

import { useEffect, useRef } from 'react'
import 'leaflet/dist/leaflet.css'

// Per-type polyline style — selected (highlighted) vs dimmed
const ROUTE_STYLE = {
  fastest:  { color: '#38bdf8', selectedWeight: 6, dimWeight: 3, selectedOpacity: 1.0, dimOpacity: 0.35 },
  clean:    { color: '#4ade80', selectedWeight: 6, dimWeight: 3, selectedOpacity: 1.0, dimOpacity: 0.35 },
  balanced: { color: '#c084fc', selectedWeight: 6, dimWeight: 3, selectedOpacity: 1.0, dimOpacity: 0.35 },
}

function fixLeafletIcons(L) {
  delete L.Icon.Default.prototype._getIconUrl
  L.Icon.Default.mergeOptions({
    iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
    iconUrl:       'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
    shadowUrl:     'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
  })
}

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
  const containerRef  = useRef(null)
  const mapRef        = useRef(null)
  const polylinesRef  = useRef({})    // { route_type: polyline }
  const markersRef    = useRef([])
  const [mapReady, _setMapReady] = [useRef(false), (v) => { mapReady.current = v }]
  const mapReadyRef   = useRef(false)
  const setMapReady   = (v) => { mapReadyRef.current = v }

  // ── Initialise map once ────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    import('leaflet').then(({ default: L }) => {
      if (!containerRef.current || mapRef.current) return
      fixLeafletIcons(L)

      const map = L.map(containerRef.current, {
        zoomControl:        true,
        attributionControl: true,
        scrollWheelZoom:    true,
      })

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
      }).addTo(map)

      mapRef.current = map
      setMapReady(true)
    })

    return () => {
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current    = null
        polylinesRef.current = {}
        markersRef.current   = []
        setMapReady(false)
      }
    }
  }, [])

  // ── Redraw all polylines + markers when routes or selectedType changes ─────
  useEffect(() => {
    if (!mapRef.current || !routes.length) return

    import('leaflet').then(({ default: L }) => {
      const map = mapRef.current
      if (!map) return

      // Remove old polylines
      Object.values(polylinesRef.current).forEach(pl => map.removeLayer(pl))
      polylinesRef.current = {}

      // Remove old markers
      markersRef.current.forEach(m => map.removeLayer(m))
      markersRef.current = []

      let allBoundsPoints = []

      // ── Draw ALL routes, dimmed first, selected last (on top) ─────────────
      const sortedRoutes = [
        ...routes.filter(r => r.route_type !== selectedType),
        ...routes.filter(r => r.route_type === selectedType),
      ]

      sortedRoutes.forEach(route => {
        if (!route?.waypoints?.length) return

        const style   = ROUTE_STYLE[route.route_type] || ROUTE_STYLE.fastest
        const isSelected = route.route_type === selectedType

        const polyline = L.polyline(route.waypoints, {
          color:   style.color,
          weight:  isSelected ? style.selectedWeight : style.dimWeight,
          opacity: isSelected ? style.selectedOpacity : style.dimOpacity,
        }).addTo(map)

        // Tooltip on hover (all routes)
        polyline.bindTooltip(
          `<b style="color:${style.color}">${route.route_type.charAt(0).toUpperCase() + route.route_type.slice(1)}</b>` +
          ` — ${route.distance_km?.toFixed(1)} km · ${route.time_min?.toFixed(0)} min` +
          ` · AQI ${Math.round(route.avg_aqi_exposure ?? 0)}`,
          { sticky: true, opacity: 0.9 }
        )

        polylinesRef.current[route.route_type] = polyline

        if (isSelected) {
          allBoundsPoints = route.waypoints
        } else if (!allBoundsPoints.length) {
          allBoundsPoints = route.waypoints
        }
      })

      // ── Source / destination markers ──────────────────────────────────────
      if (sourceLat != null && sourceLon != null) {
        const srcMarker = L.marker([sourceLat, sourceLon], {
          icon: makeCircleIcon(L, '#0ea5e9', 'A'),
          zIndexOffset: 1000,
        })
          .addTo(map)
          .bindPopup(`<b>${sourceName}</b><br/>Origin`)
        markersRef.current.push(srcMarker)
      }

      if (destLat != null && destLon != null) {
        const dstMarker = L.marker([destLat, destLon], {
          icon: makeCircleIcon(L, '#22c55e', 'B'),
          zIndexOffset: 1000,
        })
          .addTo(map)
          .bindPopup(`<b>${destName}</b><br/>Destination`)
        markersRef.current.push(dstMarker)
      }

      // ── Fit map to the selected (or first available) route bounds ─────────
      if (allBoundsPoints.length) {
        const bounds = L.latLngBounds(allBoundsPoints)
        if (bounds.isValid()) {
          map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 })
        }
      }
    })
  }, [routes, selectedType, sourceLat, sourceLon, destLat, destLon, sourceName, destName])

  return (
    <div style={{ position: 'relative', zIndex: 0 }}>
      <div
        ref={containerRef}
        style={{ height: '380px', width: '100%', borderRadius: '12px', overflow: 'hidden' }}
      />
    </div>
  )
}
