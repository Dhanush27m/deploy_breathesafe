"""
BreatheSafe — Route Engine
Pollution-aware route planning using OSRM (free, no key) + AQI lookup.

Strategy:
  1. Call OSRM for the primary route + up to 2 alternatives.
  2. Decode polyline geometry for each route.
  3. Sample waypoints at ~5 km intervals, find nearest city, read latest AQI.
  4. Score routes by (travel_time, avg_aqi_exposure).
  5. Return three route variants: fastest, clean, balanced.
"""

import math
from typing import List, Optional, Tuple

import httpx


# ── Haversine distance (km) ───────────────────────────────────────────────────
def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi       = math.radians(lat2 - lat1)
    dlam       = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Polyline decoder (Google / OSRM format) ───────────────────────────────────
def decode_polyline(encoded: str, precision: int = 5) -> List[Tuple[float, float]]:
    """Decode an encoded polyline string into (lat, lon) tuples."""
    coords, idx, lat, lng = [], 0, 0, 0
    factor = 10 ** precision
    while idx < len(encoded):
        for is_lng in (False, True):
            shift, result = 0, 0
            while True:
                b = ord(encoded[idx]) - 63
                idx += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if (result & 1) else (result >> 1)
            if is_lng:
                lng += delta
                coords.append((lat / factor, lng / factor))
            else:
                lat += delta
    return coords


# ── OSRM API call ─────────────────────────────────────────────────────────────
# ── OSRM endpoint registry ────────────────────────────────────────────────────
# Tried in order; first successful response wins.
# Primary: HTTPS on the official demo server (plain HTTP is blocked on Render).
# Fallback: OSM community OSRM server — separate infrastructure, same API.

_OSRM_SERVERS = [
    # (base_url_template, supports_alternatives)
    # {profile} = driving | cycling | foot
    ("https://router.project-osrm.org/route/v1/{profile}", True),
    # OSM community server uses a different path per travel mode
    ("https://routing.openstreetmap.de/routed-{osm_mode}/route/v1/{profile}", True),
]

# OSM community server uses different service names per mode
_OSM_MODE = {"driving": "car", "cycling": "bike", "foot": "foot"}


def _travel_mode_to_osrm(mode: str) -> str:
    return {"driving": "driving", "cycling": "cycling", "walking": "foot"}.get(mode, "driving")


def _build_osrm_url(template: str, profile: str, coords: str,
                     extra_qs: str = "") -> str:
    """Fill in a server template and append the coordinate string + query params."""
    osm_mode = _OSM_MODE.get(profile, "car")
    base = template.format(profile=profile, osm_mode=osm_mode)
    return f"{base}/{coords}?overview=full&geometries=polyline{extra_qs}"


