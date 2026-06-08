/**
 * AQIMap — Interactive India map with AQI pin markers
 *
 * V2 props:
 *   allStations : array of all-India stations from /aqi/india-stations
 *                 Each: { name, state, latitude, longitude, india_aqi,
 *                         india_aqi_category, station_name, stale, source }
 *   cities      : legacy fallback — 29 DB city rankings from /aqi/rankings
 *                 (used when allStations is not provided)
 *   onSelect    : optional callback(station) when a pin is clicked
 *
 * Features:
 *   • Leaflet.markercluster for smooth performance with 200+ stations
 *   • Grey markers for stale data (>3 h since last reading)
 *   • Popup shows station name, state, AQI, PM2.5, staleness warning
 */

import { useEffect, useRef, useState } from 'react'
import 'leaflet/dist/leaflet.css'
import 'leaflet.markercluster/dist/MarkerCluster.css'
import 'leaflet.markercluster/dist/MarkerCluster.Default.css'

// ── AQI category colours ──────────────────────────────────────────────────────
const AQI_COLOUR = {
  'Good':                { bg: '#16a34a', border: '#15803d', text: '#fff' },
  'Satisfactory':        { bg: '#65a30d', border: '#4d7c0f', text: '#fff' },
  'Moderately Polluted': { bg: '#ca8a04', border: '#a16207', text: '#fff' },
  'Poor':                { bg: '#ea580c', border: '#c2410c', text: '#fff' },
  'Very Poor':           { bg: '#dc2626', border: '#b91c1c', text: '#fff' },
  'Severe':              { bg: '#7c3aed', border: '#6d28d9', text: '#fff' },
  'Unknown':             { bg: '#6b7280', border: '#4b5563', text: '#fff' },
}
const STALE_COLOUR = { bg: '#9ca3af', border: '#6b7280', text: '#fff' }

