/**
 * BreatheSafe — Browser-side OSRM routing utilities
 *
 * Calling OSRM directly from the user's browser sidesteps Render's
 * outbound-networking restrictions.  The computed geometries are then
 * POST-ed to /route/score for server-side AQI exposure scoring.
 *
 * Two public OSRM servers are tried in order:
 *   1. router.project-osrm.org  (official demo — primary)
 *   2. routing.openstreetmap.de (OSM community — fallback)
 */

// ── Internal profile / mode mappings ──────────────────────────────────────────
const PROFILE = { driving: 'driving', cycling: 'cycling', walking: 'foot' }
// openstreetmap.de uses different service-name prefixes
const OSM_MODE = { driving: 'car', cycling: 'bike', foot: 'foot' }

function _buildUrl(serverIdx, profile, coordStr, extraQs = '') {
  const qs = `overview=full&geometries=polyline${extraQs}`
  if (serverIdx === 0) {
    return `https://router.project-osrm.org/route/v1/${profile}/${coordStr}?${qs}`
  }
  const osmMode = OSM_MODE[profile] || 'car'
  return `https://routing.openstreetmap.de/routed-${osmMode}/route/v1/${profile}/${coordStr}?${qs}`
}

/** Fetch from OSRM, trying both servers.  Returns parsed JSON or null. */
async function _osrmGet(coordStr, profile, extraQs = '', timeoutMs = 20_000) {
  for (let i = 0; i < 2; i++) {
    const url = _buildUrl(i, profile, coordStr, extraQs)
    console.log(`[BreatheSafe OSRM] Trying server ${i + 1}: ${url.split('?')[0]}…`)
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), timeoutMs)
    try {
      const resp = await fetch(url, { signal: ctrl.signal })
      clearTimeout(timer)
      if (!resp.ok) {
        console.warn(`[BreatheSafe OSRM] Server ${i + 1} responded ${resp.status}`)
        continue
      }
      const data = await resp.json()
      if (data.code === 'Ok') {
        console.log(`[BreatheSafe OSRM] Server ${i + 1} succeeded — ${data.routes?.length} route(s)`)
        return data
      }
      console.warn(`[BreatheSafe OSRM] Server ${i + 1} returned code: ${data.code}`)
    } catch (err) {
      clearTimeout(timer)
      const reason = err?.name === 'AbortError' ? 'timeout' : err?.message
      console.warn(`[BreatheSafe OSRM] Server ${i + 1} failed: ${reason}`)
    }
  }
  return null
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Fetch up to maxAlt alternative routes between two points.
 * Returns an array of raw OSRM route objects (may be empty if both servers fail).
 */
export async function osrmFetchRoutes(
  srcLat, srcLon, dstLat, dstLon,
  mode = 'driving', maxAlt = 3,   // public OSRM servers cap alternatives at 3
) {
  const profile = PROFILE[mode] || 'driving'
  const coords  = `${srcLon},${srcLat};${dstLon},${dstLat}`
  const data    = await _osrmGet(coords, profile, `&alternatives=${maxAlt}`)
  return data ? data.routes : []
}

/**
 * Fetch a single route that passes through a via-point.
 * Returns the first OSRM route object, or null on failure.
 */
export async function osrmFetchVia(
  srcLat, srcLon,
  viaLat, viaLon,
  dstLat, dstLon,
  mode = 'driving',
) {
  const profile = PROFILE[mode] || 'driving'
  const coords  = `${srcLon},${srcLat};${viaLon},${viaLat};${dstLon},${dstLat}`
  const data    = await _osrmGet(coords, profile, '', 8_000)
  return data && data.routes?.length ? data.routes[0] : null
}

/**
 * Returns true when two OSRM routes are within `tol` (default 8%) of each
 * other in both distance and duration — used to deduplicate synthetic routes.
 */
export function routesSimilar(r1, r2, tol = 0.08) {
  const dRel = Math.abs(r1.distance - r2.distance) / Math.max(r1.distance, 1)
  const tRel = Math.abs(r1.duration - r2.duration) / Math.max(r1.duration, 1)
  return dRel < tol && tRel < tol
}

/**
 * Generate candidate via-points placed perpendicularly off the src→dst line.
 * Mirrors the Python implementation in route_engine.py.
 * Returns an array of [lat, lon] pairs ordered by increasing detour aggressiveness.
 */
export function perpendicularViaPoints(srcLat, srcLon, dstLat, dstLon) {
  function haversine(lat1, lon1, lat2, lon2) {
    const R    = 6371
    const dLat = (lat2 - lat1) * Math.PI / 180
    const dLon = (lon2 - lon1) * Math.PI / 180
    const a    = Math.sin(dLat / 2) ** 2
                 + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180)
                 * Math.sin(dLon / 2) ** 2
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
  }

  const routeDistKm = haversine(srcLat, srcLon, dstLat, dstLon)
  // Scale offset proportionally to route length so long-distance routes
  // (e.g. Delhi→Bengaluru, 2100 km) get via-points far enough apart to
  // land in genuinely different road corridors (NH44 vs NH48 etc.).
  // Cap raised from 60 km → 250 km; coefficient 0.12 → 0.15.
  const offsetKm = Math.max(8.0, Math.min(250.0, routeDistKm * 0.15))

  const dlat = dstLat - srcLat
  const dlon = dstLon - srcLon
  const mag  = Math.sqrt(dlat ** 2 + dlon ** 2)
  if (mag < 1e-9) return []

  const px = -dlon / mag   // perpendicular lat component
  const py =  dlat / mag   // perpendicular lon component

  const midLat = (srcLat + dstLat) / 2
  const latKm  = 111.0
  const lonKm  = 111.0 * Math.max(0.05, Math.cos(midLat * Math.PI / 180))

  // [fraction along route, side ±1, offset scale factor]
  // More candidates at varied fractions and scales → higher chance of
  // landing in a different highway corridor on long routes.
  const candidates = [
    [0.50, +1, 1.00],  // midpoint, left
    [0.50, -1, 1.00],  // midpoint, right
    [0.33, +1, 0.80],  // 1/3 point, left
    [0.67, -1, 0.80],  // 2/3 point, right
    [0.50, +1, 1.60],  // midpoint, further left
    [0.50, -1, 1.60],  // midpoint, further right
    [0.33, -1, 1.20],  // 1/3 point, right
    [0.67, +1, 1.20],  // 2/3 point, left
  ]

  return candidates.map(([t, sign, scale]) => {
    const ptLat = srcLat + t * dlat
    const ptLon = srcLon + t * dlon
    return [
      ptLat + sign * px * offsetKm * scale / latKm,
      ptLon + sign * py * offsetKm * scale / lonKm,
    ]
  })
}
