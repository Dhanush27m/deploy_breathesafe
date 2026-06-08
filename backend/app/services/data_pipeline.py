"""
BreatheSafe — Automated Data Pipeline Service
==============================================
Incrementally fetches weather + air quality for all 29 cities,
from MAX(datetime) in the DB up to the current hour.

Called automatically by APScheduler:
  • Hourly job  — fetch last few hours, insert into DB only
  • Daily job   — fetch yesterday (24 h), insert DB + update CSV

APIs used (in priority order):
  1. Open-Meteo Forecast API   — weather (free, no key, past_days up to 92)
  2. OpenAQ v3 API             — measured pollutants (key required, cached)
  3. Open-Meteo CAMS API       — model-based pollutants fallback (free, no key)

Design:
  • Station cache stored at /app/data/openaq_stations_cache.json (TTL: 7 days)
  • All inserts use ON CONFLICT DO NOTHING — fully idempotent
  • CSV updated atomically (write to .tmp then rename)
"""

import json
import logging
import math
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
OPENAQ_KEY   = os.getenv("OPENAQ_API_KEY", "")
OPENAQ_BASE  = "https://api.openaq.org/v3"
_OAQ_HDR     = {"X-API-Key": OPENAQ_KEY, "Accept": "application/json"} if OPENAQ_KEY else {"Accept": "application/json"}

DATABASE_URL  = os.getenv("DATABASE_URL", "")
CSV_PATH      = Path(os.getenv("SEED_CSV_PATH", "/app/data/aqi_india_enriched.csv"))
CACHE_FILE    = CSV_PATH.parent / "openaq_stations_cache.json"
CACHE_TTL_H   = 24 * 7   # re-discover every 7 days
BATCH_SIZE    = 2000

CITIES = [
    ("agartala",           "tripura",            23.8315,  91.2868),
    ("ahmedabad",          "gujarat",             23.0225,  72.5714),
    ("aizawl",             "mizoram",             23.7271,  92.7176),
    ("bengaluru",          "karnataka",           12.9716,  77.5946),
    ("bhopal",             "madhya pradesh",      23.2599,  77.4126),
    ("bhubaneswar",        "odisha",              20.2961,  85.8245),
    ("chandigarh",         "punjab",              30.7333,  76.7794),
    ("chennai",            "tamil nadu",          13.0827,  80.2707),
    ("dehradun",           "uttarakhand",         30.3165,  78.0322),
    ("delhi",              "delhi",               28.6139,  77.2090),
    ("gangtok",            "sikkim",              27.3389,  88.6065),
    ("gurugram",           "haryana",             28.4595,  77.0266),
    ("guwahati",           "assam",               26.1445,  91.7362),
    ("hyderabad",          "telangana",           17.3850,  78.4867),
    ("imphal",             "manipur",             24.8170,  93.9368),
    ("itanagar",           "arunachal pradesh",   27.0844,  93.6053),
    ("jaipur",             "rajasthan",           26.9124,  75.7873),
    ("kohima",             "nagaland",            25.6747,  94.1086),
    ("kolkata",            "west bengal",         22.5726,  88.3639),
    ("lucknow",            "uttar pradesh",       26.8467,  80.9462),
    ("mumbai",             "maharashtra",         19.0760,  72.8777),
    ("panaji",             "goa",                 15.4989,  73.8278),
    ("patna",              "bihar",               25.5941,  85.1376),
    ("raipur",             "chhattisgarh",        21.2514,  81.6296),
    ("ranchi",             "jharkhand",           23.3441,  85.3096),
    ("shillong",           "meghalaya",           25.5788,  91.8933),
    ("shimla",             "himachal pradesh",    31.1048,  77.1734),
    ("thiruvananthapuram", "kerala",               8.5241,  76.9366),
    ("visakhapatnam",      "andhra pradesh",      17.6868,  83.2185),
]

CROP_BURNING_CITIES = {
    "delhi", "chandigarh", "gurugram", "lucknow",
    "patna", "jaipur", "agartala", "bhopal",
}

# Upcoming Indian festival dates (extend as needed)
FESTIVAL_DATES = {
    date(2025, 12, 25), date(2025, 12, 26),
    date(2025, 12, 31), date(2026,  1,  1),
    date(2026,  1, 13), date(2026,  1, 14), date(2026,  1, 15),
    date(2026,  2, 26),
    date(2026,  3, 13), date(2026,  3, 14), date(2026,  3, 15),
    date(2026,  4, 14), date(2026,  4, 15),
    date(2026,  8, 15), date(2026,  8, 19),
    date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22),
    date(2026, 11,  3), date(2026, 11,  4),
    date(2026, 12, 25), date(2026, 12, 31),
    date(2027,  1,  1),
}

