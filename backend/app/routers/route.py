"""
BreatheSafe — Route Planning Router (Phase 6 + 7)

Endpoints:
  POST /route/suggest        — get fastest / clean / balanced routes with AQI exposure
  POST /route/save           — explicitly save a route with planned travel window + health check
  DELETE /route/{id}         — delete a saved route (cancel journey)
  GET  /route/history        — past route queries for the authenticated user
"""

import logging
import time as _time
from datetime import datetime, timedelta
from typing import List, Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.city import City
from app.models.aqi_data import AQIData
from app.models.monitoring_station import MonitoringStation
from app.models.route import Route, RouteTypeEnum, TravelModeEnum
from app.models.user import User
from app.schemas.route import RouteRequest, RouteSaveRequest, RouteScoreRequest
from app.services.route_engine import (
    fetch_osrm_routes, fetch_osrm_route_via,
    routes_are_similar, perpendicular_via_points, via_direction_label,
    decode_polyline, sample_aqi_along_route,
    score_routes, exposure_reduction, build_explanation, haversine,
)

router = APIRouter()

_bearer = HTTPBearer(auto_error=False)

# ── V3: ML forecast cache ──────────────────────────────────────────────────────
# {(city_name, date_str, hour): {"aqi": float|None, "ts": float}}
_ML_CITY_FORECAST_CACHE: dict = {}
_ML_FORECAST_CACHE_TTL = 3600   # 1 hour — forecasts don't change quickly


def _get_city_recent_df(city_name: str, db: Session):
    """
    Fetch last 14 days of AQI + weather data for a DB city.
    Returns a pandas DataFrame with columns: datetime, india_aqi, temperature_c,
    wind_speed_kmh, humidity_percent, pressure_msl_hpa, wind_gusts_kmh,
    precipitation_mm, is_raining — or None if no data exists.
    """
    import pandas as pd

    cutoff = datetime.utcnow() - timedelta(days=14)

    rows = (
        db.query(AQIData)
        .join(MonitoringStation, AQIData.station_id == MonitoringStation.id)
        .join(City, MonitoringStation.city_id == City.id)
        .filter(City.name == city_name)
        .filter(AQIData.datetime >= cutoff)
        .order_by(AQIData.datetime)
        .all()
    )

    if not rows:
        return None

    records = [{
        "datetime":          r.datetime,
        "india_aqi":         float(r.india_aqi) if r.india_aqi is not None else 100.0,
        "temperature_c":     float(r.temperature_c)    if r.temperature_c    is not None else 20.0,
        "wind_speed_kmh":    float(r.wind_speed_kmh)   if r.wind_speed_kmh   is not None else  5.0,
        "humidity_percent":  float(r.humidity_percent) if r.humidity_percent is not None else 60.0,
        "pressure_msl_hpa":  float(r.pressure_msl_hpa) if r.pressure_msl_hpa is not None else 1013.0,
        "wind_gusts_kmh":    float(r.wind_gusts_kmh)   if r.wind_gusts_kmh   is not None else  8.0,
        "precipitation_mm":  float(r.precipitation_mm) if r.precipitation_mm is not None else  0.0,
        "is_raining":        bool(r.is_raining)         if r.is_raining       is not None else False,
    } for r in rows]

    df = pd.DataFrame(records)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df


