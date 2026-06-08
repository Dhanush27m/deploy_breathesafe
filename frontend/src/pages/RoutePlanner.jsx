import { useState, useMemo, lazy, Suspense } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../services/api'
import {
  osrmFetchRoutes, osrmFetchVia,
  routesSimilar, perpendicularViaPoints,
} from '../services/osrm'
import { useAuth } from '../context/AuthContext'
import {
  IconMapPin, IconNavigation, IconRoute, IconInfo,
  IconUser, IconCheck, IconShield, IconCalendar,
} from '../components/Icons'
import PlaceSearch from '../components/PlaceSearch'
import DateTimePicker from '../components/DateTimePicker'

// Lazy-load the map so Leaflet CSS doesn't block initial page render
const RouteMap = lazy(() => import('../components/RouteMap'))

const ROUTE_BORDER = { fastest:'border-sky-600', clean:'border-green-600', balanced:'border-purple-600' }
const ROUTE_COLOUR = { fastest:'text-sky-400',   clean:'text-green-400',   balanced:'text-purple-400'  }
const RISK_COLOUR  = { Low:'text-green-400', Moderate:'text-yellow-400', High:'text-orange-400', Severe:'text-red-400' }
const RISK_BG      = {
  Low:      'border-green-700  bg-green-900/20',
  Moderate: 'border-yellow-700 bg-yellow-900/20',
  High:     'border-orange-700 bg-orange-900/20',
  Severe:   'border-red-700    bg-red-900/20',
}

const ROUTE_ICON = {
  fastest: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
    </svg>
  ),
  clean: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 8C8 10 5.9 16.17 3.82 19.5c-.55.86.21 1.83 1.17 1.5C7 20 9 19 12 19c6 0 10-5 10-11V3a1 1 0 0 0-1.7-.71C18.5 4.07 17.5 6 17 8z"/>
    </svg>
  ),
  balanced: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="3" x2="12" y2="21"/><path d="M3 9l9-7 9 7"/><path d="M3 15l9 7 9-7"/>
    </svg>
  ),
}

const MODE_ICONS = {
  driving: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <rect x="1" y="3" width="15" height="13" rx="2"/><path d="M16 8h4l3 5v3h-7V8z"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/>
    </svg>
  ),
  cycling: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="5.5" cy="17.5" r="3.5"/><circle cx="18.5" cy="17.5" r="3.5"/><path d="M15 6a1 1 0 0 0-1-1h-1l-3 8h1l1-2h4l-2-5z"/><path d="M18.5 17.5H15l-2-5"/>
    </svg>
  ),
  walking: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M13 4a1 1 0 1 0 2 0 1 1 0 0 0-2 0"/><path d="M7.5 20l2-6 3 2 2-4"/><path d="M17 20l-2-6"/><path d="M10 9l-2 5h4l2-5"/>
    </svg>
  ),
}