COL_ORDER = [
    "city", "state", "latitude", "longitude", "datetime",
    "month", "day_name", "is_weekend", "season", "time_of_day",
    "humidity_percent", "dew_point_c", "wind_gusts_kmh", "precipitation_mm",
    "is_raining", "heavy_rain", "pressure_msl_hpa", "cloud_cover_percent",
    "temperature_c", "wind_speed_kmh",
    "pm2_5_ugm3", "pm10_ugm3", "co_ugm3", "no2_ugm3", "so2_ugm3", "o3_ugm3",
    "dust_ugm3", "aod",
    "us_aqi", "india_aqi", "india_aqi_category",
    "aqi_category", "pm25_category_india",
    "festival_period", "crop_burning_season",
]


# ── HTTP helper ────────────────────────────────────────────────────────────────
def _get(url: str, headers: dict = None, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers or {})
            with urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except HTTPError as e:
            if e.code == 429:
                log.warning("Rate-limited by API — waiting 60s")
                time.sleep(60)
            elif e.code in (500, 502, 503) and attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
            else:
                raise
        except URLError as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise RuntimeError(f"Network error after {retries} tries: {e}") from e
    return {}


def _oaq_get(path: str, params: dict = None) -> dict:
    qs  = ("?" + urlencode(params)) if params else ""
    url = f"{OPENAQ_BASE}{path}{qs}"
    time.sleep(0.4)
    return _get(url, headers=_OAQ_HDR)


# ── Open-Meteo: recent weather (forecast API, supports past_days) ─────────────
def fetch_recent_weather(lat: float, lon: float, past_days: int = 3) -> pd.DataFrame:
    """
    Fetch recent hourly weather using the Open-Meteo forecast API.
    past_days: how many days back to fetch (1-92).
    Returns DataFrame with datetime + 8 weather columns.
    """
    params = urlencode({
        "latitude":        lat,
        "longitude":       lon,
        "past_days":       past_days,
        "forecast_days":   1,
        "hourly":          ("temperature_2m,relative_humidity_2m,dew_point_2m,"
                            "precipitation,cloud_cover,pressure_msl,"
                            "wind_speed_10m,wind_gusts_10m"),
        "timezone":        "Asia/Kolkata",
        "wind_speed_unit": "kmh",
    })
    d = _get(f"https://api.open-meteo.com/v1/forecast?{params}")
    h = d.get("hourly", {})
    if not h or not h.get("time"):
        return pd.DataFrame()
    return pd.DataFrame({
        "datetime":            pd.to_datetime(h["time"]),
        "temperature_c":       h.get("temperature_2m"),
        "humidity_percent":    h.get("relative_humidity_2m"),
        "dew_point_c":         h.get("dew_point_2m"),
        "precipitation_mm":    h.get("precipitation"),
        "cloud_cover_percent": h.get("cloud_cover"),
        "pressure_msl_hpa":    h.get("pressure_msl"),
        "wind_speed_kmh":      h.get("wind_speed_10m"),
        "wind_gusts_kmh":      h.get("wind_gusts_10m"),
    })


# ── Open-Meteo: CAMS air quality (fallback) ────────────────────────────────────
def fetch_recent_cams(lat: float, lon: float, past_days: int = 3) -> pd.DataFrame:
    """
    Fetch model-based air quality from CAMS via Open-Meteo.
    past_days: max 5 for free tier.
    """
    past_days = min(past_days, 5)
    params = urlencode({
        "latitude":     lat,
        "longitude":    lon,
        "past_days":    past_days,
        "forecast_days": 1,
        "hourly":       ("pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,"
                         "sulphur_dioxide,ozone,dust,aerosol_optical_depth"),
        "timezone":     "Asia/Kolkata",
    })
    d = _get(f"https://air-quality-api.open-meteo.com/v1/air-quality?{params}")
    h = d.get("hourly", {})
    if not h or not h.get("time"):
        return pd.DataFrame()
    return pd.DataFrame({
        "datetime":   pd.to_datetime(h["time"]),
        "pm2_5_ugm3": h.get("pm2_5"),
        "pm10_ugm3":  h.get("pm10"),
        "co_ugm3":    h.get("carbon_monoxide"),
        "no2_ugm3":   h.get("nitrogen_dioxide"),
        "so2_ugm3":   h.get("sulphur_dioxide"),
        "o3_ugm3":    h.get("ozone"),
        "dust_ugm3":  h.get("dust"),
        "aod":        h.get("aerosol_optical_depth"),
    })