def _get_ml_forecast_aqi(city_name: str, target_dt: datetime, db: Session):
    """
    Return XGBoost-predicted India AQI for a DB city at a specific future hour.

    Workflow:
      1. Fetch last 14 days of DB readings for the city.
      2. Run _xgb_predict_horizon() up to target_dt.
      3. Return the hourly prediction matching target_dt's date + hour.

    Results cached per (city, date, hour) with a 1-hour TTL so repeated route
    requests for the same journey don't re-run inference.

    Returns None if:
      • ML models not trained for this city
      • target_dt is more than 7 days in the future
      • Fewer than 24 h of DB history available
    """
    from app.ml.predictor import _load_models, _xgb_predict_horizon, models_available

    # Check if within forecastable range (0 min → 7 days ahead)
    now_ist   = datetime.utcnow() + timedelta(hours=5, minutes=30)
    tgt_naive = target_dt.replace(tzinfo=None) if getattr(target_dt, "tzinfo", None) else target_dt
    delta_h   = (tgt_naive - now_ist).total_seconds() / 3600

    if delta_h < 0 or delta_h > 168:
        return None

    if not models_available(city_name):
        return None

    date_str  = tgt_naive.strftime("%Y-%m-%d")
    cache_key = (city_name, date_str, tgt_naive.hour)
    entry     = _ML_CITY_FORECAST_CACHE.get(cache_key)
    if entry and (_time.time() - entry["ts"] < _ML_FORECAST_CACHE_TTL):
        return entry["aqi"]

    try:
        recent_df = _get_city_recent_df(city_name, db)
        if recent_df is None or len(recent_df) < 24:
            return None

        last_dt   = recent_df["datetime"].max()
        if getattr(last_dt, "tzinfo", None):
            last_dt = last_dt.replace(tzinfo=None)

        horizon_h = max(1, int((tgt_naive - last_dt).total_seconds() / 3600) + 1)
        if horizon_h > 168:
            return None

        models  = _load_models(city_name)
        hourly  = _xgb_predict_horizon(city_name, models, recent_df, horizon_h)

        aqi = None
        for pred in hourly:
            pdt = pred["datetime"]
            if pdt.date() == tgt_naive.date() and pdt.hour == tgt_naive.hour:
                aqi = round(float(pred["aqi"]), 1)
                break

        _ML_CITY_FORECAST_CACHE[cache_key] = {"aqi": aqi, "ts": _time.time()}
        return aqi

    except Exception as exc:
        logger.warning("_get_ml_forecast_aqi(%s, %s) failed: %s", city_name, target_dt, exc)
        return None


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Returns authenticated user if a valid JWT is present, otherwise None."""
    if credentials is None:
        return None
    from app.core.security import decode_token
    payload = decode_token(credentials.credentials)
    if not payload:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    return db.query(User).filter(User.id == int(user_id)).first()


# ── Helper: build city → (lat, lon, latest_aqi) map ──────────────────────────
def _build_city_aqi_map(db: Session) -> dict:
    """
    Return dict {station_name: (lat, lon, aqi)} for AQI sampling along routes.

    V2: merges ALL active Indian CPCB stations (~200+) from the live OpenAQ cache
    with our 29 DB cities (DB values take priority for those cities).
    Falls back to DB-only if the live cache is unavailable.
    """
    from sqlalchemy import func

    # ── DB data (29 cities, most accurate) ───────────────────────────────────
    latest_sub = (
        db.query(
            AQIData.station_id,
            func.max(AQIData.datetime).label("max_dt"),
        )
        .group_by(AQIData.station_id)
        .subquery()
    )

    rows = (
        db.query(AQIData, City)
        .join(MonitoringStation, AQIData.station_id == MonitoringStation.id)
        .join(City, MonitoringStation.city_id == City.id)
        .join(
            latest_sub,
            (AQIData.station_id == latest_sub.c.station_id)
            & (AQIData.datetime == latest_sub.c.max_dt),
        )
        .all()
    )

    city_map: dict = {
        city.name: (city.latitude, city.longitude, aqi.india_aqi or 100.0)
        for aqi, city in rows
    }

    # ── V2: Augment with all-India OpenAQ stations ────────────────────────────
    try:
        from app.services.data_pipeline import get_all_india_live
        live_stations = get_all_india_live()
        for s in live_stations:
            if s.get("source") == "openaq" and s.get("india_aqi") is not None:
                key = s.get("station_name") or s.get("name") or ""
                if key and key not in city_map:
                    city_map[key] = (
                        s["latitude"],
                        s["longitude"],
                        float(s["india_aqi"]),
                    )
    except Exception as e:
        logger.warning("_build_city_aqi_map: OpenAQ augment failed: %s", e)

    return city_map


# ── Helper: convert OSRM route → internal dict ───────────────────────────────
def _process_osrm_route(osrm_r: dict, city_aqi_map: dict) -> dict:
    duration_s = osrm_r.get("duration", 0)
    distance_m = osrm_r.get("distance", 0)
    geometry   = osrm_r.get("geometry", "")

    waypoints = decode_polyline(geometry) if geometry else []
    avg_aqi   = sample_aqi_along_route(waypoints, city_aqi_map)

    result = {
        "duration_s":  duration_s,
        "distance_m":  distance_m,
        "distance_km": round(distance_m / 1000, 2),
        "time_min":    round(duration_s / 60, 1),
        "avg_aqi":     round(avg_aqi, 1),
        "waypoints":   waypoints,
        "geometry":    geometry,
    }
    # Carry forward any _via_* metadata set during synthetic route generation
    for k, v in osrm_r.items():
        if k.startswith("_via_"):
            result[k] = v
    return result


# ── Helper: nearest city name ─────────────────────────────────────────────────
def _nearest_city_name(lat: float, lon: float, db: Session) -> str:
    cities = db.query(City).all()
    if not cities:
        return f"{lat:.3f},{lon:.3f}"
    nearest = min(cities, key=lambda c: haversine(lat, lon, c.latitude, c.longitude))
    return nearest.name


# ── Helper: nearest city object ───────────────────────────────────────────────
def _nearest_city(lat: float, lon: float, db: Session) -> Optional[City]:
    cities = db.query(City).all()
    if not cities:
        return None
    return min(cities, key=lambda c: haversine(lat, lon, c.latitude, c.longitude))


# ── Shared: score a pool of processed routes into fastest/clean/balanced ──────
def _score_and_build_response(
    processed: list,
    payload_source_lat: float, payload_source_lon: float,
    payload_dest_lat: float,   payload_dest_lon: float,
    payload_via_lat: Optional[float], payload_via_lon: Optional[float],
    payload_via_name: Optional[str],
    source_name: str, dest_name: str, travel_mode: str,
):
    """
    Convert a list of processed route dicts into the full suggest/score response.
    Returns either:
      • needs_via_selection=True with via_options (when pool > 3 and no via chosen)
      • needs_via_selection=False with fastest/clean/balanced route cards
    """
    # If pool > 3 and no via → offer corridor picker
    if len(processed) > 3 and payload_via_lat is None:
        via_options = []
        seen_labels: set = set()
        for p in processed:
            vl = p.get("_via_lat")
            vv = p.get("_via_lon")
            if vl is None and p["waypoints"]:
                mid = p["waypoints"][len(p["waypoints"]) // 2]
                vl, vv = mid[0], mid[1]
            if vl is None:
                continue
            base = via_direction_label(
                payload_source_lat, payload_source_lon,
                payload_dest_lat,   payload_dest_lon,
                vl, vv,
            )
            label, suffix = base, 1
            while label in seen_labels:
                suffix += 1
                label = f"{base} {suffix}"
            seen_labels.add(label)
            wpts = p["waypoints"]
            step = max(1, len(wpts) // 50)
            preview = [[lat, lon] for lat, lon in wpts[::step]]
            via_options.append({
                "via_lat":           vl,
                "via_lon":           vv,
                "label":             label,
                "distance_km":       p["distance_km"],
                "time_min":          p["time_min"],
                "avg_aqi":           round(p["avg_aqi"], 1),
                "preview_waypoints": preview,
            })
        return {
            "source":              source_name,
            "destination":         dest_name,
            "source_lat":          payload_source_lat,
            "source_lon":          payload_source_lon,
            "dest_lat":            payload_dest_lat,
            "dest_lon":            payload_dest_lon,
            "generated_at":        datetime.utcnow().isoformat(),
            "travel_mode":         travel_mode,
            "needs_via_selection": True,
            "via_options":         via_options,
            "routes":              [],
            "has_alternatives":    True,
            "single_path":         False,
            "tip":                 "",
            "via_label":           None,
        }

    # Score and build route cards
    scored = score_routes(processed)
    if not scored:
        raise HTTPException(status_code=503, detail="Route scoring failed.")

    fastest_aqi = scored["fastest"]["avg_aqi"]
    via_label: Optional[str] = None
    if payload_via_lat is not None and payload_via_lon is not None:
        via_label = payload_via_name or via_direction_label(
            payload_source_lat, payload_source_lon,
            payload_dest_lat,   payload_dest_lon,
            payload_via_lat,    payload_via_lon,
        )

    output_routes = []
    for rtype, route_data in scored.items():
        reduction = (exposure_reduction(route_data["avg_aqi"], fastest_aqi)
                     if rtype != "fastest" else None)
        expl = build_explanation(
            rtype, route_data["distance_km"],
            route_data["time_min"], route_data["avg_aqi"], reduction,
        )
        wpts = route_data["waypoints"]
        step = max(1, len(wpts) // 200)
        map_waypoints = [[lat, lon] for lat, lon in wpts[::step]]
        if wpts and [wpts[-1][0], wpts[-1][1]] != map_waypoints[-1]:
            map_waypoints.append([wpts[-1][0], wpts[-1][1]])
        output_routes.append({
            "route_type":             rtype,
            "travel_mode":            travel_mode,
            "distance_km":            route_data["distance_km"],
            "time_min":               route_data["time_min"],
            "avg_aqi_exposure":       route_data["avg_aqi"],
            "exposure_reduction_pct": reduction,
            "explanation":            expl,
            "waypoints":              map_waypoints,
            "route_idx":              route_data.get("_idx", 0),
        })

    unique_idxs = {r["route_idx"] for r in output_routes}
    single_path = len(unique_idxs) == 1
    tip = (
        "All three route types follow the same road — "
        "no distinct alternative paths were found for this journey."
        if single_path else
        "The 'clean' route minimises your AQI exposure. "
        "The 'balanced' route offers the best time-vs-pollution trade-off."
    )

    return {
        "source":              source_name,
        "destination":         dest_name,
        "source_lat":          payload_source_lat,
        "source_lon":          payload_source_lon,
        "dest_lat":            payload_dest_lat,
        "dest_lon":            payload_dest_lon,
        "generated_at":        datetime.utcnow().isoformat(),
        "travel_mode":         travel_mode,
        "has_alternatives":    len(processed) > 1,
        "single_path":         single_path,
        "needs_via_selection": False,
        "via_options":         [],
        "via_label":           via_label,
        "routes":              output_routes,
        "tip":                 tip,
    }


# ── 1a. Score pre-fetched OSRM routes (browser sends geometries) ───────────────
@router.post("/score", response_model=dict)
async def score_browser_routes(
    payload: RouteScoreRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """
    Accept OSRM route geometries fetched by the user's browser and score them
    by AQI exposure.  Returns the same response shape as POST /route/suggest so
    the frontend can use either endpoint interchangeably.

    This endpoint is the primary routing path in production (Render blocks
    outbound connections to OSRM servers, but the user's browser can reach them
    directly).
    """
    if not payload.osrm_routes:
        raise HTTPException(status_code=400, detail="osrm_routes must not be empty.")

    city_aqi_map = _build_city_aqi_map(db)
    if not city_aqi_map:
        raise HTTPException(status_code=503, detail="No AQI data available.")

    # ── V3: Apply time-aware AQI forecasts when journey is in the future ──────
    aqi_source    = "live"
    forecast_for  = None
    planned_start = payload.planned_start

    if planned_start is not None:
        now_ist   = datetime.utcnow() + timedelta(hours=5, minutes=30)
        tgt_naive = (planned_start.replace(tzinfo=None)
                     if getattr(planned_start, "tzinfo", None) else planned_start)
        delta_min = (tgt_naive - now_ist).total_seconds() / 60

        if delta_min > 30:
            # Journey is meaningfully in the future — override AQI with forecasts
            aqi_source   = "forecast"
            forecast_for = tgt_naive.isoformat()

            # Collect a representative sample of waypoints from ALL routes
            # (used to determine which stations are near the route)
            all_waypoints: list = []
            for r in payload.osrm_routes:
                if r.geometry:
                    wpts = decode_polyline(r.geometry)
                    # Sample ~30 evenly-spaced points per route for proximity checks
                    step = max(1, len(wpts) // 30)
                    all_waypoints.extend(wpts[::step])

            # Collect DB city names for quick lookup
            db_city_names: set = {c.name for c in db.query(City).all()}

            # Import CAMS function from data_pipeline
            from app.services.data_pipeline import get_cams_forecast_aqi

            # For each station in the AQI map, check if it's within 150 km of
            # any route waypoint.  If so, override with forecast AQI.
            overrides: dict = {}
            for station_key, (slat, slon, current_aqi) in city_aqi_map.items():
                near = any(
                    haversine(slat, slon, wlat, wlon) < 150.0
                    for wlat, wlon in all_waypoints
                )
                if not near:
                    continue

                if station_key in db_city_names:
                    # DB city → use XGBoost ML forecast
                    ml_aqi = _get_ml_forecast_aqi(station_key, tgt_naive, db)
                    if ml_aqi is not None:
                        overrides[station_key] = (slat, slon, ml_aqi)
                        logger.debug(
                            "V3 ML forecast  city=%-20s  live=%-5.0f  → forecast=%.0f",
                            station_key, current_aqi, ml_aqi,
                        )
                else:
                    # OpenAQ station → use CAMS forecast
                    cams_aqi = get_cams_forecast_aqi(slat, slon, tgt_naive)
                    if cams_aqi is not None:
                        overrides[station_key] = (slat, slon, cams_aqi)

            city_aqi_map.update(overrides)
            logger.info(
                "V3 forecast overrides applied: %d stations overridden for %s",
                len(overrides), tgt_naive.strftime("%Y-%m-%d %H:%M"),
            )

    travel_mode = payload.travel_mode.value
    source_name = payload.source_name or _nearest_city_name(
        payload.source_lat, payload.source_lon, db)
    dest_name   = payload.dest_name   or _nearest_city_name(
        payload.dest_lat,   payload.dest_lon,   db)

    # Build processed route list from browser-supplied geometries
    processed = []
    for idx, r in enumerate(payload.osrm_routes):
        waypoints = decode_polyline(r.geometry) if r.geometry else []
        avg_aqi   = sample_aqi_along_route(waypoints, city_aqi_map)
        p = {
            "_idx":        idx,
            "duration_s":  r.duration_s,
            "distance_m":  r.distance_m,
            "distance_km": round(r.distance_m / 1000, 2),
            "time_min":    round(r.duration_s / 60, 1),
            "avg_aqi":     round(avg_aqi, 1),
            "waypoints":   waypoints,
            "geometry":    r.geometry,
        }
        if r.via_lat is not None:
            p["_via_lat"] = r.via_lat
        if r.via_lon is not None:
            p["_via_lon"] = r.via_lon
        processed.append(p)

    response = _score_and_build_response(
        processed,
        payload.source_lat, payload.source_lon,
        payload.dest_lat,   payload.dest_lon,
        payload.via_lat,    payload.via_lon,
        payload.via_name,
        source_name, dest_name, travel_mode,
    )

    # V3: annotate response so the frontend can show "Forecast" vs "Live" label
    response["aqi_source"]   = aqi_source
    response["forecast_for"] = forecast_for   # ISO string or None
    return response


# ── 1. Suggest routes ──────────────────────────────────────────────────────────
@router.post("/suggest", response_model=dict)
async def suggest_routes(
    payload: RouteRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """
    Return fastest / clean / balanced route options with AQI exposure scores.

    Flow:
      1. If via_lat/via_lon supplied → route specifically through that waypoint,
         supplement with any natural OSRM alternatives, then score fastest/clean/balanced.
      2. Otherwise → request up to 5 OSRM alternatives.  If fewer than 3 distinct
         routes come back, generate synthetic alternatives by routing through
         perpendicular via-points offset from the direct line.
      3. If the resulting pool exceeds 3 routes → return needs_via_selection=True
         with via_options so the frontend shows a corridor-picker modal.
      4. Otherwise → score the pool into fastest / clean / balanced and return cards.

    Routes are NOT auto-saved here; use POST /route/save to explicitly save one.
    """
    city_aqi_map = _build_city_aqi_map(db)
    if not city_aqi_map:
        raise HTTPException(status_code=503, detail="No AQI data available.")

    travel_mode = payload.travel_mode.value
    source_name = payload.source_name or _nearest_city_name(
        payload.source_lat, payload.source_lon, db)
    dest_name   = payload.dest_name   or _nearest_city_name(
        payload.dest_lat,   payload.dest_lon,   db)

    # ── Build the raw OSRM pool ───────────────────────────────────────────────
    if payload.via_lat is not None and payload.via_lon is not None:
        # User chose a specific corridor via the via-picker modal
        via_route = fetch_osrm_route_via(
            payload.source_lat, payload.source_lon,
            payload.via_lat,    payload.via_lon,
            payload.dest_lat,   payload.dest_lon,
            travel_mode,
        )
        if not via_route:
            raise HTTPException(
                status_code=503,
                detail="Could not find a route through the selected via point. "
                       "Try another corridor or plan without a via point.",
            )
        osrm_pool = [via_route]
        # Supplement with natural OSRM alternatives that differ meaningfully
        natural = fetch_osrm_routes(
            payload.source_lat, payload.source_lon,
            payload.dest_lat,   payload.dest_lon,
            travel_mode, max_alternatives=3,
        )
        for r in natural:
            if len(osrm_pool) >= 3:
                break
            if not routes_are_similar(r["distance"], r["duration"],
                                       via_route["distance"], via_route["duration"]):
                osrm_pool.append(r)
    else:
        # No via specified — ask OSRM for up to 5 alternatives
        osrm_pool = fetch_osrm_routes(
            payload.source_lat, payload.source_lon,
            payload.dest_lat,   payload.dest_lon,
            travel_mode, max_alternatives=3,
        )
        if not osrm_pool:
            raise HTTPException(
                status_code=503,
                detail="Could not reach the routing service (OSRM). "
                       "Check your internet connection or try again.",
            )

        # If OSRM returned fewer than 3 distinct routes, generate synthetic
        # alternatives by routing through perpendicular offset via-points.
        if len(osrm_pool) < 3:
            via_candidates = perpendicular_via_points(
                payload.source_lat, payload.source_lon,
                payload.dest_lat,   payload.dest_lon,
            )
            for via_lat, via_lon in via_candidates:
                if len(osrm_pool) >= 5:   # cap pool at 5
                    break
                synth = fetch_osrm_route_via(
                    payload.source_lat, payload.source_lon,
                    via_lat, via_lon,
                    payload.dest_lat,   payload.dest_lon,
                    travel_mode,
                )
                if synth is None:
                    continue
                # Only keep if it's meaningfully different from every existing route
                is_dup = any(
                    routes_are_similar(synth["distance"], synth["duration"],
                                       r["distance"], r["duration"])
                    for r in osrm_pool
                )
                if not is_dup:
                    # Tag with the via coordinates so we can extract for via_options
                    synth["_via_lat"] = via_lat
                    synth["_via_lon"] = via_lon
                    osrm_pool.append(synth)

    # ── Process all pooled routes ─────────────────────────────────────────────
    processed = []
    for idx, r in enumerate(osrm_pool):
        p = _process_osrm_route(r, city_aqi_map)
        p["_idx"] = idx
        processed.append(p)

    return _score_and_build_response(
        processed,
        payload.source_lat, payload.source_lon,
        payload.dest_lat,   payload.dest_lon,
        payload.via_lat,    payload.via_lon,
        payload.via_name,
        source_name, dest_name, travel_mode,
    )


# ── 2. Save a route (explicit, with travel window + health check) ──────────────
@router.post("/save", response_model=dict, status_code=status.HTTP_201_CREATED)
def save_route(
    payload: RouteSaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Explicitly save a chosen route with a planned travel window.

    After saving:
    - Runs a PAERI health check against the user's health profile.
    - If risk is High or Severe, creates an in-app risk_alert notification.
    - Returns health_warning=True and the risk details so the frontend can
      show a warning modal (Continue / Cancel Journey).
    """
    # ── Validate datetimes ────────────────────────────────────────────────────
    if payload.planned_end <= payload.planned_start:
        raise HTTPException(
            status_code=400,
            detail="planned_end must be after planned_start.",
        )

    # ── Validate enums ────────────────────────────────────────────────────────
    try:
        rt_enum = RouteTypeEnum(payload.route_type)
        tm_enum = TravelModeEnum(payload.travel_mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # ── Persist route ─────────────────────────────────────────────────────────
    db_route = Route(
        user_id                = current_user.id,
        source_name            = payload.source_name,
        source_lat             = payload.source_lat,
        source_lon             = payload.source_lon,
        dest_name              = payload.dest_name,
        dest_lat               = payload.dest_lat,
        dest_lon               = payload.dest_lon,
        route_type             = rt_enum,
        travel_mode            = tm_enum,
        distance_km            = payload.distance_km,
        time_min               = payload.time_min,
        avg_aqi_exposure       = payload.avg_aqi_exposure,
        exposure_reduction_pct = payload.exposure_reduction_pct,
        explanation            = payload.explanation,
        planned_start          = payload.planned_start,
        planned_end            = payload.planned_end,
    )
    db.add(db_route)
    db.flush()   # get db_route.id without committing yet

    # ── Health check via PAERI ────────────────────────────────────────────────
    health_warning    = False
    risk_score        = None
    risk_category     = None
    notification_id   = None
    warning_message   = None

    from app.models.health_profile import HealthProfile
    from app.services.paeri import calculate_paeri
    from app.models.notification import NotificationTypeEnum
    from app.services.notifier import (
        create_notification, create_route_notification, send_route_saved_email,
    )

    profile = (
        db.query(HealthProfile)
        .filter(HealthProfile.user_id == current_user.id)
        .first()
    )

    # Find nearest city for notification (use source coords)
    src_city = _nearest_city(payload.source_lat, payload.source_lon, db)

    if profile:
        # Use profile's default activity & exposure, or fall back to sensible defaults
        activity = str(profile.default_activity_level or "light")
        duration_hours = (
            (payload.planned_end - payload.planned_start).total_seconds() / 3600
        )
        # Clamp to something meaningful (min 15 min, cap at 12 h for PAERI)
        exposure_for_check = max(0.25, min(12.0, duration_hours))

        paeri = calculate_paeri(
            aqi            = payload.avg_aqi_exposure,
            profile        = profile,
            exposure_hours = exposure_for_check,
            activity_level = activity,
        )

        risk_score    = paeri.risk_score
        risk_category = paeri.risk_category

        # In-app risk_alert notification for High/Severe (appears in notification centre)
        if paeri.risk_category in ("High", "Severe"):
            health_warning = True
            src  = payload.source_name or "origin"
            dst  = payload.dest_name   or "destination"
            travel_window = (
                f"{payload.planned_start.strftime('%b %d, %H:%M')} – "
                f"{payload.planned_end.strftime('%H:%M')}"
            )
            warning_message = (
                f"Route Health Alert ({paeri.risk_category} Risk): "
                f"Your planned journey from {src} to {dst} on {travel_window} "
                f"has a personal risk score of {paeri.risk_score:.0f}/100 "
                f"based on the route's avg AQI ({payload.avg_aqi_exposure:.0f}) "
                f"and your health profile. "
                f"{paeri.explanation}"
            )
            notif = create_notification(
                db                = db,
                user_id           = current_user.id,
                city_id           = src_city.id if src_city else None,
                notification_type = NotificationTypeEnum.risk_alert,
                message           = warning_message,
                aqi_value         = payload.avg_aqi_exposure,
            )
            notification_id = notif.id
    else:
        paeri = None

    # ── Always create a route_saved notification (used by AQI monitoring job) ──
    create_route_notification(
        db                = db,
        user_id           = current_user.id,
        route_id          = db_route.id,
        city_id           = src_city.id if src_city else None,
        notification_type = NotificationTypeEnum.route_saved,
        message           = (
            f"Route saved: {payload.source_name or 'Origin'} → "
            f"{payload.dest_name or 'Destination'}"
        ),
        aqi_value         = payload.avg_aqi_exposure,
    )

    # ── Always send save confirmation email (tone adapts to risk level) ─────────
    # Called directly (not via background_tasks) because save_route is a sync
    # endpoint running in a thread pool — direct SMTP call is safe here and
    # guarantees the email attempt runs (background_tasks on sync endpoints
    # can silently drop tasks when exceptions occur).
    try:
        send_route_saved_email(
            to_email        = current_user.email,
            user_name       = current_user.name,
            source          = payload.source_name or "Origin",
            destination     = payload.dest_name   or "Destination",
            route_type      = payload.route_type,
            travel_mode     = payload.travel_mode,
            distance_km     = payload.distance_km or 0.0,
            time_min        = payload.time_min    or 0.0,
            avg_aqi         = payload.avg_aqi_exposure or 0.0,
            risk_score      = paeri.risk_score      if paeri else None,
            risk_category   = paeri.risk_category   if paeri else None,
            planned_start   = payload.planned_start,
            planned_end     = payload.planned_end,
            recommendations = paeri.recommendations if paeri else [],
        )
    except Exception as _email_exc:
        logger.error(
            "Route save email failed for user=%d route=%s→%s: %s",
            current_user.id,
            payload.source_name, payload.dest_name,
            _email_exc, exc_info=True,
        )

    db.commit()
    db.refresh(db_route)

    return {
        "id":             db_route.id,
        "saved":          True,
        "health_warning": health_warning,
        "risk_score":     risk_score,
        "risk_category":  risk_category,
        "notification_id": notification_id,
        "message":        warning_message,
        "planned_start":  db_route.planned_start,
        "planned_end":    db_route.planned_end,
    }


# ── 3. Delete / cancel a saved route ─────────────────────────────────────────
@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_route(
    route_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a saved route (user chose to cancel the journey)."""
    route = db.query(Route).filter(
        Route.id      == route_id,
        Route.user_id == current_user.id,
    ).first()
    if not route:
        raise HTTPException(status_code=404, detail="Route not found.")
    db.delete(route)
    db.commit()


# ── 4. Route history ──────────────────────────────────────────────────────────
@router.get("/history", response_model=dict)
def route_history(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the authenticated user's explicitly saved routes."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    routes = (
        db.query(Route)
        .filter(Route.user_id == current_user.id,
                Route.created_at >= cutoff)
        .order_by(desc(Route.created_at))
        .all()
    )

    return {
        "user":    current_user.name,
        "days":    days,
        "total":   len(routes),
        "records": [
            {
                "id":                    r.id,
                "source":                r.source_name,
                "destination":           r.dest_name,
                "route_type":            r.route_type,
                "travel_mode":           r.travel_mode,
                "distance_km":           r.distance_km,
                "time_min":              r.time_min,
                "avg_aqi_exposure":      r.avg_aqi_exposure,
                "exposure_reduction_pct":r.exposure_reduction_pct,
                "explanation":           r.explanation,
                "planned_start":         r.planned_start,
                "planned_end":           r.planned_end,
                "created_at":            r.created_at,
            }
            for r in routes
        ],
    }