// ── AQI colour badge (compact) ─────────────────────────────────────────────────
function AQIBadgeSmall({ aqi }) {
  const v = Math.round(aqi ?? 0)
  const cls = v <= 50  ? 'bg-green-900/50 text-green-300 border-green-700'
            : v <= 100 ? 'bg-yellow-900/50 text-yellow-300 border-yellow-700'
            : v <= 200 ? 'bg-orange-900/50 text-orange-300 border-orange-700'
            : v <= 300 ? 'bg-red-900/50 text-red-300 border-red-700'
            :             'bg-rose-900/50 text-rose-300 border-rose-700'
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${cls}`}>
      AQI {v}
    </span>
  )
}

// ── Via-corridor picker modal ──────────────────────────────────────────────────
function ViaSelectionModal({ source, destination, viaOptions, onSelect, onClose, loading }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 px-4">
      <div className="card max-w-lg w-full space-y-4 max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-start justify-between shrink-0">
          <div>
            <h3 className="font-bold text-white text-lg">Multiple Route Corridors Found</h3>
            <p className="text-gray-400 text-sm mt-0.5">
              {source} → {destination}
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-300 text-2xl leading-none px-1 ml-4 shrink-0"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <p className="text-gray-300 text-sm shrink-0">
          More than 3 distinct routes exist for this journey. Select a corridor below —
          we'll then show you the <span className="text-sky-400 font-medium">fastest</span>,{' '}
          <span className="text-green-400 font-medium">cleanest</span> and{' '}
          <span className="text-purple-400 font-medium">balanced</span> options within that path.
        </p>

        {/* Route option list */}
        <div className="space-y-2 overflow-y-auto flex-1 pr-1">
          {viaOptions.map((opt, i) => (
            <button
              key={i}
              onClick={() => !loading && onSelect(opt)}
              disabled={loading}
              className="w-full text-left border border-gray-700 hover:border-sky-600
                         bg-gray-800/60 hover:bg-gray-800/90 rounded-xl p-3.5
                         transition-all disabled:opacity-50 disabled:cursor-not-allowed group"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="font-semibold text-white text-sm group-hover:text-sky-300 transition-colors">
                  {opt.label}
                </span>
                <AQIBadgeSmall aqi={opt.avg_aqi} />
              </div>
              <div className="flex gap-4 text-xs text-gray-400">
                <span className="flex items-center gap-1">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
                  </svg>
                  ~{Math.round(opt.time_min)} min
                </span>
                <span className="flex items-center gap-1">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M3 12h18M3 6h18M3 18h18"/>
                  </svg>
                  {opt.distance_km.toFixed(1)} km
                </span>
                <span className="text-gray-500">Avg AQI: {Math.round(opt.avg_aqi)}</span>
              </div>
            </button>
          ))}
        </div>

        {loading && (
          <div className="flex items-center justify-center gap-2 text-sm text-gray-400 py-1 shrink-0">
            <div className="w-4 h-4 border-2 border-sky-500 border-t-transparent rounded-full animate-spin" />
            Loading routes for selected corridor…
          </div>
        )}

        <p className="text-xs text-gray-600 shrink-0 pt-1">
          Can't decide? Close this and plan without a via point — we'll pick the best 3 paths automatically.
        </p>
      </div>
    </div>
  )
}

// ── Health Warning Modal ───────────────────────────────────────────────────────
function HealthWarningModal({ warning, onContinue, onCancel, cancelling }) {
  const cat = warning.risk_category
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4">
      <div className={`card border-2 ${RISK_BG[cat] ?? 'border-orange-700 bg-orange-900/20'} max-w-lg w-full space-y-4`}>
        {/* Header */}
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-full ${cat === 'Severe' ? 'bg-red-800/40' : 'bg-orange-800/40'}`}>
            <IconShield size={22} className={RISK_COLOUR[cat] ?? 'text-orange-400'} />
          </div>
          <div>
            <h3 className="font-bold text-white text-lg">Health Risk Detected</h3>
            <p className={`text-sm font-semibold ${RISK_COLOUR[cat] ?? 'text-orange-400'}`}>
              {cat} Risk — Score {warning.risk_score?.toFixed(0)}/100
            </p>
          </div>
        </div>

        {/* Message */}
        <p className="text-gray-300 text-sm leading-relaxed">{warning.message}</p>

        {/* What this means */}
        <div className="bg-gray-800/60 rounded-xl px-4 py-3 text-sm space-y-1">
          <p className="text-gray-400 font-medium">What should you do?</p>
          {cat === 'Severe' && (
            <p className="text-red-300">This journey poses a serious health risk. Consider postponing or use N95 protection and limit time outdoors.</p>
          )}
          {cat === 'High' && (
            <p className="text-orange-300">Wear an N95 mask and try to limit the duration of outdoor exposure during this journey.</p>
          )}
          <p className="text-gray-400 text-xs mt-1">
            This alert has been saved to your{' '}
            <span className="text-sky-400 font-medium">Alerts</span> tab for reference.
          </p>
        </div>

        {/* Actions */}
        <div className="flex gap-3 pt-1">
          <button
            onClick={onContinue}
            className="flex-1 flex items-center justify-center gap-2 bg-gray-700 hover:bg-gray-600 border border-gray-600 text-white font-semibold py-2.5 rounded-xl transition-colors text-sm"
          >
            <IconCheck size={15} />
            Continue Journey
          </button>
          <button
            onClick={onCancel}
            disabled={cancelling}
            className="flex-1 bg-red-700 hover:bg-red-600 disabled:opacity-60 text-white font-semibold py-2.5 rounded-xl transition-colors text-sm"
          >
            {cancelling ? 'Cancelling…' : 'Cancel Journey'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Datetime helpers ──────────────────────────────────────────────────────────
function defaultDeparture() {
  const d = new Date()
  d.setSeconds(0, 0)
  d.setMinutes(Math.ceil(d.getMinutes() / 5) * 5)
  return d.toISOString()
}

function fmtDuration(mins) {
  const h = Math.floor(mins / 60)
  const m = Math.round(mins % 60)
  if (h > 0 && m > 0) return `${h}h ${m}m`
  if (h > 0)           return `${h}h`
  return `${m} min`
}

// ══════════════════════════════════════════════════════════════════════════════
export default function RoutePlanner() {
  const { user } = useAuth()
  const navigate = useNavigate()

  // Route calculation form — src/dst hold { name, lat, lon }
  const [src,           setSrc]           = useState({ name: '', lat: null, lon: null })
  const [dst,           setDst]           = useState({ name: '', lat: null, lon: null })
  const [mode,          setMode]          = useState('driving')
  const [result,        setResult]        = useState(null)
  const [loading,       setLoading]       = useState(false)
  const [error,         setError]         = useState('')
  const [selectedRoute, setSelectedRoute] = useState('clean')

  // Via-corridor picker state
  const [viaModal,   setViaModal]   = useState(null)   // null | { source, destination, via_options }
  const [viaLoading, setViaLoading] = useState(false)

  // Travel window (logged-in users)
  const [travelStart,     setTravelStart]     = useState(defaultDeparture)
  const [travelEndManual, setTravelEndManual] = useState(null)
  const [arrivalIsAuto,   setArrivalIsAuto]   = useState(true)

  // Per-card save state: { [route_type]: { saving, saved, error, data } }
  const [saving,  setSaving]  = useState({})
  const [saved,   setSaved]   = useState({})
  const [saveErr, setSaveErr] = useState({})

  // ── Derived travel times ────────────────────────────────────────────────────
  const computedArrival = useMemo(() => {
    const route = result?.routes?.find(r => r.route_type === selectedRoute)
    if (!route || !travelStart) return null
    const dep = new Date(travelStart)
    return new Date(dep.getTime() + route.time_min * 60_000).toISOString()
  }, [result, selectedRoute, travelStart])

  const arrivalMin = computedArrival || travelStart
  const travelEnd  = arrivalIsAuto ? computedArrival : travelEndManual

  const selectedRouteData = result?.routes?.find(r => r.route_type === selectedRoute)
  const arrivalHint = (() => {
    if (!result || !selectedRouteData) return 'Auto-fills once you plan a route'
    const dur = fmtDuration(selectedRouteData.time_min)
    if (arrivalIsAuto) return `⚡ Auto · ${selectedRoute} route · ~${dur} journey`
    return `~${dur} by ${selectedRoute} route · using your custom arrival`
  })()

  // Health warning modal
  const [warningModal, setWarningModal] = useState(null)
  const [cancelling,   setCancelling]   = useState(false)

  // ── Build OSRM route pool in the browser ───────────────────────────────────
  // Avoids Render's outbound-connection restriction; browser can reach OSRM directly.
  const _buildOsrmPool = async (srcLat, srcLon, dstLat, dstLon, travelMode, viaLat, viaLon) => {
    if (viaLat != null && viaLon != null) {
      // Via specified: route through it, then supplement with alternatives
      const viaRoute = await osrmFetchVia(srcLat, srcLon, viaLat, viaLon, dstLat, dstLon, travelMode)
      if (!viaRoute) return null
      const pool = [viaRoute]
      const natural = await osrmFetchRoutes(srcLat, srcLon, dstLat, dstLon, travelMode, 3)
      for (const r of natural) {
        if (pool.length >= 3) break
        if (!routesSimilar(r, viaRoute)) pool.push(r)
      }
      return pool
    }

    // No via: fetch alternatives + generate synthetics if needed
    const pool = await osrmFetchRoutes(srcLat, srcLon, dstLat, dstLon, travelMode, 3)
    if (!pool.length) return null

    if (pool.length < 3) {
      const vias = perpendicularViaPoints(srcLat, srcLon, dstLat, dstLon)
      for (const [vLat, vLon] of vias) {
        if (pool.length >= 5) break
        const synth = await osrmFetchVia(srcLat, srcLon, vLat, vLon, dstLat, dstLon, travelMode)
        if (!synth) continue
        if (!pool.some(r => routesSimilar(synth, r))) {
          synth._via_lat = vLat
          synth._via_lon = vLon
          pool.push(synth)
        }
      }
    }
    return pool
  }

  // ── Core route fetch (shared by submit and via-select) ──────────────────────
  // Routes are fetched directly from the user's browser (OSRM public API).
  // The backend /route/score endpoint only does AQI scoring — no OSRM call.
  // This sidesteps Render's blocked outbound connections to OSRM servers.
  const _fetchRoutes = async (params) => {
    const { source_lat, source_lon, dest_lat, dest_lon, travel_mode, via_lat, via_lon } = params

    console.log('[BreatheSafe] Fetching routes via browser-side OSRM…')

    let pool = null
    try {
      pool = await _buildOsrmPool(
        source_lat, source_lon, dest_lat, dest_lon,
        travel_mode, via_lat ?? null, via_lon ?? null,
      )
    } catch (err) {
      console.error('[BreatheSafe] OSRM pool build threw:', err?.message)
    }

    if (!pool || pool.length === 0) {
      console.warn('[BreatheSafe] Both OSRM servers returned no routes.')
      throw new Error(
        'The routing service (OpenStreetMap) could not find a route. ' +
        'Both routing servers may be temporarily busy — please wait a moment and try again.',
      )
    }

    console.log(`[BreatheSafe] OSRM returned ${pool.length} route(s). Scoring AQI…`)

    const osrmRoutes = pool.map(r => ({
      distance_m: r.distance,
      duration_s: r.duration,
      geometry:   r.geometry,
      via_lat:    r._via_lat ?? null,
      via_lon:    r._via_lon ?? null,
    }))

    const { data } = await api.post('/route/score', { ...params, osrm_routes: osrmRoutes })
    return data
  }

  // ── Initial form submit ─────────────────────────────────────────────────────
  const submit = async e => {
    e.preventDefault()
    if (!src.lat || !dst.lat) {
      setError('Please select a source and destination from the suggestions.')
      return
    }
    setError(''); setLoading(true); setResult(null); setViaModal(null)
    setSaved({}); setSaveErr({})
    setSelectedRoute('clean')
    try {
      const data = await _fetchRoutes({
        source_lat:  src.lat, source_lon: src.lon, source_name: src.name || undefined,
        dest_lat:    dst.lat, dest_lon:   dst.lon, dest_name:   dst.name || undefined,
        travel_mode: mode,
      })

      if (data.needs_via_selection) {
        // More than 3 corridors found — show picker before rendering cards
        setViaModal({
          source:      data.source,
          destination: data.destination,
          via_options: data.via_options,
        })
        return
      }

      setResult(data)
      if (data.routes?.length) {
        const preferred = data.routes.find(r => r.route_type === 'clean') || data.routes[0]
        setSelectedRoute(preferred.route_type)
        setArrivalIsAuto(true)
        setTravelEndManual(null)
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Route planning failed.')
    } finally {
      setLoading(false)
    }
  }

  // ── Via corridor selected from modal ───────────────────────────────────────
  const handleViaSelect = async (viaOpt) => {
    setViaLoading(true)
    setError('')
    try {
      const data = await _fetchRoutes({
        source_lat:  src.lat, source_lon: src.lon, source_name: src.name || undefined,
        dest_lat:    dst.lat, dest_lon:   dst.lon, dest_name:   dst.name || undefined,
        travel_mode: mode,
        via_lat:     viaOpt.via_lat,
        via_lon:     viaOpt.via_lon,
        via_name:    viaOpt.label,
      })
      setViaModal(null)
      setSaved({}); setSaveErr({})

      if (data.needs_via_selection) {
        // Rare: still too many paths even through the via — show picker again with the new set
        setViaModal({
          source:      data.source,
          destination: data.destination,
          via_options: data.via_options,
        })
        return
      }

      setResult(data)
      if (data.routes?.length) {
        const preferred = data.routes.find(r => r.route_type === 'clean') || data.routes[0]
        setSelectedRoute(preferred.route_type)
        setArrivalIsAuto(true)
        setTravelEndManual(null)
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Route planning failed.')
      setViaModal(null)
    } finally {
      setViaLoading(false)
    }
  }

  const handleSave = async (route) => {
    if (!travelStart) {
      setSaveErr(e => ({ ...e, [route.route_type]: 'Set a departure time first.' })); return
    }
    const routeTimeMs   = (route.time_min ?? 60) * 60_000
    const minArrival    = new Date(new Date(travelStart).getTime() + routeTimeMs)
    const manualArrival = !arrivalIsAuto && travelEndManual ? new Date(travelEndManual) : null
    const effectiveEnd  = (manualArrival && manualArrival > minArrival) ? manualArrival : minArrival

    setSaving(s  => ({ ...s, [route.route_type]: true }))
    setSaveErr(e => ({ ...e, [route.route_type]: ''   }))
    try {
      const { data } = await api.post('/route/save', {
        route_type:             route.route_type,
        source_lat:             src.lat,   source_lon: src.lon,
        source_name:            src.name || result?.source,
        dest_lat:               dst.lat,   dest_lon:   dst.lon,
        dest_name:              dst.name || result?.destination,
        travel_mode:            mode,
        distance_km:            route.distance_km,
        time_min:               route.time_min,
        avg_aqi_exposure:       route.avg_aqi_exposure,
        exposure_reduction_pct: route.exposure_reduction_pct,
        explanation:            route.explanation,
        planned_start:          new Date(travelStart).toISOString(),
        planned_end:            effectiveEnd.toISOString(),
      })
      setSaved(s => ({ ...s, [route.route_type]: data }))
      if (data.health_warning) {
        setWarningModal({ ...data, routeType: route.route_type, routeId: data.id })
      }
    } catch (err) {
      setSaveErr(e => ({ ...e, [route.route_type]: err.response?.data?.detail || 'Save failed.' }))
    } finally {
      setSaving(s => ({ ...s, [route.route_type]: false }))
    }
  }

  const handleModalContinue = () => setWarningModal(null)

  const handleModalCancel = async () => {
    if (!warningModal?.routeId) { setWarningModal(null); return }
    setCancelling(true)
    try {
      await api.delete(`/route/${warningModal.routeId}`)
      setSaved(s => { const c = {...s}; delete c[warningModal.routeType]; return c })
    } catch { /* close regardless */ }
    finally { setCancelling(false); setWarningModal(null) }
  }

  const handleStartChange = val => {
    setTravelStart(val)
    if (!arrivalIsAuto && travelEndManual && result) {
      const route = result.routes?.find(r => r.route_type === selectedRoute)
      if (route) {
        const newMin = new Date(new Date(val).getTime() + route.time_min * 60_000)
        if (new Date(travelEndManual) <= newMin) {
          setArrivalIsAuto(true)
          setTravelEndManual(null)
        }
      }
    }
  }

  const handleEndChange = val => {
    setTravelEndManual(val)
    setArrivalIsAuto(false)
  }

  const resetArrivalToAuto = () => {
    setArrivalIsAuto(true)
    setTravelEndManual(null)
  }


  return (
    <div className="space-y-6">

      {/* Via corridor picker modal */}
      {viaModal && (
        <ViaSelectionModal
          source={viaModal.source}
          destination={viaModal.destination}
          viaOptions={viaModal.via_options}
          onSelect={handleViaSelect}
          onClose={() => setViaModal(null)}
          loading={viaLoading}
        />
      )}

      {/* Health warning modal */}
      {warningModal && (
        <HealthWarningModal
          warning={warningModal}
          onContinue={handleModalContinue}
          onCancel={handleModalCancel}
          cancelling={cancelling}
        />
      )}

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-white">Pollution-Aware Route Planner</h1>
          <p className="text-gray-400 text-sm mt-1">
            Fastest, cleanest, and balanced routes with real-time AQI overlay.
            {user
              ? ' Set your travel window and save a route to get a personalised health check.'
              : ' No login required to plan.'}
          </p>
        </div>
        {user && (
          <button
            onClick={() => navigate('/saved-routes')}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold border border-gray-700 bg-gray-800 text-gray-300 hover:border-sky-600 hover:text-sky-400 transition-colors shrink-0"
          >
            <IconCalendar size={15} />
            Saved Routes
          </button>
        )}
      </div>

      {/* Plan form */}
      <form onSubmit={submit} className="card space-y-4">
        <div className="grid md:grid-cols-2 gap-4">
          {/* Source */}
          <div className="space-y-1.5">
            <h3 className="flex items-center gap-1.5 text-sky-400 text-sm font-medium">
              <IconMapPin size={14} /> Source
            </h3>
            <PlaceSearch
              value={src}
              onChange={setSrc}
              placeholder="Enter source"
              accentClass="text-sky-400"
              icon={<IconMapPin size={14} />}
              required
            />
            {src.lat && (
              <p className="text-xs text-gray-600 pl-1">
                {src.lat.toFixed(4)}, {src.lon.toFixed(4)}
              </p>
            )}
          </div>

          {/* Destination */}
          <div className="space-y-1.5">
            <h3 className="flex items-center gap-1.5 text-green-400 text-sm font-medium">
              <IconNavigation size={14} /> Destination
            </h3>
            <PlaceSearch
              value={dst}
              onChange={setDst}
              placeholder="Enter destination"
              accentClass="text-green-400"
              icon={<IconNavigation size={14} />}
              required
            />
            {dst.lat && (
              <p className="text-xs text-gray-600 pl-1">
                {dst.lat.toFixed(4)}, {dst.lon.toFixed(4)}
              </p>
            )}
          </div>
        </div>

        {/* Travel mode */}
        <div className="flex gap-2 flex-wrap">
          {['driving','cycling','walking'].map(m => (
            <button key={m} type="button" onClick={() => setMode(m)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border transition-colors capitalize ${
                mode === m ? 'bg-sky-600 border-sky-600 text-white' : 'border-gray-700 text-gray-400 hover:border-gray-500'
              }`}>
              {MODE_ICONS[m]}{m}
            </button>
          ))}
        </div>

        {/* Travel window */}
        <div className="border border-gray-700 rounded-xl p-4 space-y-3 bg-gray-800/30">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide flex items-center gap-1.5">
              <IconCalendar size={12} />
              Planned Travel Window
            </p>
            {travelStart && (
              <span className="text-[10px] text-gray-600 bg-gray-800 border border-gray-700 px-2 py-0.5 rounded-full">
                Departure: {new Date(travelStart).toLocaleString('en-IN', {
                  day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'
                })}
              </span>
            )}
          </div>

          <div className="grid sm:grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="label flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-sky-400 inline-block" />
                Departure
              </label>
              <DateTimePicker
                value={travelStart}
                onChange={handleStartChange}
                min={new Date().toISOString()}
                accentColor="sky"
                hint="Earliest selectable time is now"
              />
            </div>

            <div className="space-y-1">
              <label className="label flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-green-400 inline-block" />
                Arrival
                {arrivalIsAuto && result && (
                  <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full
                                   bg-green-900/30 text-green-400 border border-green-800/60 ml-1">
                    Auto
                  </span>
                )}
                {!arrivalIsAuto && (
                  <button
                    type="button"
                    onClick={resetArrivalToAuto}
                    className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full
                               bg-yellow-900/20 text-yellow-400 border border-yellow-800/40 ml-1
                               hover:bg-yellow-900/40 transition-colors"
                    title="Reset arrival back to auto (route ETA)"
                  >
                    Manual · Reset ↩
                  </button>
                )}
              </label>
              <DateTimePicker
                value={travelEnd}
                onChange={handleEndChange}
                min={arrivalMin}
                accentColor="green"
                hint={arrivalHint}
              />
            </div>
          </div>

          <p className="text-xs text-gray-600">
            {user
              ? 'Health risk is assessed against this window when you save a route. You can extend the arrival beyond the estimated journey time.'
              : 'Log in to save this route with travel times and get a personalised health risk assessment.'}
          </p>
        </div>

        {error && <p className="text-red-400 text-sm bg-red-900/20 border border-red-800 rounded-lg px-3 py-2">{error}</p>}

        <button type="submit" disabled={loading || viaLoading} className="btn-primary flex items-center gap-2 disabled:opacity-60">
          <IconRoute size={15} />
          {loading ? 'Planning routes…' : 'Find Routes'}
        </button>
      </form>

      {loading && (
        <div className="flex justify-center py-8">
          <div className="w-8 h-8 border-4 border-sky-500 border-t-transparent rounded-full animate-spin"/>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-5">

          {/* Journey header */}
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2 flex-wrap">
              <p className="text-gray-400 text-sm">
                <span className="text-white font-medium">{result.source}</span>
                {' '}&rarr;{' '}
                <span className="text-white font-medium">{result.destination}</span>
                {' '}•{' '}<span className="capitalize">{result.travel_mode}</span>
              </p>
              {/* Via corridor badge */}
              {result.via_label && (
                <span className="text-xs px-2.5 py-0.5 rounded-full bg-sky-900/30 text-sky-300 border border-sky-700 font-medium">
                  via {result.via_label}
                </span>
              )}
            </div>
            <p className="text-gray-600 text-xs">Click a route card to highlight it on the map</p>
          </div>


          {/* Map box */}
          <div className="card p-0 overflow-hidden border border-gray-700">
            <div className="flex items-center gap-4 px-4 py-2.5 bg-gray-800/80 border-b border-gray-700 flex-wrap">
              <span className="text-xs text-gray-400 font-medium">Highlight:</span>
              {result.routes?.map(r => (
                <button
                  key={r.route_type}
                  onClick={() => setSelectedRoute(r.route_type)}
                  className={`flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-lg border transition-colors capitalize ${
                    selectedRoute === r.route_type
                      ? `${ROUTE_BORDER[r.route_type]} ${ROUTE_COLOUR[r.route_type]} bg-gray-700`
                      : 'border-gray-700 text-gray-500 hover:border-gray-500'
                  }`}
                >
                  {ROUTE_ICON[r.route_type]}
                  {r.route_type}
                </button>
              ))}
              {/* Colour legend — always visible */}
              <div className="ml-auto flex items-center gap-3 text-xs text-gray-500">
                <span className="flex items-center gap-1"><span className="w-3 h-1.5 rounded bg-sky-400 inline-block"/>Fastest</span>
                <span className="flex items-center gap-1"><span className="w-3 h-1.5 rounded bg-green-400 inline-block"/>Cleanest</span>
                <span className="flex items-center gap-1"><span className="w-3 h-1.5 rounded bg-purple-400 inline-block"/>Balanced</span>
              </div>
            </div>
            {result.single_path && (
              <div className="px-4 py-2 bg-sky-900/10 border-b border-sky-900/30 text-xs text-sky-400 flex items-center gap-2">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                Same road path — fastest &amp; cleanest take identical roads; AQI scores differ by weighting.
              </div>
            )}

            <Suspense fallback={
              <div className="flex items-center justify-center bg-gray-800" style={{ height:'380px' }}>
                <div className="w-8 h-8 border-4 border-sky-500 border-t-transparent rounded-full animate-spin"/>
              </div>
            }>
              <RouteMap
                routes={result.routes}
                selectedType={selectedRoute}
                sourceLat={result.source_lat}  sourceLon={result.source_lon}
                destLat={result.dest_lat}      destLon={result.dest_lon}
                sourceName={result.source}     destName={result.destination}
              />
            </Suspense>
          </div>

          {/* Route cards */}
          <div className="grid md:grid-cols-3 gap-4">
            {result.routes?.map(r => {
              const isSaved    = !!saved[r.route_type]
              const isSaving   = !!saving[r.route_type]
              const cardErr    = saveErr[r.route_type]
              const savedData  = saved[r.route_type]
              const isSelected = selectedRoute === r.route_type

              return (
                <div
                  key={r.route_type}
                  onClick={() => setSelectedRoute(r.route_type)}
                  className={`card border-2 space-y-3 flex flex-col cursor-pointer transition-all duration-150 ${
                    ROUTE_BORDER[r.route_type]
                  } ${isSelected ? 'ring-2 ring-offset-2 ring-offset-gray-950 ' + ROUTE_BORDER[r.route_type].replace('border-','ring-') + ' shadow-lg scale-[1.01]' : 'opacity-80 hover:opacity-100'}`}
                >
                  {/* Header */}
                  <div className={`flex items-center justify-between ${ROUTE_COLOUR[r.route_type]}`}>
                    <div className="flex items-center gap-2">
                      {ROUTE_ICON[r.route_type]}
                      <span className="font-bold text-white capitalize">{r.route_type} Route</span>
                    </div>
                    {isSelected && (
                      <span className={`text-xs px-2 py-0.5 rounded-full border ${ROUTE_BORDER[r.route_type]} ${ROUTE_COLOUR[r.route_type]} font-semibold`}>
                        On map
                      </span>
                    )}
                  </div>

                  {/* Stats */}
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    {[
                      ['Distance',       `${r.distance_km?.toFixed(1)} km`],
                      ['Time',           `${r.time_min?.toFixed(0)} min`],
                      ['Avg AQI',        `${Math.round(r.avg_aqi_exposure ?? 0)}`],
                      ['Exposure Saved', r.exposure_reduction_pct != null ? `${r.exposure_reduction_pct}%` : '—'],
                    ].map(([l,v]) => (
                      <div key={l} className="bg-gray-800/60 rounded-lg p-2 text-center">
                        <div className="font-bold text-white">{v}</div>
                        <div className="text-gray-500 text-xs">{l}</div>
                      </div>
                    ))}
                  </div>

                  <p className="text-gray-400 text-xs leading-relaxed flex-1">{r.explanation}</p>

                  {/* Save section — logged-in users only */}
                  {user && (
                    <div
                      className="pt-2 border-t border-gray-700/60 space-y-2"
                      onClick={e => e.stopPropagation()}
                    >
                      {isSaved ? (
                        <div className="space-y-1.5">
                          <div className="flex items-center gap-1.5 text-green-400 text-xs font-semibold">
                            <IconCheck size={13} /> Route saved
                          </div>
                          {savedData?.planned_start && (
                            <div className="space-y-0.5 text-xs text-gray-500">
                              <div className="flex items-center gap-1.5">
                                <span className="w-1.5 h-1.5 rounded-full bg-sky-400 shrink-0"/>
                                {new Date(savedData.planned_start).toLocaleString('en-IN', {
                                  day:'numeric', month:'short', year:'numeric',
                                  hour:'2-digit', minute:'2-digit', hour12:true,
                                })}
                              </div>
                              <div className="flex items-center gap-1.5">
                                <span className="w-1.5 h-1.5 rounded-full bg-green-400 shrink-0"/>
                                {new Date(savedData.planned_end).toLocaleString('en-IN', {
                                  day:'numeric', month:'short', year:'numeric',
                                  hour:'2-digit', minute:'2-digit', hour12:true,
                                })}
                              </div>
                            </div>
                          )}
                          {savedData?.risk_score != null && (
                            <div className={`flex items-center gap-1 text-xs font-medium ${RISK_COLOUR[savedData.risk_category] ?? 'text-gray-400'}`}>
                              <IconShield size={12} />
                              Risk: {savedData.risk_category} ({savedData.risk_score?.toFixed(0)}/100)
                              {savedData.health_warning && ' — check Alerts'}
                            </div>
                          )}
                        </div>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={() => handleSave(r)}
                            disabled={isSaving}
                            className={`w-full flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm font-semibold border transition-colors disabled:opacity-60 ${ROUTE_BORDER[r.route_type]} ${ROUTE_COLOUR[r.route_type]} hover:bg-gray-800`}
                          >
                            {isSaving
                              ? <><div className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin"/>Saving…</>
                              : <><IconRoute size={14}/>Save Route</>
                            }
                          </button>
                          {cardErr && <p className="text-red-400 text-xs">{cardErr}</p>}
                        </>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {result.tip && (
            <div className="card border-sky-800 bg-sky-900/10 flex items-start gap-2 text-sm text-gray-300">
              <IconInfo size={15} className="text-sky-400 shrink-0 mt-0.5" />
              {result.tip}
            </div>
          )}
        </div>
      )}

      {/* Guest CTA */}
      {!user && (
        <div className="flex items-center gap-3 bg-sky-900/20 border border-sky-800 rounded-xl px-4 py-3">
          <IconUser size={18} className="text-sky-400 shrink-0" />
          <p className="text-sm text-gray-300">
            <Link to="/login" className="text-sky-400 hover:text-sky-300 font-medium underline">Log in</Link>
            {' '}or{' '}
            <Link to="/register" className="text-sky-400 hover:text-sky-300 font-medium underline">Sign up</Link>
            {' '}to save routes and receive personalised health risk alerts for your planned travel window.
          </p>
        </div>
      )}
    </div>
  )
}