# ── Open-Meteo: historical weather (archive API, any date range) ──────────────
def fetch_historical_weather(lat: float, lon: float,
                              start_date: str, end_date: str) -> pd.DataFrame:
    """
    Fetch hourly weather using the Open-Meteo ERA5 archive API.
    start_date / end_date: 'YYYY-MM-DD'. No day limit.
    """
    params = urlencode({
        "latitude":        lat,
        "longitude":       lon,
        "start_date":      start_date,
        "end_date":        end_date,
        "hourly":          ("temperature_2m,relative_humidity_2m,dew_point_2m,"
                            "precipitation,cloud_cover,pressure_msl,"
                            "wind_speed_10m,wind_gusts_10m"),
        "timezone":        "Asia/Kolkata",
        "wind_speed_unit": "kmh",
    })
    d = _get(f"https://archive-api.open-meteo.com/v1/archive?{params}")
    h = d.get("hourly", {})
    if not h or not h.get("time"):
        return pd.DataFrame()
    return pd.DataFrame({
        "datetime":            pd.to_datetime(h["time"]),
        "temperature_c":       h.get("temperature_2m"),
        "humidity_percent":    h.get("relative_humidity_2m"),
        "dew_point_c":         h.get("dew_point_2m"),
        "precipitation_mm":    h.get("precipitation"),
        "cloud_cover_percent": h.get("cloud_cover"),
        "pressure_msl_hpa":    h.get("pressure_msl"),
        "wind_speed_kmh":      h.get("wind_speed_10m"),
        "wind_gusts_kmh":      h.get("wind_gusts_10m"),
    })


# ── Open-Meteo: historical CAMS air quality (any date range) ──────────────────
def fetch_historical_cams(lat: float, lon: float,
                           start_date: str, end_date: str) -> pd.DataFrame:
    """
    Fetch model-based air quality using CAMS reanalysis via Open-Meteo.
    Uses start_date/end_date — no 5-day limit unlike fetch_recent_cams.
    """
    params = urlencode({
        "latitude":   lat,
        "longitude":  lon,
        "start_date": start_date,
        "end_date":   end_date,
        "hourly":     ("pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,"
                       "sulphur_dioxide,ozone,dust,aerosol_optical_depth"),
        "timezone":   "Asia/Kolkata",
    })
    d = _get(f"https://air-quality-api.open-meteo.com/v1/air-quality?{params}")
    h = d.get("hourly", {})
    if not h or not h.get("time"):
        return pd.DataFrame()
    return pd.DataFrame({
        "datetime":   pd.to_datetime(h["time"]),
        "pm2_5_ugm3": h.get("pm2_5"),
        "pm10_ugm3":  h.get("pm10"),
        "co_ugm3":    h.get("carbon_monoxide"),
        "no2_ugm3":   h.get("nitrogen_dioxide"),
        "so2_ugm3":   h.get("sulphur_dioxide"),
        "o3_ugm3":    h.get("ozone"),
        "dust_ugm3":  h.get("dust"),
        "aod":        h.get("aerosol_optical_depth"),
    })


# ── OpenAQ: station discovery (cached) ────────────────────────────────────────
def _haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _load_cache() -> dict | None:
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE) as f:
            cached = json.load(f)
        age_h = (time.time() - cached.get("_ts", 0)) / 3600
        if age_h > CACHE_TTL_H:
            log.info("OpenAQ station cache expired (%.1f h old) — will re-discover", age_h)
            return None
        log.info("Using OpenAQ station cache (%.1f h old)", age_h)
        return {k: v for k, v in cached.items() if not k.startswith("_")}
    except Exception as e:
        log.warning("Failed to read station cache: %s", e)
        return None


def _save_cache(data: dict):
    try:
        payload = dict(data)
        payload["_ts"] = time.time()
        with open(CACHE_FILE, "w") as f:
            json.dump(payload, f, indent=2)
        log.info("OpenAQ station cache saved to %s", CACHE_FILE)
    except Exception as e:
        log.warning("Failed to save station cache: %s", e)