function aqiColour(category, stale) {
  if (stale) return STALE_COLOUR
  return AQI_COLOUR[category] ?? AQI_COLOUR['Unknown']
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

// Build a custom HTML bubble pin icon
function makePinIcon(L, aqi, category, stale) {
  const c   = aqiColour(category, stale)
  const val = aqi != null ? Math.round(aqi) : '—'
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
        ${stale ? 'opacity:0.65;' : ''}
      ">
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

// Normalise a station entry regardless of whether it came from
// /aqi/india-stations (name/station_name fields) or /aqi/rankings (city field)
function normalise(s) {
  return {
    displayName: s.station_name || s.city || s.name || 'Station',
    city:        s.city || s.name || '',
    state:       s.state || '',
    latitude:    s.latitude,
    longitude:   s.longitude,
    india_aqi:   s.india_aqi,
    india_aqi_category: s.india_aqi_category || 'Unknown',
    pm2_5_ugm3:  s.pm2_5_ugm3,
    stale:       !!s.stale,
    source:      s.source || 'db',
  }
}

export default function AQIMap({ allStations, cities = [], onSelect }) {
  const containerRef   = useRef(null)
  const mapRef         = useRef(null)
  const clusterRef     = useRef(null)
  const [mapReady, setMapReady] = useState(false)

  // Prefer allStations (V2); fall back to legacy cities prop
  const stations = (allStations && allStations.length > 0) ? allStations : cities

  // ── Init map once ───────────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    Promise.all([
      import('leaflet'),
      import('leaflet.markercluster'),
    ]).then(([{ default: L }]) => {
      if (!containerRef.current || mapRef.current) return

      fixLeafletIcons(L)

      const map = L.map(containerRef.current, {
        center:             [22.5, 82.5],
        zoom:               5,
        zoomControl:        true,
        attributionControl: true,
        scrollWheelZoom:    true,
        minZoom:            4,
        maxZoom:            14,
      })

      L.tileLayer(
        'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
        {
          attribution: '© <a href="https://carto.com/">CARTO</a> | © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
          subdomains: 'abcd',
          maxZoom:    19,
        }
      ).addTo(map)

      mapRef.current = map
      setMapReady(true)
    })

    return () => {
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current  = null
        clusterRef.current = null
      }
    }
  }, [])

  // ── Drop / update markers whenever stations data changes or map becomes ready ─
  useEffect(() => {
    if (!mapReady || !mapRef.current || !stations.length) return

    Promise.all([
      import('leaflet'),
      import('leaflet.markercluster'),
    ]).then(([{ default: L }]) => {
      const map = mapRef.current
      if (!map) return

      // Remove previous cluster group
      if (clusterRef.current) {
        map.removeLayer(clusterRef.current)
        clusterRef.current = null
      }

      // Create a fresh cluster group
      const clusterGroup = L.markerClusterGroup({
        maxClusterRadius: 40,
        spiderfyOnMaxZoom: true,
        showCoverageOnHover: false,
        zoomToBoundsOnClick: true,
        iconCreateFunction: (cluster) => {
          const count = cluster.getChildCount()
          const size  = count < 10 ? 32 : count < 50 ? 40 : 48
          return L.divIcon({
            html: `<div style="
              background: rgba(14,165,233,0.85);
              border: 2px solid #0369a1;
              border-radius: 50%;
              width: ${size}px;
              height: ${size}px;
              display: flex;
              align-items: center;
              justify-content: center;
              font-size: 12px;
              font-weight: 700;
              color: #fff;
              font-family: -apple-system, sans-serif;
              box-shadow: 0 2px 6px rgba(0,0,0,0.3);
            ">${count}</div>`,
            className: '',
            iconSize:  [size, size],
          })
        },
      })

      stations.forEach(raw => {
        const s = normalise(raw)
        if (s.latitude == null || s.longitude == null) return

        const icon   = makePinIcon(L, s.india_aqi, s.india_aqi_category, s.stale)
        const marker = L.marker([s.latitude, s.longitude], { icon })

        const c = aqiColour(s.india_aqi_category, s.stale)
        const aqiLabel = s.india_aqi != null ? Math.round(s.india_aqi) : 'No data'

        marker.bindPopup(`
          <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-width:170px;">
            <div style="font-size:13px;font-weight:700;color:#1f2937;margin-bottom:2px;text-transform:capitalize;">
              ${s.displayName}
            </div>
            <div style="font-size:11px;color:#6b7280;margin-bottom:6px;text-transform:capitalize;">
              ${s.state}
            </div>
            <div style="
              display:inline-block;
              background:${c.bg};
              color:${c.text};
              font-size:13px;font-weight:700;
              padding:2px 10px;
              border-radius:6px;
              margin-bottom:4px;
            ">AQI ${aqiLabel}</div>
            <div style="font-size:11px;color:#374151;">${s.india_aqi_category}</div>
            ${s.pm2_5_ugm3 != null
              ? `<div style="font-size:11px;color:#6b7280;margin-top:4px;">PM2.5: ${Number(s.pm2_5_ugm3).toFixed(1)} µg/m³</div>`
              : ''}
            ${s.stale
              ? `<div style="font-size:10px;color:#f59e0b;margin-top:5px;font-weight:600;">⚠ Data may be outdated</div>`
              : ''}
            ${s.source === 'openaq'
              ? `<div style="font-size:9px;color:#9ca3af;margin-top:2px;">Source: OpenAQ</div>`
              : ''}
          </div>
        `, {
          className:   'aqi-popup',
          maxWidth:    240,
          closeButton: true,
        })

        if (onSelect) {
          marker.on('click', () => onSelect(raw))
        }

        clusterGroup.addLayer(marker)
      })

      map.addLayer(clusterGroup)
      clusterRef.current = clusterGroup
    })
  }, [stations, onSelect, mapReady])

  return (
    <>
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
        .leaflet-cluster-anim .leaflet-marker-icon,
        .leaflet-cluster-anim .leaflet-marker-shadow {
          transition: transform 0.3s ease-out, opacity 0.3s ease-in;
        }
      `}</style>
      <div style={{ isolation: 'isolate', position: 'relative' }}>
        <div
          ref={containerRef}
          style={{ height: '460px', width: '100%', borderRadius: '0 0 14px 14px', overflow: 'hidden' }}
        />
      </div>
    </>
  )
}