def _osrm_get(coords: str, profile: str, extra_qs: str = "",
              timeout: float = 12.0) -> Optional[dict]:
    """
    Try each OSRM server in sequence.
    Returns the parsed JSON response on the first success, or None if all fail.
    """
    for template, _ in _OSRM_SERVERS:
        url = _build_osrm_url(template, profile, coords, extra_qs)
        try:
            resp = httpx.get(url, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == "Ok":
                return data
        except Exception:
            continue   # try next server
    return None


def fetch_osrm_routes(
    src_lat: float, src_lon: float,
    dst_lat: float, dst_lon: float,
    travel_mode: str = "driving",
    max_alternatives: int = 3,
) -> List[dict]:
    """
    Call OSRM (with server fallback) and return raw route objects.
    Each route has: distance (m), duration (s), geometry (encoded polyline).
    Returns empty list when all servers fail.
    Requests up to max_alternatives alternative routes in addition to the primary.
    """
    profile = _travel_mode_to_osrm(travel_mode)
    coords  = f"{src_lon},{src_lat};{dst_lon},{dst_lat}"
    data    = _osrm_get(coords, profile, f"&alternatives={max_alternatives}")
    if data:
        return data.get("routes", [])
    return []


def fetch_osrm_route_via(
    src_lat: float, src_lon: float,
    via_lat: float, via_lon: float,
    dst_lat: float, dst_lon: float,
    travel_mode: str = "driving",
) -> Optional[dict]:
    """
    Fetch a single OSRM route that passes through a specific via-waypoint.
    Returns the raw OSRM route dict, or None when all servers fail.
    """
    profile = _travel_mode_to_osrm(travel_mode)
    coords  = f"{src_lon},{src_lat};{via_lon},{via_lat};{dst_lon},{dst_lat}"
    data    = _osrm_get(coords, profile, timeout=8.0)
    if data and data.get("routes"):
        return data["routes"][0]
    return None


def routes_are_similar(
    dist1_m: float, dur1_s: float,
    dist2_m: float, dur2_s: float,
    tol: float = 0.08,
) -> bool:
    """
    Return True when two routes have both distance AND duration within tol (8%) of each other.
    Used to deduplicate synthetic via-routes that snap to the same road.
    """
    d_rel = abs(dist1_m - dist2_m) / max(dist1_m, 1.0)
    t_rel = abs(dur1_s  - dur2_s)  / max(dur1_s,  1.0)
    return d_rel < tol and t_rel < tol


def perpendicular_via_points(
    src_lat: float, src_lon: float,
    dst_lat: float, dst_lon: float,
) -> List[Tuple[float, float]]:
    """
    Generate candidate via-points placed perpendicularly off the src→dst line.
    Uses multiple offsets and positions along the route to maximise the chance
    of finding genuinely distinct road corridors.

    Returns a list of (via_lat, via_lon) tuples ordered by increasing detour aggressiveness.
    """
    route_dist_km = haversine(src_lat, src_lon, dst_lat, dst_lon)
    # Scale offset proportionally so long routes (e.g. Delhi→Bengaluru, 2100 km)
    # get via-points far enough to land in genuinely different highway corridors.
    # Cap raised from 60 km → 250 km; coefficient 0.12 → 0.15.
    offset_km = max(8.0, min(250.0, route_dist_km * 0.15))

    dlat = dst_lat - src_lat
    dlon = dst_lon - src_lon
    mag  = math.sqrt(dlat ** 2 + dlon ** 2)
    if mag < 1e-9:
        return []

    # Perpendicular unit vector in degree-space
    px = -dlon / mag   # perpendicular lat component
    py =  dlat / mag   # perpendicular lon component

    mid_lat = (src_lat + dst_lat) / 2
    lat_km  = 111.0
    lon_km  = 111.0 * max(0.05, math.cos(math.radians(mid_lat)))

    # (fraction along route, side ±1, offset scale factor)
    # More candidates at varied fractions and scales → higher chance of
    # landing in a different highway corridor on long inter-city routes.
    candidates = [
        (0.50, +1, 1.00),   # midpoint, left
        (0.50, -1, 1.00),   # midpoint, right
        (0.33, +1, 0.80),   # 1/3 point, left
        (0.67, -1, 0.80),   # 2/3 point, right
        (0.50, +1, 1.60),   # midpoint, further left
        (0.50, -1, 1.60),   # midpoint, further right
        (0.33, -1, 1.20),   # 1/3 point, right
        (0.67, +1, 1.20),   # 2/3 point, left
    ]
    vias: List[Tuple[float, float]] = []
    for t, sign, scale in candidates:
        pt_lat = src_lat + t * dlat
        pt_lon = src_lon + t * dlon
        via_lat = pt_lat + sign * px * offset_km * scale / lat_km
        via_lon = pt_lon + sign * py * offset_km * scale / lon_km
        vias.append((via_lat, via_lon))

    return vias


def via_direction_label(
    src_lat: float, src_lon: float,
    dst_lat: float, dst_lon: float,
    via_lat: float, via_lon: float,
) -> str:
    """Return a human-readable direction label (e.g. 'Northern Route') for a via-point."""
    mid_lat = (src_lat + dst_lat) / 2
    mid_lon = (src_lon + dst_lon) / 2
    dlat = via_lat - mid_lat
    dlon = via_lon - mid_lon
    if abs(dlat) >= abs(dlon):
        direction = "Northern" if dlat > 0 else "Southern"
    else:
        direction = "Eastern" if dlon > 0 else "Western"
    return f"{direction} Route"


# ── AQI sampling along a route ────────────────────────────────────────────────
def sample_aqi_along_route(
    waypoints: List[Tuple[float, float]],
    city_aqi_map: dict,          # {city_name: (lat, lon, aqi)}
) -> float:
    """
    For each sampled waypoint, find the nearest city and return its AQI.
    Returns the mean AQI across all sampled points.
    """
    if not city_aqi_map or not waypoints:
        return 0.0

    cities = list(city_aqi_map.values())   # list of (lat, lon, aqi)
    aqi_sum, count = 0.0, 0

    # Sample at most every 10th waypoint (or all if fewer than 30 total)
    step = max(1, len(waypoints) // 30)
    sample = waypoints[::step]

    for wlat, wlon in sample:
        nearest = min(cities, key=lambda c: haversine(wlat, wlon, c[0], c[1]))
        aqi_sum += nearest[2]
        count   += 1

    return aqi_sum / count if count else 0.0


# ── Route scoring and classification ─────────────────────────────────────────
def score_routes(routes_with_aqi: List[dict]) -> dict:
    """
    Given a list of {duration_s, distance_m, avg_aqi, waypoints, _idx},
    classify them into fastest / clean / balanced.

    Each input route must have a unique '_idx' so the caller can detect
    when two categories map to the same underlying OSRM route.

    Returns dict: {fastest: ..., clean: ..., balanced: ...}
    """
    if not routes_with_aqi:
        return {}

    # Normalize time and AQI to [0, 1] for scoring
    times = [r["duration_s"] for r in routes_with_aqi]
    aqis  = [r["avg_aqi"]    for r in routes_with_aqi]

    t_min, t_max = min(times), max(times)
    a_min, a_max = min(aqis),  max(aqis)

    def norm_t(t):
        return (t - t_min) / (t_max - t_min) if t_max > t_min else 0.0

    def norm_a(a):
        return (a - a_min) / (a_max - a_min) if a_max > a_min else 0.0

    fastest_route  = min(routes_with_aqi, key=lambda r: r["duration_s"])
    clean_route    = min(routes_with_aqi, key=lambda r: r["avg_aqi"])
    def balanced_score(r):
        return 0.4 * norm_t(r["duration_s"]) + 0.6 * norm_a(r["avg_aqi"])

    balanced_route = min(routes_with_aqi, key=balanced_score)

    return {
        "fastest":  fastest_route,
        "clean":    clean_route,
        "balanced": balanced_route,
    }


# ── Exposure reduction % ──────────────────────────────────────────────────────
def exposure_reduction(clean_aqi: float, fastest_aqi: float) -> Optional[float]:
    if fastest_aqi and fastest_aqi > 0:
        return round((fastest_aqi - clean_aqi) / fastest_aqi * 100, 1)
    return None


# ── Build explanation string ──────────────────────────────────────────────────
def build_explanation(route_type: str, dist_km: float, time_min: float,
                       avg_aqi: float, reduction: Optional[float]) -> str:
    from app.ml.predictor import aqi_category
    cat = aqi_category(avg_aqi)
    base = (f"{route_type.capitalize()} route: {dist_km:.1f} km, "
            f"~{time_min:.0f} min. Avg AQI exposure {avg_aqi:.0f} ({cat}).")
    if route_type == "clean" and reduction and reduction > 0:
        base += f" {reduction:.0f}% less pollution exposure than the fastest route."
    elif route_type == "balanced":
        base += " Optimised balance of travel time and air quality."
    return base