def discover_stations() -> dict:
    """
    Returns city_sensors: {city_name: {"loc_id": ..., "sensors": {col: sensor_id}}}
    Uses cache if available and fresh; otherwise queries OpenAQ API.
    """
    cached = _load_cache()
    if cached is not None:
        return cached

    log.info("Discovering India OpenAQ stations (this may take a minute)...")
    all_locs = []
    page = 1
    while True:
        try:
            d = _oaq_get("/locations", {"country_id": "IN", "limit": 1000, "page": page})
        except Exception as e:
            log.warning("OpenAQ location fetch failed page %d: %s", page, e)
            break
        results = d.get("results", [])
        if not results:
            break
        all_locs.extend(results)
        # OpenAQ v3 sometimes returns found as '>1000' string — parse safely
        found_raw = d.get("meta", {}).get("found", 0)
        try:
            found = int(found_raw)
        except (TypeError, ValueError):
            found = len(all_locs) + 1   # can't tell total — keep paginating
        log.info("  Page %d: %d locations (total=%s)", page, len(results), found_raw)
        if len(all_locs) >= found:
            break
        page += 1
        time.sleep(0.5)

    log.info("Total India locations from OpenAQ: %d", len(all_locs))

    WANTED = {
        "pm2.5": "pm2_5_ugm3", "pm10": "pm10_ugm3",
        "no2":   "no2_ugm3",   "so2":  "so2_ugm3",
        "o3":    "o3_ugm3",    "co":   "co_ugm3",
    }

    city_sensors = {}
    for city, state, clat, clon in CITIES:
        best_loc, best_dist = None, 9999.0
        for loc in all_locs:
            coords = loc.get("coordinates") or {}
            olat, olon = coords.get("latitude"), coords.get("longitude")
            if olat is None or olon is None:
                continue
            d = _haversine(clat, clon, float(olat), float(olon))
            if d < best_dist:
                best_dist, best_loc = d, loc

        if best_loc is None or best_dist > 50:
            log.warning("  %s: no station within 50 km (best=%.1f km) — CAMS fallback", city, best_dist)
            continue

        loc_id = best_loc["id"]
        try:
            sensor_data = _oaq_get(f"/locations/{loc_id}/sensors")
            sensors = sensor_data.get("results", [])
        except Exception as e:
            log.warning("  %s: sensor fetch failed: %s", city, e)
            continue

        param_map = {}
        for s in sensors:
            pname = (s.get("parameter") or {}).get("name", "").lower()
            col = WANTED.get(pname)
            if col:
                param_map[col] = s["id"]

        if param_map:
            city_sensors[city] = {
                "loc_id":   loc_id,
                "loc_name": best_loc.get("name", ""),
                "dist_km":  round(best_dist, 1),
                "sensors":  param_map,
            }
            log.info("  %s -> %s (%.1f km) | %s",
                     city, best_loc.get("name", ""), best_dist, list(param_map.keys()))
        else:
            log.warning("  %s: station found but no matching sensors", city)

    _save_cache(city_sensors)
    return city_sensors


# ── OpenAQ: fetch measurements for a date range ───────────────────────────────
def fetch_openaq_range(sensor_map: dict, dt_from: datetime, dt_to: datetime) -> pd.DataFrame:
    """
    Fetch hourly pollutant measurements from OpenAQ for a specific datetime range.
    sensor_map: {col_name: sensor_id}
    """
    from_str = dt_from.strftime("%Y-%m-%dT%H:%M:%S+05:30")
    to_str   = dt_to.strftime("%Y-%m-%dT%H:%M:%S+05:30")

    all_series = {}
    for col, sid in sensor_map.items():
        records = []
        page = 1
        while True:
            try:
                d = _oaq_get(f"/sensors/{sid}/measurements", {
                    "datetime_from": from_str,
                    "datetime_to":   to_str,
                    "limit":         1000,
                    "page":          page,
                })
            except Exception as e:
                log.warning("  OpenAQ sensor %s (%s) failed: %s", sid, col, e)
                break

            results = d.get("results", [])
            if not results:
                break

            for r in results:
                dt_obj = (r.get("datetime") or {})
                dt_str = dt_obj.get("local") or dt_obj.get("utc")
                val    = r.get("value")
                if dt_str and val is not None:
                    try:
                        ts = (pd.to_datetime(dt_str, utc=True)
                              .tz_convert("Asia/Kolkata")
                              .tz_localize(None))
                        records.append((ts, float(val)))
                    except Exception:
                        pass

            found = d.get("meta", {}).get("found", 0)
            if len(records) >= found or not results:
                break
            page += 1
            time.sleep(0.4)

        if records:
            s = pd.Series({dt: v for dt, v in records}, name=col)
            s.index.name = "datetime"
            all_series[col] = s

    if not all_series:
        return pd.DataFrame()

    df = pd.DataFrame(all_series)
    df.index.name = "datetime"
    df = df.resample("1h").mean()
    df.reset_index(inplace=True)
    return df


