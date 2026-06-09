import { useEffect, useState, useRef, lazy, Suspense } from 'react'
import { Link } from 'react-router-dom'
import api from '../services/api'
import AQIBadge from '../components/AQIBadge'
import { IconSearch, IconChevronRight, IconMapPin } from '../components/Icons'

const AQIMap = lazy(() => import('../components/AQIMap'))

// AQI category → pill colour class
const CAT_COLOUR = {
  'Good':                'bg-green-600',
  'Satisfactory':        'bg-lime-600',
  'Moderately Polluted': 'bg-yellow-600',
  'Poor':                'bg-orange-600',
  'Very Poor':           'bg-red-600',
  'Severe':              'bg-violet-600',
}

function Spinner() {
  return (
    <div className="flex items-center justify-center py-24">
      <div className="w-8 h-8 border-4 border-sky-500 border-t-transparent rounded-full animate-spin" />
    </div>
  )
}

// Highlight the matched substring in a string
function Highlight({ text, query }) {
  if (!query) return <>{text}</>
  const idx = text.toLowerCase().indexOf(query.toLowerCase())
  if (idx === -1) return <>{text}</>
  return (
    <>
      {text.slice(0, idx)}
      <span className="text-sky-300 font-bold">{text.slice(idx, idx + query.length)}</span>
      {text.slice(idx + query.length)}
    </>
  )
}

