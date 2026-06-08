import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import { IconRoute, IconCalendar, IconTrash, IconMapPin, IconNavigation } from '../components/Icons'

const ROUTE_BORDER = { fastest:'border-sky-600',   clean:'border-green-600',  balanced:'border-purple-600' }
const ROUTE_COLOUR = { fastest:'text-sky-400',      clean:'text-green-400',    balanced:'text-purple-400'  }
const ROUTE_ICON = {
  fastest: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
    </svg>
  ),
  clean: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 8C8 10 5.9 16.17 3.82 19.5c-.55.86.21 1.83 1.17 1.5C7 20 9 19 12 19c6 0 10-5 10-11V3a1 1 0 0 0-1.7-.71C18.5 4.07 17.5 6 17 8z"/>
    </svg>
  ),
  balanced: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="3" x2="12" y2="21"/><path d="M3 9l9-7 9 7"/><path d="M3 15l9 7 9-7"/>
    </svg>
  ),
}

const MODE_ICONS = {
  driving: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <rect x="1" y="3" width="15" height="13" rx="2"/><path d="M16 8h4l3 5v3h-7V8z"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/>
    </svg>
  ),
  cycling: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="5.5" cy="17.5" r="3.5"/><circle cx="18.5" cy="17.5" r="3.5"/><path d="M15 6a1 1 0 0 0-1-1h-1l-3 8h1l1-2h4l-2-5z"/><path d="M18.5 17.5H15l-2-5"/>
    </svg>
  ),
  walking: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M13 4a1 1 0 1 0 2 0 1 1 0 0 0-2 0"/><path d="M7.5 20l2-6 3 2 2-4"/><path d="M17 20l-2-6"/><path d="M10 9l-2 5h4l2-5"/>
    </svg>
  ),
}

function aqiColour(aqi) {
  if (!aqi)       return 'text-gray-400'
  if (aqi <= 50)  return 'text-green-400'
  if (aqi <= 100) return 'text-lime-400'
  if (aqi <= 200) return 'text-yellow-400'
  if (aqi <= 300) return 'text-orange-400'
  if (aqi <= 400) return 'text-red-400'
  return 'text-red-600'
}

function aqiLabel(aqi) {
  if (!aqi)       return 'N/A'
  if (aqi <= 50)  return 'Good'
  if (aqi <= 100) return 'Satisfactory'
  if (aqi <= 200) return 'Moderate'
  if (aqi <= 300) return 'Poor'
  if (aqi <= 400) return 'Very Poor'
  return 'Severe'
}