# ── AQI formulas ──────────────────────────────────────────────────────────────
def _linear(c, cl, ch, il, ih):
    if pd.isna(c):
        return np.nan
    c = float(np.clip(c, cl, ch))
    return ((ih - il) / (ch - cl)) * (c - cl) + il


def _sub(c, bp):
    if pd.isna(c):
        return np.nan
    c = float(c)
    for cl, ch, il, ih in bp:
        if c <= ch:
            return _linear(c, cl, ch, il, ih)
    return 500.0


PM25_BP  = [(0,30,0,50),(30,60,51,100),(60,90,101,200),(90,120,201,300),(120,250,301,400),(250,500,401,500)]
PM10_BP  = [(0,50,0,50),(50,100,51,100),(100,250,101,200),(250,350,201,300),(350,430,301,400),(430,600,401,500)]
NO2_BP   = [(0,40,0,50),(40,80,51,100),(80,180,101,200),(180,280,201,300),(280,400,301,400),(400,800,401,500)]
SO2_BP   = [(0,40,0,50),(40,80,51,100),(80,380,101,200),(380,800,201,300),(800,1600,301,400),(1600,2000,401,500)]
O3_BP    = [(0,50,0,50),(50,100,51,100),(100,168,101,200),(168,208,201,300),(208,748,301,400),(748,1000,401,500)]
CO_MG_BP = [(0,1,0,50),(1,2,51,100),(2,10,101,200),(10,17,201,300),(17,34,301,400),(34,50,401,500)]
PM25_US  = [(0,12,0,50),(12,35.4,51,100),(35.4,55.4,101,150),(55.4,150.4,151,200),
            (150.4,250.4,201,300),(250.4,350.4,301,400),(350.4,500,401,500)]


def compute_india_aqi(row):
    subs = [
        _sub(row.get("pm2_5_ugm3"), PM25_BP),
        _sub(row.get("pm10_ugm3"),  PM10_BP),
        _sub(row.get("no2_ugm3"),   NO2_BP),
        _sub(row.get("so2_ugm3"),   SO2_BP),
        _sub(row.get("o3_ugm3"),    O3_BP),
    ]
    co = row.get("co_ugm3")
    if not pd.isna(co):
        subs.append(_sub(float(co) / 1000, CO_MG_BP))
    valid = [x for x in subs if not pd.isna(x)]
    return round(max(valid), 1) if valid else np.nan


def _india_cat(aqi):
    if pd.isna(aqi): return None
    aqi = float(aqi)
    if aqi <= 50:  return "Good"
    if aqi <= 100: return "Satisfactory"
    if aqi <= 200: return "Moderately Polluted"
    if aqi <= 300: return "Poor"
    if aqi <= 400: return "Very Poor"
    return "Severe"


def _us_aqi(pm25):
    return round(_sub(pm25, PM25_US), 0) if not pd.isna(pm25) else np.nan


def _us_cat(aqi):
    if pd.isna(aqi): return None
    aqi = float(aqi)
    if aqi <= 50:  return "Good"
    if aqi <= 100: return "Moderate"
    if aqi <= 150: return "Unhealthy for Sensitive Groups"
    if aqi <= 200: return "Unhealthy"
    if aqi <= 300: return "Very Unhealthy"
    return "Hazardous"


def _pm25_ind_cat(v):
    if pd.isna(v): return None
    v = float(v)
    if v <= 30:  return "good"
    if v <= 60:  return "satisfactory"
    if v <= 90:  return "moderate"
    if v <= 120: return "poor"
    if v <= 250: return "very poor"
    return "severe"


def _season(m):
    if m in (12, 1, 2): return "winter"
    if m in (3, 4, 5):  return "summer"
    if m in (6, 7, 8, 9): return "monsoon"
    return "post_monsoon"


def _tod(h):
    if h < 6:  return "night"
    if h < 12: return "morning"
    if h < 18: return "afternoon"
    return "evening"


