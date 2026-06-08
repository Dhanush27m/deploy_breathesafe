/**
 * PlaceSearch — Geocoding input using Nominatim (free, no API key)
 *
 * Props:
 *   value       : { name, lat, lon } — controlled value
 *   onChange    : fn({ name, lat, lon }) — called when a place is confirmed
 *   placeholder : input placeholder string
 *   accentClass : Tailwind text colour class for the icon (e.g. 'text-sky-400')
 *   icon        : JSX icon element
 *   required    : bool
 */

import { useState, useRef, useEffect, useCallback } from 'react'

const NOMINATIM = 'https://nominatim.openstreetmap.org/search'

// India's approximate bounding box (lon_min, lat_min, lon_max, lat_max)
const INDIA_VIEWBOX = '68.1,6.5,97.5,37.4'

// Debounce helper
function useDebounce(fn, delay) {
  const timer = useRef(null)
  return useCallback((...args) => {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => fn(...args), delay)
  }, [fn, delay])
}

export default function PlaceSearch({
  value       = { name: '', lat: null, lon: null },
  onChange,
  placeholder = 'Enter place',
  accentClass = 'text-sky-400',
  icon        = null,
  required    = false,
}) {
  const [query,       setQuery]       = useState(value.name || '')
  const [suggestions, setSuggestions] = useState([])
  const [open,        setOpen]        = useState(false)
  const [fetching,    setFetching]    = useState(false)
  const [activeIdx,   setActiveIdx]   = useState(-1)
  const [confirmed,   setConfirmed]   = useState(!!value.lat)  // is a place locked in?

  const containerRef = useRef(null)

  // Sync if parent resets value (e.g. preset fill)
  useEffect(() => {
    setQuery(value.name || '')
    setConfirmed(!!value.lat)
  }, [value.name, value.lat])

  // Close on outside click
  useEffect(() => {
    function handler(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Nominatim search — restricted to India only
  const searchNominatim = useCallback(async (q) => {
    if (q.trim().length < 2) { setSuggestions([]); return }
    setFetching(true)
    try {
      const params = new URLSearchParams({
        q,
        format:         'json',
        limit:          10,           // fetch more so we have buffer after filtering
        countrycodes:   'in',         // hard-filter to India
        viewbox:        INDIA_VIEWBOX, // India bounding box
        bounded:        1,            // strictly restrict to bounding box
        addressdetails: 1,
      })
      const res  = await fetch(`${NOMINATIM}?${params}`, {
        headers: { 'Accept-Language': 'en' },
      })
      const data = await res.json()

      // Post-fetch guard: keep only results confirmed to be in India
      const indiaOnly = data.filter(item => {
        const cc = item.address?.country_code?.toLowerCase()
        if (cc) return cc === 'in'
        // Fallback: display_name must end with "India"
        return item.display_name?.trim().endsWith('India')
      })

      setSuggestions(
        indiaOnly.slice(0, 6).map(item => {
          // Build a concise label: "City, State" or "Place, District, State"
          const addr  = item.address || {}
          const city  = addr.city || addr.town || addr.village || addr.county
                        || item.name || item.display_name.split(',')[0]
          const state = addr.state || ''
          const district = addr.state_district || ''
          const sub   = [district, state].filter(Boolean).join(', ')
          return {
            display: item.display_name,
            short:   city.trim(),
            sub,                       // state/district line shown below name
            lat:     parseFloat(item.lat),
            lon:     parseFloat(item.lon),
            type:    item.type,
            class:   item.class,
          }
        })
      )
      setOpen(true)
      setActiveIdx(-1)
    } catch {
      setSuggestions([])
    } finally {
      setFetching(false)
    }
  }, [])

  const debouncedSearch = useDebounce(searchNominatim, 350)

  const handleInput = (e) => {
    const val = e.target.value
    setQuery(val)
    setConfirmed(false)
    onChange({ name: val, lat: null, lon: null })   // mark as unresolved
    debouncedSearch(val)
  }

  const pick = (s) => {
    const name = s.short
    setQuery(name)
    setSuggestions([])
    setOpen(false)
    setConfirmed(true)
    setActiveIdx(-1)
    onChange({ name, lat: s.lat, lon: s.lon })
  }

  const clear = () => {
    setQuery('')
    setConfirmed(false)
    setSuggestions([])
    setOpen(false)
    onChange({ name: '', lat: null, lon: null })
  }

  const handleKeyDown = (e) => {
    if (!open || suggestions.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx(i => Math.min(i + 1, suggestions.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (activeIdx >= 0) pick(suggestions[activeIdx])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <div className="relative">
        {/* Icon */}
        {icon && (
          <span className={`absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none ${accentClass}`}>
            {icon}
          </span>
        )}

        {/* Input */}
        <input
          type="text"
          value={query}
          placeholder={placeholder}
          onChange={handleInput}
          onFocus={() => { if (suggestions.length) setOpen(true) }}
          onKeyDown={handleKeyDown}
          autoComplete="off"
          required={required && !confirmed}
          className={`input-field w-full ${icon ? 'pl-9' : ''} pr-8 ${
            confirmed ? 'border-green-700 bg-green-900/10' : ''
          }`}
        />

        {/* Right indicator: spinner, tick, or clear */}
        <div className="absolute right-2.5 top-1/2 -translate-y-1/2">
          {fetching ? (
            <div className="w-3.5 h-3.5 border-2 border-sky-500 border-t-transparent rounded-full animate-spin" />
          ) : confirmed ? (
            <button
              type="button"
              onClick={clear}
              title="Clear"
              className="text-gray-500 hover:text-gray-300 text-base leading-none"
            >×</button>
          ) : null}
        </div>
      </div>

      {/* Hidden input to force HTML required validation when lat is missing */}
      {required && (
        <input
          type="text"
          value={confirmed ? 'ok' : ''}
          required
          readOnly
          tabIndex={-1}
          className="sr-only"
          aria-hidden="true"
        />
      )}

      {/* Dropdown */}
      {open && suggestions.length > 0 && (
        <div className="absolute z-50 top-full mt-1 w-full bg-gray-900 border border-gray-700 rounded-xl shadow-2xl overflow-hidden">
          {suggestions.map((s, i) => (
            <button
              key={i}
              type="button"
              onMouseDown={e => { e.preventDefault(); pick(s) }}
              onMouseEnter={() => setActiveIdx(i)}
              className={`w-full text-left px-3 py-2.5 transition-colors ${
                i === activeIdx ? 'bg-gray-800' : 'hover:bg-gray-800/60'
              } ${i < suggestions.length - 1 ? 'border-b border-gray-800' : ''}`}
            >
              <div className="text-sm text-white font-medium truncate">{s.short}</div>
              {s.sub && (
                <div className="text-xs text-gray-500 truncate mt-0.5">{s.sub}</div>
              )}
            </button>
          ))}
        </div>
      )}

      {/* No results */}
      {open && !fetching && query.trim().length >= 2 && suggestions.length === 0 && (
        <div className="absolute z-50 top-full mt-1 w-full bg-gray-900 border border-gray-700 rounded-xl shadow-xl px-4 py-3 text-sm text-gray-500">
          No places found for "{query}"
        </div>
      )}
    </div>
  )
}