export default function Dashboard() {
  const [rankings,      setRankings]      = useState([])
  const [stats,         setStats]         = useState(null)
  const [loading,       setLoading]       = useState(true)
  const [search,        setSearch]        = useState('')
  const [showDropdown,  setShowDropdown]  = useState(false)
  const [activeIdx,     setActiveIdx]     = useState(-1)   // keyboard nav
  const [selectedCity,  setSelectedCity]  = useState(null)
  const searchRef = useRef(null)
  const dropdownRef = useRef(null)

  useEffect(() => {
    Promise.all([
      api.get('/aqi/rankings?order=desc'),
      api.get('/aqi/stats'),
    ]).then(([r, s]) => {
      setRankings(r.data)
      setStats(s.data)
    }).finally(() => setLoading(false))
  }, [])

  // Close dropdown on outside click
  useEffect(() => {
    function onOutside(e) {
      if (
        searchRef.current && !searchRef.current.contains(e.target) &&
        dropdownRef.current && !dropdownRef.current.contains(e.target)
      ) setShowDropdown(false)
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [])

  // Suggestions: cities/states matching current search (max 8)
  const suggestions = search.trim().length === 0 ? [] : rankings.filter(c =>
    c.city.toLowerCase().includes(search.toLowerCase()) ||
    c.state.toLowerCase().includes(search.toLowerCase())
  ).slice(0, 8)

  // Table filter: exact same logic, but uses full list when dropdown closed
  const filtered = rankings.filter(c =>
    c.city.toLowerCase().includes(search.toLowerCase()) ||
    c.state.toLowerCase().includes(search.toLowerCase())
  )

  const pickCity = (c) => {
    setSearch(c.city)
    setShowDropdown(false)
    setActiveIdx(-1)
    setSelectedCity(c)
    setTimeout(() => {
      const el = document.getElementById(`city-row-${c.city}`)
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 100)
  }

  const handleKeyDown = (e) => {
    if (!showDropdown || suggestions.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx(i => Math.min(i + 1, suggestions.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && activeIdx >= 0) {
      e.preventDefault()
      pickCity(suggestions[activeIdx])
    } else if (e.key === 'Escape') {
      setShowDropdown(false)
    }
  }

  if (loading) return <Spinner />

  const best  = [...rankings].sort((a, b) => (a.india_aqi||0) - (b.india_aqi||0))[0]
  const worst = rankings[0]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">AQI Dashboard</h1>
          <p className="text-gray-400 text-sm">Latest readings for 29 monitored cities</p>
        </div>

        {/* Search with autocomplete */}
        <div className="relative" ref={searchRef}>
          <IconSearch size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none z-10" />
          <input
            className="input-field w-64 pl-9 pr-8"
            placeholder="Search city or state…"
            value={search}
            onChange={e => {
              setSearch(e.target.value)
              setShowDropdown(true)
              setActiveIdx(-1)
            }}
            onFocus={() => { if (search.trim()) setShowDropdown(true) }}
            onKeyDown={handleKeyDown}
            autoComplete="off"
          />
          {search && (
            <button
              onClick={() => { setSearch(''); setShowDropdown(false); setSelectedCity(null) }}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 text-lg leading-none"
            >×</button>
          )}

          {/* Dropdown */}
          {showDropdown && suggestions.length > 0 && (
            <div
              ref={dropdownRef}
              className="absolute z-50 top-full mt-1 w-full bg-gray-900 border border-gray-700 rounded-xl shadow-2xl overflow-hidden"
            >
              {suggestions.map((c, i) => (
                <button
                  key={c.city}
                  onMouseDown={e => { e.preventDefault(); pickCity(c) }}
                  onMouseEnter={() => setActiveIdx(i)}
                  className={`w-full flex items-center justify-between px-3 py-2.5 text-left transition-colors ${
                    i === activeIdx ? 'bg-gray-800' : 'hover:bg-gray-800/60'
                  } ${i < suggestions.length - 1 ? 'border-b border-gray-800' : ''}`}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <IconMapPin size={12} className="text-gray-500 shrink-0" />
                    <div className="min-w-0">
                      <div className="text-sm text-white font-medium capitalize truncate">
                        <Highlight text={c.city} query={search} />
                      </div>
                      <div className="text-xs text-gray-500 capitalize truncate">
                        <Highlight text={c.state} query={search} />
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0 ml-2">
                    <span className="text-sm font-bold text-white">{Math.round(c.india_aqi ?? 0)}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold text-white ${CAT_COLOUR[c.india_aqi_category] ?? 'bg-gray-600'}`}>
                      {c.india_aqi_category?.split(' ')[0]}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* No results hint */}
          {showDropdown && search.trim().length > 0 && suggestions.length === 0 && (
            <div className="absolute z-50 top-full mt-1 w-full bg-gray-900 border border-gray-700 rounded-xl shadow-xl px-4 py-3 text-sm text-gray-500">
              No city or state matches "{search}"
            </div>
          )}
        </div>
      </div>

      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Cities Monitored', value: stats.cities },
            { label: 'Avg India AQI',    value: stats.avg_india_aqi },
            { label: 'Cleanest City',    value: best?.city?.toUpperCase(),  sub: `AQI ${Math.round(best?.india_aqi||0)}` },
            { label: 'Most Polluted',    value: worst?.city?.toUpperCase(), sub: `AQI ${Math.round(worst?.india_aqi||0)}` },
          ].map(s => (
            <div key={s.label} className="card text-center">
              <div className="text-2xl font-black text-sky-400">{s.value}</div>
              {s.sub && <div className="text-xs text-gray-400">{s.sub}</div>}
              <div className="text-gray-500 text-xs mt-0.5">{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* ── Live AQI Map ─────────────────────────────────────────────────────── */}
      <div className="card p-0 overflow-hidden border border-gray-700">
        {/* Map header */}
        <div className="flex items-center justify-between px-4 py-3 bg-gray-800/80 border-b border-gray-700">
          <div className="flex items-center gap-2">
            <IconMapPin size={15} className="text-sky-400" />
            <span className="text-white text-sm font-semibold">Live AQI Map — India</span>
            <span className="text-gray-500 text-xs ml-1">· {rankings.length} cities</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {[
              ['Good',                'bg-green-600'],
              ['Satisfactory',        'bg-lime-600'],
              ['Moderately Polluted', 'bg-yellow-600'],
              ['Poor',                'bg-orange-600'],
              ['Very Poor',           'bg-red-600'],
              ['Severe',              'bg-violet-600'],
            ].map(([l, c]) => (
              <span key={l} className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${c} text-white hidden sm:inline`}>
                {l}
              </span>
            ))}
          </div>
        </div>

        {/* Leaflet map */}
        <Suspense fallback={
          <div className="flex items-center justify-center bg-gray-900" style={{ height: '460px' }}>
            <div className="w-8 h-8 border-4 border-sky-500 border-t-transparent rounded-full animate-spin" />
          </div>
        }>
          <AQIMap cities={rankings} onSelect={pickCity} />
        </Suspense>

        {/* Selected city quick-info bar */}
        {selectedCity && (
          <div className="flex items-center justify-between px-4 py-2.5 bg-gray-800/60 border-t border-gray-700 text-sm flex-wrap gap-2">
            <div className="flex items-center gap-2 text-white font-semibold capitalize">
              <IconMapPin size={13} className="text-sky-400" />
              {selectedCity.city}
              <span className="text-gray-400 font-normal text-xs capitalize">· {selectedCity.state}</span>
            </div>
            <div className="flex items-center gap-3 text-xs text-gray-300">
              <span>AQI <span className="font-bold text-white">{Math.round(selectedCity.india_aqi ?? 0)}</span></span>
              {selectedCity.pm2_5_ugm3 != null && (
                <span>PM2.5 <span className="font-bold text-white">{selectedCity.pm2_5_ugm3.toFixed(1)} µg/m³</span></span>
              )}
              <AQIBadge category={selectedCity.india_aqi_category} />
              <button onClick={() => { setSelectedCity(null); setSearch('') }}
                className="text-gray-500 hover:text-gray-300 text-xs ml-2">✕ Clear</button>
            </div>
          </div>
        )}
      </div>

      {/* AQI scale + search row */}
      <div className="flex flex-wrap gap-2 items-center justify-between">
        <div className="flex flex-wrap gap-2 items-center">
          <span className="text-gray-500 text-xs mr-1">AQI Scale:</span>
          {[['Good','bg-green-600'],['Satisfactory','bg-lime-500'],['Moderately Polluted','bg-yellow-400 text-gray-900'],
            ['Poor','bg-orange-500'],['Very Poor','bg-red-600'],['Severe','bg-purple-700']].map(([l,c]) => (
            <span key={l} className={`text-xs px-2 py-0.5 rounded-full font-medium ${c} text-white`}>{l}</span>
          ))}
        </div>
      </div>

      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-gray-400 text-xs uppercase">
              {['#','City','State','India AQI','Category','PM2.5 µg/m³','Temp °C',''].map(h => (
                <th key={h} className="px-4 py-3 text-left last:text-center">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map(c => (
              <tr
                key={c.city}
                id={`city-row-${c.city}`}
                className={`border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors ${selectedCity?.city === c.city ? 'bg-sky-900/20' : ''}`}
              >
                <td className="px-4 py-3 text-gray-500 font-mono">{c.rank}</td>
                <td className="px-4 py-3 font-semibold text-white capitalize">{c.city}</td>
                <td className="px-4 py-3 text-gray-400 capitalize">{c.state}</td>
                <td className="px-4 py-3 font-bold text-white">{Math.round(c.india_aqi??0)}</td>
                <td className="px-4 py-3"><AQIBadge category={c.india_aqi_category} /></td>
                <td className="px-4 py-3 text-gray-300">{c.pm2_5_ugm3?.toFixed(1) ?? '—'}</td>
                <td className="px-4 py-3 text-gray-300">{c.temperature_c ? `${c.temperature_c.toFixed(1)}°` : '—'}</td>
                <td className="px-4 py-3 text-center">
                  <Link to="/forecast" className="inline-flex items-center gap-1 text-sky-400 hover:text-sky-300 text-xs">
                    Forecast <IconChevronRight size={13} />
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && <p className="text-center text-gray-500 py-8">No cities match.</p>}
      </div>
    </div>
  )
}
