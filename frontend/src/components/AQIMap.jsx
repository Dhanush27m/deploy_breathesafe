/**
 * AQIMap — Interactive India map with AQI pin markers
 *
 * Props:
 *   cities  : array of { city, state, latitude, longitude, india_aqi, india_aqi_category }
 *   onSelect: optional callback(city) when a pin is clicked
 */

import { useEffect, useRef, useState } from 'react'
import 'leaflet/dist/leaflet.css'

// Tracks when the Leaflet map instance is ready so the marker effect can depend on it

// AQI category → colours (background, border, text)
const AQI_COLOUR = {
  'Good':                { bg: '#16a34a', border: '#15803d', text: '#fff' },   // green-600
  'Satisfactory':        { bg: '#65a30d', border: '#4d7c0f', text: '#fff' },   // lime-600
  'Moderately Polluted': { bg: '#ca8a04', border: '#a16207', text: '#fff' },   // yellow-600
  'Poor':                { bg: '#ea580c', border: '#c2410c', text: '#fff' },   // orange-600
  'Very Poor':           { bg: '#dc2626', border: '#b91c1c', text: '#fff' },   // red-600
  'Severe':              { bg: '#7c3aed', border: '#6d28d9', text: '#fff' },   // violet-600
}

function aqiColour(category) {
  return AQI_COLOUR[category] ?? { bg: '#6b7280', border: '#4b5563', text: '#fff' }
}

// Fix Leaflet default marker icons broken by Vite/webpack bundlers
function fixLeafletIcons(L) {
  delete L.Icon.Default.prototype._getIconUrl
  L.Icon.Default.mergeOptions({
    iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
    iconUrl:       'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
    shadowUrl:     'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
  })
}

// Build a custom HTML pin icon for a given AQI value + category
function makePinIcon(L, aqi, category) {
  const c = aqiColour(category)
  const val = Math.round(aqi ?? 0)
  return L.divIcon({
    className: '',
    html: `
      <div style="
        position:relative;
        display:flex;
        flex-direction:column;
        align-items:center;
        filter:drop-shadow(0 2px 4px rgba(0,0,0,0.55));
        cursor:pointer;
      ">
        <!-- Bubble -->
        <div style="
          background:${c.bg};
          border:2px solid ${c.border};
          border-radius:8px;
          padding:2px 6px;
          min-width:36px;
          text-align:center;
          font-size:11px;
          font-weight:700;
          color:${c.text};
          font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
          white-space:nowrap;
          line-height:1.5;
        ">${val}</div>
        <!-- Pointer triangle -->
        <div style="
          width:0; height:0;
          border-left:5px solid transparent;
          border-right:5px solid transparent;
          border-top:7px solid ${c.bg};
          margin-top:-1px;
        "></div>
      </div>`,
    iconSize:    [44, 34],
    iconAnchor:  [22, 34],
    popupAnchor: [0, -36],
  })
}

export default function AQIMap({ cities = [], onSelect }) {
  const containerRef = useRef(null)
  const mapRef       = useRef(null)
  const markersRef   = useRef([])
  // FIX: track map readiness as state so the marker effect re-runs after init
  const [mapReady, setMapReady] = useState(false)

  // ── Init map once ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    import('leaflet').then(({ default: L }) => {
      // Guard: component may have unmounted during the async import
      if (!containerRef.current || mapRef.current) return

      fixLeafletIcons(L)

      const map = L.map(containerRef.current, {
        center:             [22.5, 82.5],   // centre of India
        zoom:               5,
        zoomControl:        true,
        attributionControl: true,
        scrollWheelZoom:    true,
        minZoom:            4,
        maxZoom:            12,
      })

      // Light tile layer
      L.tileLayer(
        'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
        {
          attribution: '© <a href="https://carto.com/">CARTO</a> | © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
          subdomains: 'abcd',
          maxZoom:    19,
        }
      ).addTo(map)

      mapRef.current = map
      // Signal that the map is ready → triggers the marker effect below
      setMapReady(true)
    })

    return () => {
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
        markersRef.current = []
      }
    }
  }, [])

  // ── Drop / update markers whenever cities data changes OR map becomes ready ─
  // mapReady is in the deps array so this effect fires once the async map init
  // completes, even if cities was already loaded before the map was ready.
  useEffect(() => {
    if (!mapReady || !mapRef.current || !cities.length) return

    import('leaflet').then(({ default: L }) => {
      const map = mapRef.current
      if (!map) return

      // Remove old markers
      markersRef.current.forEach(m => map.removeLayer(m))
      markersRef.current = []

      cities.forEach(city => {
        if (city.latitude == null || city.longitude == null) return

        const icon = makePinIcon(L, city.india_aqi, city.india_aqi_category)
        const marker = L.marker([city.latitude, city.longitude], { icon })

        // Rich popup
        const c = aqiColour(city.india_aqi_category)
        marker.bindPopup(`
          <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-width:160px;">
            <div style="font-size:14px;font-weight:700;color:#1f2937;margin-bottom:4px;text-transform:capitalize;">
              ${city.city}
            </div>
            <div style="font-size:11px;color:#6b7280;margin-bottom:8px;text-transform:capitalize;">${city.state}</div>
            <div style="
              display:inline-block;
              background:${c.bg};
              color:${c.text};
              font-size:13px;font-weight:700;
              padding:2px 10px;
              border-radius:6px;
              margin-bottom:4px;
            ">AQI ${Math.round(city.india_aqi ?? 0)}</div>
            <div style="font-size:11px;color:#374151;">${city.india_aqi_category ?? ''}</div>
            ${city.pm2_5_ugm3 != null ? `<div style="font-size:11px;color:#6b7280;margin-top:4px;">PM2.5: ${city.pm2_5_ugm3.toFixed(1)} µg/m³</div>` : ''}
          </div>
        `, {
          className:   'aqi-popup',
          maxWidth:    220,
          closeButton: true,
        })

        if (onSelect) {
          marker.on('click', () => onSelect(city))
        }

        marker.addTo(map)
        markersRef.current.push(marker)
      })
    })
  }, [cities, onSelect, mapReady])

  return (
    <>
      {/* Inject popup styles globally once */}
      <style>{`
        .aqi-popup .leaflet-popup-content-wrapper {
          background: #ffffff;
          border: 1px solid #e5e7eb;
          border-radius: 10px;
          box-shadow: 0 4px 20px rgba(0,0,0,0.15);
          padding: 0;
        }
        .aqi-popup .leaflet-popup-content {
          margin: 12px 14px;
        }
        .aqi-popup .leaflet-popup-tip {
          background: #ffffff;
        }
        .aqi-popup .leaflet-popup-close-button {
          color: #6b7280 !important;
          font-size: 16px !important;
          top: 6px !important;
          right: 8px !important;
        }
      `}</style>
      {/*
        isolation:isolate creates a new stacking context so Leaflet's internal
        z-indexes don't leak out and overlap the sticky navbar above.
      */}
      <div style={{ isolation: 'isolate', position: 'relative' }}>
        <div
          ref={containerRef}
          style={{ height: '460px', width: '100%', borderRadius: '0 0 14px 14px', overflow: 'hidden' }}
        />
      </div>
    </>
  )
}