def add_derived(df: pd.DataFrame, city: str) -> pd.DataFrame:
    df = df.copy()
    dt = df["datetime"]
    df["month"]       = dt.dt.month.astype(float)
    df["day_name"]    = dt.dt.day_name().str.lower()
    df["is_weekend"]  = dt.dt.dayofweek >= 5
    df["season"]      = dt.dt.month.map(_season)
    df["time_of_day"] = dt.dt.hour.map(_tod)
    df["is_raining"]  = df["precipitation_mm"].fillna(0) > 0
    df["heavy_rain"]  = df["precipitation_mm"].fillna(0) > 10
    df["festival_period"]     = dt.dt.date.map(lambda d: d in FESTIVAL_DATES)
    in_burn = dt.dt.month.isin([10, 11, 4, 5])
    df["crop_burning_season"] = in_burn & (city.lower() in CROP_BURNING_CITIES)
    df["india_aqi"]           = df.apply(compute_india_aqi, axis=1)
    df["india_aqi_category"]  = df["india_aqi"].map(_india_cat)
    df["us_aqi"]              = df["pm2_5_ugm3"].map(_us_aqi)
    df["aqi_category"]        = df["us_aqi"].map(_us_cat)
    df["pm25_category_india"] = df["pm2_5_ugm3"].map(_pm25_ind_cat)
    return df


# ── DB helpers ────────────────────────────────────────────────────────────────
def _sv(v):
    """Safe scalar — convert NaN/None to None for DB."""
    if v is None:
        return None
    try:
        if math.isnan(float(v)):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _sb(v):
    """Safe bool — convert NaN/None to None for DB."""
    if v is None:
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    try:
        if math.isnan(float(v)):
            return None
    except (TypeError, ValueError):
        pass
    return bool(v)


def _get_engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True)


def _get_station_map(engine) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT ms.id, c.name FROM monitoring_stations ms "
            "JOIN cities c ON c.id = ms.city_id"
        )).fetchall()
    return {r[1].lower(): r[0] for r in rows}


def _get_last_datetime(engine) -> datetime:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT MAX(datetime) FROM aqi_data")).fetchone()
    if row and row[0]:
        return row[0]
    return datetime(2025, 11, 26, 23, 0)


def _insert_rows(engine, station_map: dict, df: pd.DataFrame) -> int:
    """Insert new rows into aqi_data, returns count inserted."""
    Session = sessionmaker(bind=engine)
    session = Session()
    inserted = 0
    total = len(df)

    try:
        for b_start in range(0, total, BATCH_SIZE):
            batch = df.iloc[b_start: b_start + BATCH_SIZE]
            rows = []
            for _, row in batch.iterrows():
                sid = station_map.get(str(row["city"]).lower().strip())
                if sid is None:
                    continue
                rows.append({
                    "station_id":          sid,
                    "datetime":            row["datetime"],
                    "pm2_5_ugm3":          _sv(row.get("pm2_5_ugm3")),
                    "pm10_ugm3":           _sv(row.get("pm10_ugm3")),
                    "co_ugm3":             _sv(row.get("co_ugm3")),
                    "no2_ugm3":            _sv(row.get("no2_ugm3")),
                    "so2_ugm3":            _sv(row.get("so2_ugm3")),
                    "o3_ugm3":             _sv(row.get("o3_ugm3")),
                    "dust_ugm3":           _sv(row.get("dust_ugm3")),
                    "aod":                 _sv(row.get("aod")),
                    "us_aqi":              _sv(row.get("us_aqi")),
                    "india_aqi":           _sv(row.get("india_aqi")),
                    "india_aqi_category":  _sv(row.get("india_aqi_category")),
                    "pm25_category_india": _sv(row.get("pm25_category_india")),
                    "temperature_c":       _sv(row.get("temperature_c")),
                    "wind_speed_kmh":      _sv(row.get("wind_speed_kmh")),
                    "wind_gusts_kmh":      _sv(row.get("wind_gusts_kmh")),
                    "humidity_percent":    _sv(row.get("humidity_percent")),
                    "dew_point_c":         _sv(row.get("dew_point_c")),
                    "pressure_msl_hpa":    _sv(row.get("pressure_msl_hpa")),
                    "cloud_cover_percent": _sv(row.get("cloud_cover_percent")),
                    "precipitation_mm":    _sv(row.get("precipitation_mm")),
                    "is_raining":          _sb(row.get("is_raining")),
                    "heavy_rain":          _sb(row.get("heavy_rain")),
                    "month":               _sv(row.get("month")),
                    "day_name":            _sv(row.get("day_name")),
                    "is_weekend":          _sb(row.get("is_weekend")),
                    "season":              _sv(row.get("season")),
                    "time_of_day":         _sv(row.get("time_of_day")),
                    "festival_period":     _sb(row.get("festival_period")),
                    "crop_burning_season": _sb(row.get("crop_burning_season")),
                })
            if rows:
                session.execute(text("""
                    INSERT INTO aqi_data (
                        station_id, datetime,
                        pm2_5_ugm3, pm10_ugm3, co_ugm3, no2_ugm3,
                        so2_ugm3, o3_ugm3, dust_ugm3, aod,
                        us_aqi, india_aqi, india_aqi_category, pm25_category_india,
                        temperature_c, wind_speed_kmh, wind_gusts_kmh,
                        humidity_percent, dew_point_c, pressure_msl_hpa,
                        cloud_cover_percent, precipitation_mm,
                        is_raining, heavy_rain,
                        month, day_name, is_weekend, season,
                        time_of_day, festival_period, crop_burning_season
                    ) VALUES (
                        :station_id, :datetime,
                        :pm2_5_ugm3, :pm10_ugm3, :co_ugm3, :no2_ugm3,
                        :so2_ugm3, :o3_ugm3, :dust_ugm3, :aod,
                        :us_aqi, :india_aqi, :india_aqi_category, :pm25_category_india,
                        :temperature_c, :wind_speed_kmh, :wind_gusts_kmh,
                        :humidity_percent, :dew_point_c, :pressure_msl_hpa,
                        :cloud_cover_percent, :precipitation_mm,
                        :is_raining, :heavy_rain,
                        :month, :day_name, :is_weekend, :season,
                        :time_of_day, :festival_period, :crop_burning_season
                    ) ON CONFLICT DO NOTHING
                """), rows)
                session.commit()
                inserted += len(rows)
    finally:
        session.close()

    return inserted