export default function SavedRoutes() {
  const navigate = useNavigate()

  const [routes,     setRoutes]     = useState([])
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState('')
  const [deletingId, setDeletingId] = useState(null)
  const [filter,     setFilter]     = useState('all')   // all | fastest | clean | balanced

  useEffect(() => {
    api.get('/route/history?days=365')
      .then(({ data }) => setRoutes(data.records || []))
      .catch(() => setError('Could not load saved routes.'))
      .finally(() => setLoading(false))
  }, [])

  const handleDelete = async (id) => {
    setDeletingId(id)
    try {
      await api.delete(`/route/${id}`)
      setRoutes(r => r.filter(x => x.id !== id))
    } catch {
      // silent
    } finally { setDeletingId(null) }
  }

  const filtered = filter === 'all' ? routes : routes.filter(r => r.route_type === filter)

  return (
    <div className="space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <IconCalendar size={22} className="text-sky-400" />
            Saved Routes
          </h1>
          <p className="text-gray-400 text-sm mt-1">
            Your planned journeys with travel windows and health risk scores.
          </p>
        </div>
        <button
          onClick={() => navigate('/route')}
          className="flex items-center gap-2 bg-sky-600 hover:bg-sky-500 text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition-colors"
        >
          <IconRoute size={15} />
          Plan New Route
        </button>
      </div>

      {/* Filter tabs */}
      {routes.length > 0 && (
        <div className="flex gap-2 flex-wrap">
          {['all','fastest','clean','balanced'].map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 rounded-lg text-sm border transition-colors capitalize ${
                filter === f
                  ? 'bg-sky-600 border-sky-600 text-white font-semibold'
                  : 'border-gray-700 text-gray-400 hover:border-gray-500'
              }`}
            >
              {f === 'all' ? `All (${routes.length})` : f}
            </button>
          ))}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex justify-center py-16">
          <div className="w-8 h-8 border-4 border-sky-500 border-t-transparent rounded-full animate-spin"/>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="card border-red-800 bg-red-900/10 text-red-400 text-sm">{error}</div>
      )}

      {/* Empty */}
      {!loading && !error && routes.length === 0 && (
        <div className="card text-center py-16 space-y-4">
          <IconRoute size={44} className="mx-auto text-gray-700" />
          <p className="text-gray-300 font-medium">No saved routes yet</p>
          <p className="text-gray-500 text-sm">
            Plan a route and click "Save Route" on any route card to store it here.
          </p>
          <button
            onClick={() => navigate('/route')}
            className="btn-primary mx-auto mt-2"
          >
            Go to Route Planner
          </button>
        </div>
      )}

      {/* Route cards */}
      {!loading && filtered.length > 0 && (
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filtered.map(r => {
            const borderCls = ROUTE_BORDER[r.route_type] || 'border-gray-700'
            const colourCls = ROUTE_COLOUR[r.route_type] || 'text-gray-400'
            const aqi       = r.avg_aqi_exposure
            const savedAt   = new Date(r.created_at)

            return (
              <div key={r.id} className={`card border-2 ${borderCls} flex flex-col space-y-4`}>

                {/* Card header */}
                <div className="flex items-start justify-between">
                  <div className={`flex items-center gap-2 ${colourCls}`}>
                    {ROUTE_ICON[r.route_type]}
                    <span className="font-bold text-white capitalize">{r.route_type} Route</span>
                    <span className="flex items-center gap-1 text-gray-500 text-xs ml-1">
                      {MODE_ICONS[r.travel_mode]}
                      <span className="capitalize">{r.travel_mode}</span>
                    </span>
                  </div>
                  <button
                    onClick={() => handleDelete(r.id)}
                    disabled={deletingId === r.id}
                    className="text-gray-600 hover:text-red-400 transition-colors disabled:opacity-40 p-1 -mr-1 -mt-1"
                    title="Cancel / delete this route"
                  >
                    {deletingId === r.id
                      ? <div className="w-4 h-4 border-2 border-red-400 border-t-transparent rounded-full animate-spin"/>
                      : <IconTrash size={15}/>
                    }
                  </button>
                </div>

                {/* Source → Destination */}
                <div className="bg-gray-800/50 rounded-xl px-4 py-3 space-y-2">
                  <div className="flex items-center gap-2 text-sm">
                    <IconMapPin size={13} className="text-sky-400 shrink-0"/>
                    <span className="text-gray-200 font-medium truncate">{r.source || '—'}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="w-px h-3 bg-gray-600 ml-[6px]"/>
                  </div>
                  <div className="flex items-center gap-2 text-sm">
                    <IconNavigation size={13} className="text-green-400 shrink-0"/>
                    <span className="text-gray-200 font-medium truncate">{r.destination || '—'}</span>
                  </div>
                </div>

                {/* Stats */}
                <div className="grid grid-cols-3 gap-2 text-center text-xs">
                  <div className="bg-gray-800/60 rounded-lg p-2">
                    <div className="font-bold text-white">{r.distance_km?.toFixed(1)}</div>
                    <div className="text-gray-500">km</div>
                  </div>
                  <div className="bg-gray-800/60 rounded-lg p-2">
                    <div className="font-bold text-white">{r.time_min?.toFixed(0)}</div>
                    <div className="text-gray-500">min</div>
                  </div>
                  <div className="bg-gray-800/60 rounded-lg p-2">
                    <div className={`font-bold ${aqiColour(aqi)}`}>{Math.round(aqi ?? 0)}</div>
                    <div className="text-gray-500">AQI</div>
                  </div>
                </div>

                {/* AQI label + exposure saved */}
                <div className="flex items-center justify-between text-xs">
                  <span className={`font-medium ${aqiColour(aqi)}`}>{aqiLabel(aqi)}</span>
                  {r.exposure_reduction_pct != null && (
                    <span className="text-green-400 font-medium">
                      ↓ {r.exposure_reduction_pct}% exposure saved
                    </span>
                  )}
                </div>

                {/* Travel window */}
                {r.planned_start ? (
                  <div className="bg-gray-800/40 border border-gray-700 rounded-xl px-3 py-2.5 text-xs space-y-1.5">
                    <div className="flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-sky-400 shrink-0"/>
                      <span className="text-gray-500 w-16 shrink-0">Departure</span>
                      <span className="text-gray-200 font-medium">
                        {new Date(r.planned_start).toLocaleString('en-IN', {
                          day: 'numeric', month: 'short', year: 'numeric',
                          hour: '2-digit', minute: '2-digit', hour12: true,
                        })}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-green-400 shrink-0"/>
                      <span className="text-gray-500 w-16 shrink-0">Arrival</span>
                      <span className="text-gray-200 font-medium">
                        {new Date(r.planned_end).toLocaleString('en-IN', {
                          day: 'numeric', month: 'short', year: 'numeric',
                          hour: '2-digit', minute: '2-digit', hour12: true,
                        })}
                      </span>
                    </div>
                  </div>
                ) : (
                  <div className="text-xs text-gray-600 italic">No travel window set</div>
                )}

                {/* Explanation */}
                {r.explanation && (
                  <p className="text-gray-500 text-xs leading-relaxed">{r.explanation}</p>
                )}

                {/* Saved at */}
                <p className="text-gray-700 text-xs border-t border-gray-800 pt-2">
                  Saved {savedAt.toLocaleDateString([], { dateStyle:'medium' })}
                </p>
              </div>
            )
          })}
        </div>
      )}

      {/* Filtered empty state */}
      {!loading && routes.length > 0 && filtered.length === 0 && (
        <div className="card text-center py-10">
          <p className="text-gray-500 text-sm">No <span className="capitalize">{filter}</span> routes saved yet.</p>
        </div>
      )}

    </div>
  )
}