def _update_csv(new_df: pd.DataFrame):
    """
    Append new_df to the master CSV file.
    Uses a .tmp file + rename for atomicity.
    """
    if not CSV_PATH.exists():
        log.warning("CSV not found at %s — skipping CSV update", CSV_PATH)
        return 0

    try:
        existing = pd.read_csv(CSV_PATH)
        # Deduplicate: drop rows already present by (city, datetime)
        existing_keys = set(zip(existing["city"], existing["datetime"].astype(str)))
        new_filtered = new_df[
            ~new_df.apply(
                lambda r: (r["city"], str(r["datetime"])) in existing_keys,
                axis=1,
            )
        ]
        if new_filtered.empty:
            log.info("CSV already up to date — no new rows to append")
            return 0

        combined = pd.concat([existing, new_filtered], ignore_index=True)

        # Write directly — Docker volumes don't support cross-device rename
        combined.to_csv(CSV_PATH, index=False)
        log.info("CSV updated: +%d rows (total=%d)", len(new_filtered), len(combined))
        return len(new_filtered)
    except Exception as e:
        log.error("CSV update failed: %s", e)
        return 0


# ── Core pipeline function ────────────────────────────────────────────────────
def run_pipeline(update_csv: bool = False, verbose: bool = True) -> dict:
    """
    Main pipeline entry point.

    Fetches data from MAX(datetime) in DB up to current hour,
    inserts new rows into PostgreSQL, and optionally updates CSV.

    Args:
        update_csv:  If True, also append new rows to the master CSV file.
        verbose:     Log progress to console.

    Returns:
        dict with keys: start_dt, end_dt, rows_fetched, rows_inserted, csv_rows_added
    """
    t0 = time.time()
    now = datetime.utcnow() + timedelta(hours=5, minutes=30)  # IST
    # Round down to last completed hour
    fetch_to = now.replace(minute=0, second=0, microsecond=0)

    engine = _get_engine()
    last_dt = _get_last_datetime(engine)
    fetch_from = last_dt + timedelta(hours=1)
    fetch_from = fetch_from.replace(minute=0, second=0, microsecond=0)

    if fetch_from >= fetch_to:
        log.info("Pipeline: DB is already up to date (last=%s)", last_dt)
        return {
            "start_dt": str(fetch_from),
            "end_dt":   str(fetch_to),
            "rows_fetched": 0, "rows_inserted": 0, "csv_rows_added": 0,
        }

    gap_hours = int((fetch_to - fetch_from).total_seconds() / 3600)
    past_days = max(2, math.ceil(gap_hours / 24) + 1)
    past_days = min(past_days, 92)   # Open-Meteo max

    # When the gap is > 5 days the recent CAMS API (past_days≤5) can't reach back
    # far enough. Switch to the archive/historical APIs for both weather and AQ.
    use_historical = gap_hours > 5 * 24
    hist_start = fetch_from.strftime("%Y-%m-%d")
    hist_end   = fetch_to.strftime("%Y-%m-%d")

    if verbose:
        log.info("Pipeline starting | from=%s  to=%s  gap=%dh  past_days=%d  mode=%s",
                 fetch_from, fetch_to, gap_hours, past_days,
                 "HISTORICAL" if use_historical else "RECENT")

    # Load OpenAQ station map (from cache or live discovery)
    try:
        city_sensors = discover_stations()
    except Exception as e:
        log.warning("OpenAQ discovery failed (%s) — using CAMS for all cities", e)
        city_sensors = {}

    station_map = _get_station_map(engine)

    all_frames = []
    oaq_count, cams_count = 0, 0

    for i, (city, state, lat, lon) in enumerate(CITIES, 1):
        if verbose:
            log.info("[%2d/%d] %s", i, len(CITIES), city.title())

        # ── Weather ──────────────────────────────────────────────────────────
        try:
            if use_historical:
                df_w = fetch_historical_weather(lat, lon, hist_start, hist_end)
            else:
                df_w = fetch_recent_weather(lat, lon, past_days=past_days)
            if df_w.empty:
                log.warning("  %s: weather returned empty", city)
                continue
        except Exception as e:
            log.error("  %s: weather FAILED: %s — skipping", city, e)
            continue

        # ── Pollutants ────────────────────────────────────────────────────────
        df_aq = pd.DataFrame()
        source_tag = "CAMS"

        if city in city_sensors:
            try:
                df_aq = fetch_openaq_range(
                    city_sensors[city]["sensors"],
                    fetch_from, fetch_to,
                )
                if len(df_aq) > 5:
                    source_tag = "OpenAQ"
                    oaq_count += 1
                else:
                    df_aq = pd.DataFrame()
            except Exception as e:
                log.warning("  %s: OpenAQ failed (%s) — CAMS fallback", city, e)
                df_aq = pd.DataFrame()

        if df_aq.empty:
            try:
                if use_historical:
                    df_aq = fetch_historical_cams(lat, lon, hist_start, hist_end)
                else:
                    df_aq = fetch_recent_cams(lat, lon, past_days=5)
                cams_count += 1
            except Exception as e:
                log.error("  %s: CAMS also failed: %s — skipping", city, e)
                continue

        # ── Merge + filter to new rows ────────────────────────────────────────
        df = df_w.merge(df_aq, on="datetime", how="left")

        # Filter to only rows we actually need
        df = df[(df["datetime"] >= fetch_from) & (df["datetime"] <= fetch_to)].copy()
        if df.empty:
            log.debug("  %s: no rows in target window after merge", city)
            continue

        # Static columns
        df["city"]      = city
        df["state"]     = state
        df["latitude"]  = lat
        df["longitude"] = lon

        for col in ["dust_ugm3", "aod"]:
            if col not in df.columns:
                df[col] = np.nan

        df = add_derived(df, city)
        df = df[[c for c in COL_ORDER if c in df.columns]]

        all_frames.append(df)
        if verbose:
            log.info("  %s: %d rows | source=%s", city, len(df), source_tag)

        time.sleep(0.2)

    if not all_frames:
        log.warning("Pipeline: no data fetched for any city")
        return {
            "start_dt": str(fetch_from), "end_dt": str(fetch_to),
            "rows_fetched": 0, "rows_inserted": 0, "csv_rows_added": 0,
        }

    new_df = pd.concat(all_frames, ignore_index=True)
    new_df.sort_values(["city", "datetime"], inplace=True)
    new_df.reset_index(drop=True, inplace=True)

    rows_fetched = len(new_df)
    log.info("Pipeline: %d total rows fetched (%d OpenAQ, %d CAMS cities)",
             rows_fetched, oaq_count, cams_count)

    # ── DB insert ─────────────────────────────────────────────────────────────
    rows_inserted = _insert_rows(engine, station_map, new_df)
    log.info("Pipeline: inserted %d rows into DB", rows_inserted)

    # ── CSV update (daily only) ───────────────────────────────────────────────
    csv_added = 0
    if update_csv:
        csv_added = _update_csv(new_df)

    elapsed = time.time() - t0
    log.info("Pipeline complete in %.1fs | fetched=%d inserted=%d csv_added=%d",
             elapsed, rows_fetched, rows_inserted, csv_added)

    return {
        "start_dt":      str(fetch_from),
        "end_dt":        str(fetch_to),
        "rows_fetched":  rows_fetched,
        "rows_inserted": rows_inserted,
        "csv_rows_added": csv_added,
    }
