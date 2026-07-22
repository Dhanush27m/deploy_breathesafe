"""
BreatheSafe — Complete Gap Data Fetcher
=========================================
Fills the data gap: 27 Nov 2025 to 14 Apr 2026  (~96,700 rows, 29 cities)

Sources (in priority order):
  1. Open-Meteo Historical Weather API   — 8 weather params   [FREE, no key]
  2. OpenAQ v3 API                       — 6 pollutants        [API key required]
  3. Open-Meteo CAMS Air Quality API     — fallback pollutants [FREE, no key, model-based]

Derived automatically from fetched data:
  is_raining, heavy_rain, month, day_name, is_weekend, season, time_of_day,
  india_aqi, india_aqi_category, us_aqi, aqi_category, pm25_category_india,
  festival_period, crop_burning_season, dust_ugm3, aod

After fetching the script:
  1. Appends new rows to  /app/data/aqi_india_enriched.csv
  2. Inserts new rows into PostgreSQL  aqi_data  table

Usage (run inside the backend container):
    docker exec breathesafe_backend python /app/fetch_gap_data.py
"""

import json
import logging
import math
import os
import sys
import time
from datetime import date, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
DATABASE_URL  = os.getenv("DATABASE_URL", "")
CSV_PATH      = os.getenv("SEED_CSV_PATH", "/app/data/aqi_india_enriched.csv")
OPENAQ_KEY    = os.getenv("OPENAQ_API_KEY", "")
OPENAQ_BASE   = "https://api.openaq.org/v3"
GAP_START     = "2025-11-27"
GAP_END       = "2026-04-14"
BATCH_SIZE    = 5000

CITIES = [
    ("agartala",           "tripura",           23.8315,  91.2868),
    ("ahmedabad",          "gujarat",            23.0225,  72.5714),
    ("aizawl",             "mizoram",            23.7271,  92.7176),
    ("bengaluru",          "karnataka",          12.9716,  77.5946),
    ("bhopal",             "madhya pradesh",     23.2599,  77.4126),
    ("bhubaneswar",        "odisha",             20.2961,  85.8245),
    ("chandigarh",         "punjab",             30.7333,  76.7794),
    ("chennai",            "tamil nadu",         13.0827,  80.2707),
    ("dehradun",           "uttarakhand",        30.3165,  78.0322),
    ("delhi",              "delhi",              28.6139,  77.2090),
    ("gangtok",            "sikkim",             27.3389,  88.6065),
    ("gurugram",           "haryana",            28.4595,  77.0266),
    ("guwahati",           "assam",              26.1445,  91.7362),
    ("hyderabad",          "telangana",          17.3850,  78.4867),
    ("imphal",             "manipur",            24.8170,  93.9368),
    ("itanagar",           "arunachal pradesh",  27.0844,  93.6053),
    ("jaipur",             "rajasthan",          26.9124,  75.7873),
    ("kohima",             "nagaland",           25.6747,  94.1086),
    ("kolkata",            "west bengal",        22.5726,  88.3639),
    ("lucknow",            "uttar pradesh",      26.8467,  80.9462),
    ("mumbai",             "maharashtra",        19.0760,  72.8777),
    ("panaji",             "goa",                15.4989,  73.8278),
    ("patna",              "bihar",              25.5941,  85.1376),
    ("raipur",             "chhattisgarh",       21.2514,  81.6296),
    ("ranchi",             "jharkhand",          23.3441,  85.3096),
    ("shillong",           "meghalaya",          25.5788,  91.8933),
    ("shimla",             "himachal pradesh",   31.1048,  77.1734),
    ("thiruvananthapuram", "kerala",              8.5241,  76.9366),
    ("visakhapatnam",      "andhra pradesh",     17.6868,  83.2185),
]

CROP_BURNING_CITIES = {
    "delhi", "chandigarh", "gurugram", "lucknow",
    "patna", "jaipur", "agartala", "bhopal"
}

FESTIVAL_DATES = {
    date(2025, 12, 25), date(2025, 12, 26),
    date(2025, 12, 31), date(2026,  1,  1),
    date(2026,  1, 13), date(2026,  1, 14), date(2026, 1, 15),
    date(2026,  2, 26),
    date(2026,  3, 13), date(2026,  3, 14), date(2026, 3, 15),
}

# ── HTTP helpers ───────────────────────────────────────────────────────────────
def _get(url: str, headers: dict = None, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers or {})
            with urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except HTTPError as e:
            if e.code == 429:
                wait = 60
                log.warning(f"  Rate-limited — waiting {wait}s")
                time.sleep(wait)
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

# ── Open-Meteo: Weather ────────────────────────────────────────────────────────
def fetch_weather(lat: float, lon: float) -> pd.DataFrame:
    params = urlencode({
        "latitude":        lat,
        "longitude":       lon,
        "start_date":      GAP_START,
        "end_date":        GAP_END,
        "hourly":          "temperature_2m,relative_humidity_2m,dew_point_2m,"
                           "precipitation,cloud_cover,pressure_msl,"
                           "wind_speed_10m,wind_gusts_10m",
        "timezone":        "Asia/Kolkata",
        "wind_speed_unit": "kmh",
    })
    d = _get(f"https://archive-api.open-meteo.com/v1/archive?{params}")
    h = d["hourly"]
    return pd.DataFrame({
        "datetime":            pd.to_datetime(h["time"]),
        "temperature_c":       h["temperature_2m"],
        "humidity_percent":    h["relative_humidity_2m"],
        "dew_point_c":         h["dew_point_2m"],
        "precipitation_mm":    h["precipitation"],
        "cloud_cover_percent": h["cloud_cover"],
        "pressure_msl_hpa":    h["pressure_msl"],
        "wind_speed_kmh":      h["wind_speed_10m"],
        "wind_gusts_kmh":      h["wind_gusts_10m"],
    })

# ── Open-Meteo: CAMS air quality (fallback) ────────────────────────────────────
def fetch_cams_airquality(lat: float, lon: float) -> pd.DataFrame:
    params = urlencode({
        "latitude":   lat,
        "longitude":  lon,
        "start_date": GAP_START,
        "end_date":   GAP_END,
        "hourly":     "pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,"
                      "sulphur_dioxide,ozone,dust,aerosol_optical_depth",
        "timezone":   "Asia/Kolkata",
    })
    d = _get(f"https://air-quality-api.open-meteo.com/v1/air-quality?{params}")
    h = d["hourly"]
    return pd.DataFrame({
        "datetime":   pd.to_datetime(h["time"]),
        "pm2_5_ugm3": h["pm2_5"],
        "pm10_ugm3":  h["pm10"],
        "co_ugm3":    h["carbon_monoxide"],
        "no2_ugm3":   h["nitrogen_dioxide"],
        "so2_ugm3":   h["sulphur_dioxide"],
        "o3_ugm3":    h["ozone"],
        "dust_ugm3":  h["dust"],
        "aod":        h["aerosol_optical_depth"],
    })

# ── OpenAQ v3: discover India stations ────────────────────────────────────────
_OAQ_HDR = {"X-API-Key": OPENAQ_KEY, "Accept": "application/json"}

def _oaq_get(path: str, params: dict = None) -> dict:
    qs  = ("?" + urlencode(params)) if params else ""
    url = f"{OPENAQ_BASE}{path}{qs}"
    time.sleep(0.5)   # stay well within rate limits
    return _get(url, headers=_OAQ_HDR)

def discover_india_stations() -> dict:
    """
    Returns: {city_name_lower: {param_name: sensor_id, ...}, ...}
    Matches OpenAQ locations to our 29 cities by coordinate proximity (< 50 km).
    """
    log.info("  Discovering India stations from OpenAQ v3...")
    all_locs = []
    page = 1
    while True:
        d = _oaq_get("/locations", {
            "country_id": "IN",
            "limit": 1000,
            "page": page,
        })
        results = d.get("results", [])
        if not results:
            break
        all_locs.extend(results)
        meta  = d.get("meta", {})
        found = meta.get("found", 0)
        log.info(f"  Page {page}: got {len(results)} locations (total found={found})")
        if len(all_locs) >= found:
            break
        page += 1
        time.sleep(0.5)

    log.info(f"  Total India locations: {len(all_locs)}")

    # For each location, fetch its sensors
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat/2)**2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon/2)**2)
        return R * 2 * math.asin(math.sqrt(a))

    city_sensors = {}   # city -> {param: sensor_id}

    for city, state, clat, clon in CITIES:
        best_loc  = None
        best_dist = 9999.0

        for loc in all_locs:
            coords = loc.get("coordinates") or {}
            olat   = coords.get("latitude")
            olon   = coords.get("longitude")
            if olat is None or olon is None:
                continue
            dist = haversine(clat, clon, float(olat), float(olon))
            if dist < best_dist:
                best_dist = dist
                best_loc  = loc

        if best_loc is None or best_dist > 50:
            log.warning(f"  No OpenAQ station within 50 km of {city} (best={best_dist:.1f} km) — will use CAMS")
            continue

        loc_id = best_loc["id"]
        # fetch sensors for this location
        sensor_data = _oaq_get(f"/locations/{loc_id}/sensors")
        sensors     = sensor_data.get("results", [])

        param_map = {}
        WANTED = {"pm2.5": "pm2_5_ugm3", "pm10": "pm10_ugm3",
                  "no2": "no2_ugm3",  "so2": "so2_ugm3",
                  "o3": "o3_ugm3",    "co": "co_ugm3"}

        for s in sensors:
            pname = (s.get("parameter") or {}).get("name", "").lower()
            col   = WANTED.get(pname)
            if col:
                param_map[col] = s["id"]

        if param_map:
            city_sensors[city] = {
                "loc_id":   loc_id,
                "loc_name": best_loc.get("name", ""),
                "dist_km":  round(best_dist, 1),
                "sensors":  param_map,
            }
            log.info(
                f"  {city:20s} -> {best_loc.get('name','')} ({best_dist:.1f} km) | params: {list(param_map.keys())}"
            )
        else:
            log.warning(f"  {city}: station found but no matching sensors")

    return city_sensors


def fetch_openaq_pollutants(city: str, sensor_map: dict) -> pd.DataFrame:
    """
    Fetch hourly measurements for all available sensors for a city.
    Returns DataFrame indexed by datetime with pollutant columns.
    """
    dt_from = f"{GAP_START}T00:00:00+05:30"
    dt_to   = f"{GAP_END}T23:59:59+05:30"

    all_series = {}
    for col, sid in sensor_map.items():
        records = []
        page    = 1
        while True:
            d = _oaq_get(f"/sensors/{sid}/measurements", {
                "datetime_from": dt_from,
                "datetime_to":   dt_to,
                "limit":         1000,
                "page":          page,
            })
            results = d.get("results", [])
            if not results:
                break
            for r in results:
                dt_str = (r.get("datetime") or {}).get("local") or (r.get("datetime") or {}).get("utc")
                val    = r.get("value")
                if dt_str and val is not None:
                    records.append((pd.to_datetime(dt_str, utc=True)
                                    .tz_convert("Asia/Kolkata")
                                    .tz_localize(None), float(val)))
            meta  = d.get("meta", {})
            found = meta.get("found", 0)
            if len(records) >= found or not results:
                break
            page += 1
            time.sleep(0.5)

        if records:
            s = pd.Series({dt: v for dt, v in records}, name=col)
            s.index.name = "datetime"
            all_series[col] = s

    if not all_series:
        return pd.DataFrame()

    df = pd.DataFrame(all_series)
    df.index.name = "datetime"

    # Resample to hourly (average if sub-hourly)
    df = df.resample("1h").mean()
    df.reset_index(inplace=True)
    return df


# ── AQI formulas ──────────────────────────────────────────────────────────────
def _linear(c, cl, ch, il, ih):
    if pd.isna(c): return np.nan
    c = float(np.clip(c, cl, ch))
    return ((ih - il) / (ch - cl)) * (c - cl) + il

def _sub(c, bp):
    if pd.isna(c): return np.nan
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

def india_cat(aqi):
    if pd.isna(aqi): return None
    aqi = float(aqi)
    if aqi <= 50:  return "Good"
    if aqi <= 100: return "Satisfactory"
    if aqi <= 200: return "Moderately Polluted"
    if aqi <= 300: return "Poor"
    if aqi <= 400: return "Very Poor"
    return "Severe"

def us_aqi(pm25):
    return round(_sub(pm25, PM25_US), 0) if not pd.isna(pm25) else np.nan

def us_cat(aqi):
    if pd.isna(aqi): return None
    aqi = float(aqi)
    if aqi <= 50:  return "Good"
    if aqi <= 100: return "Moderate"
    if aqi <= 150: return "Unhealthy for Sensitive Groups"
    if aqi <= 200: return "Unhealthy"
    if aqi <= 300: return "Very Unhealthy"
    return "Hazardous"

def pm25_ind_cat(v):
    if pd.isna(v): return None
    v = float(v)
    if v <= 30:  return "good"
    if v <= 60:  return "satisfactory"
    if v <= 90:  return "moderate"
    if v <= 120: return "poor"
    if v <= 250: return "very poor"
    return "severe"

# ── Temporal / flag derivation ─────────────────────────────────────────────────
def _season(m):
    if m in (12,1,2):    return "winter"
    if m in (3,4,5):     return "summer"
    if m in (6,7,8,9):   return "monsoon"
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
    df["india_aqi_category"]  = df["india_aqi"].map(india_cat)
    df["us_aqi"]              = df["pm2_5_ugm3"].map(us_aqi)
    df["aqi_category"]        = df["us_aqi"].map(us_cat)
    df["pm25_category_india"] = df["pm2_5_ugm3"].map(pm25_ind_cat)
    return df

# ── DB helpers ────────────────────────────────────────────────────────────────
def _sv(v):
    if v is None: return None
    try:
        if math.isnan(float(v)): return None
    except (TypeError, ValueError): pass
    return v

def _sb(v):
    if v is None: return None
    if isinstance(v, (bool, np.bool_)): return bool(v)
    try:
        if math.isnan(float(v)): return None
    except (TypeError, ValueError): pass
    return bool(v)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("\n" + "=" * 68)
    print("  BreatheSafe — Complete Gap Data Fetcher")
    print(f"  Period  : {GAP_START}  to  {GAP_END}")
    print(f"  Cities  : {len(CITIES)}")
    print("  Weather : Open-Meteo Historical (no key)")
    print("  Pollutants: OpenAQ v3 (measured) + CAMS fallback (model)")
    print("=" * 68 + "\n")

    # ── Phase 1: Discover OpenAQ stations ────────────────────────────────────
    log.info("PHASE 1 — Discovering OpenAQ stations for India")
    try:
        city_sensors = discover_india_stations()
        log.info(f"  OpenAQ coverage: {len(city_sensors)}/{len(CITIES)} cities matched\n")
    except Exception as e:
        log.warning(f"  OpenAQ discovery failed ({e}) — will use CAMS for all cities")
        city_sensors = {}

    # ── Phase 2: Fetch per-city data ─────────────────────────────────────────
    log.info("PHASE 2 — Fetching data for each city")
    all_frames = []
    oaq_cities, cams_cities = [], []

    COL_ORDER = [
        "city","state","latitude","longitude","datetime",
        "month","day_name","is_weekend","season","time_of_day",
        "humidity_percent","dew_point_c","wind_gusts_kmh","precipitation_mm",
        "is_raining","heavy_rain","pressure_msl_hpa","cloud_cover_percent",
        "temperature_c","wind_speed_kmh",
        "pm2_5_ugm3","pm10_ugm3","co_ugm3","no2_ugm3","so2_ugm3","o3_ugm3",
        "dust_ugm3","aod",
        "us_aqi","india_aqi","india_aqi_category",
        "aqi_category","pm25_category_india",
        "festival_period","crop_burning_season",
    ]

    for i, (city, state, lat, lon) in enumerate(CITIES, 1):
        log.info(f"[{i:2d}/{len(CITIES)}] {city.title()}")

        # Weather (always Open-Meteo)
        try:
            df_w = fetch_weather(lat, lon)
            log.info(f"  Weather: {len(df_w)} hourly rows from Open-Meteo")
        except Exception as e:
            log.error(f"  Weather FAILED: {e} — skipping city")
            continue

        # Pollutants: OpenAQ if available, else CAMS
        df_aq = pd.DataFrame()
        source_tag = "CAMS"

        if city in city_sensors:
            log.info("  Pollutants: fetching from OpenAQ (measured data)")
            try:
                df_aq = fetch_openaq_pollutants(city, city_sensors[city]["sensors"])
                if len(df_aq) > 100:
                    source_tag = "OpenAQ"
                    oaq_cities.append(city)
                    log.info(f"  OpenAQ: {len(df_aq)} rows for {list(df_aq.columns)}")
                else:
                    log.warning(f"  OpenAQ returned too few rows ({len(df_aq)}) — falling back to CAMS")
                    df_aq = pd.DataFrame()
            except Exception as e:
                log.warning(f"  OpenAQ failed ({e}) — falling back to CAMS")
                df_aq = pd.DataFrame()

        if df_aq.empty:
            log.info("  Pollutants: fetching from Open-Meteo CAMS (model-based)")
            try:
                df_aq = fetch_cams_airquality(lat, lon)
                cams_cities.append(city)
                log.info(f"  CAMS: {len(df_aq)} rows")
            except Exception as e:
                log.error(f"  CAMS also failed: {e} — skipping city")
                continue

        # Merge weather + pollutants on datetime
        df = df_w.merge(df_aq, on="datetime", how="left")

        # Static columns
        df["city"]      = city
        df["state"]     = state
        df["latitude"]  = lat
        df["longitude"] = lon

        # Ensure dust and aod columns exist (may be missing if OpenAQ used)
        for col in ["dust_ugm3", "aod"]:
            if col not in df.columns:
                df[col] = np.nan

        # Derived fields
        df = add_derived(df, city)

        # Reorder columns
        df = df[[c for c in COL_ORDER if c in df.columns]]

        all_frames.append(df)
        log.info(f"  Done — {len(df):,} rows | source: {source_tag}\n")
        time.sleep(0.3)

    if not all_frames:
        log.error("No data fetched — check internet connection inside the container")
        sys.exit(1)

    # ── Phase 3: Combine ──────────────────────────────────────────────────────
    log.info("PHASE 3 — Combining all cities")
    new_df = pd.concat(all_frames, ignore_index=True)
    new_df.sort_values(["city", "datetime"], inplace=True)
    new_df.reset_index(drop=True, inplace=True)

    # Final column order (match original CSV exactly)
    new_df = new_df[[c for c in COL_ORDER if c in new_df.columns]]

    log.info(f"  Total new rows   : {len(new_df):,}")
    log.info(f"  OpenAQ cities    : {len(oaq_cities)} — {oaq_cities}")
    log.info(f"  CAMS fallback    : {len(cams_cities)} — {cams_cities}")

    # ── Phase 4: Append CSV ───────────────────────────────────────────────────
    log.info(f"\nPHASE 4 — Appending to CSV: {CSV_PATH}")
    existing_df = pd.read_csv(CSV_PATH)
    combined_df = pd.concat([existing_df, new_df], ignore_index=True)
    combined_df.to_csv(CSV_PATH, index=False)
    log.info(f"  CSV: {len(existing_df):,} existing + {len(new_df):,} new = {len(combined_df):,} total rows")

    # ── Phase 5: Insert into PostgreSQL ──────────────────────────────────────
    log.info("\nPHASE 5 — Inserting into PostgreSQL")
    engine  = create_engine(DATABASE_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    rows_db = session.execute(
        text("SELECT ms.id, c.name FROM monitoring_stations ms JOIN cities c ON c.id=ms.city_id")
    ).fetchall()
    station_id_map = {r[1].lower(): r[0] for r in rows_db}

    last_row = session.execute(text("SELECT MAX(datetime) FROM aqi_data")).fetchone()
    last_dt  = last_row[0] if last_row and last_row[0] else datetime(2025, 11, 26, 23, 0)
    log.info(f"  Last existing datetime in DB: {last_dt}")

    insert_df = new_df[new_df["datetime"] > pd.Timestamp(last_dt)].copy()
    log.info(f"  Rows to insert: {len(insert_df):,}")

    if insert_df.empty:
        log.info("  Nothing to insert — DB already up to date")
        session.close()
    else:
        t0 = time.time()
        inserted = 0
        total    = len(insert_df)
        batches  = math.ceil(total / BATCH_SIZE)

        for b, start in enumerate(range(0, total, BATCH_SIZE), 1):
            batch = insert_df.iloc[start: start + BATCH_SIZE]
            rows  = []
            for _, row in batch.iterrows():
                sid = station_id_map.get(str(row["city"]).lower().strip())
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

            elapsed = time.time() - t0
            rate    = inserted / elapsed if elapsed > 0 else 1
            eta     = (total - inserted) / rate
            print(f"  Batch {b:3d}/{batches} | {inserted:>7,}/{total:,} "
                  f"({100*inserted/total:5.1f}%) | {rate:,.0f} rows/s | ETA {eta:.0f}s",
                  end="\r", flush=True)

        print()
        session.close()
        elapsed = time.time() - t0

        print(f"\n{'=' * 68}")
        print("  COMPLETE")
        print(f"  Rows inserted into DB   : {inserted:,}")
        print(f"  CSV rows (total)        : {len(combined_df):,}")
        print(f"  Time taken              : {elapsed:.1f}s ({elapsed/60:.1f} min)")
        print(f"  OpenAQ (measured) cities: {len(oaq_cities)}")
        print(f"  CAMS fallback cities    : {len(cams_cities)}")
        print("\n  Run the model retraining to update forecasts:")
        print("  docker exec breathesafe_backend python /app/train_models.py --skip-prophet")
        print("=" * 68)


if __name__ == "__main__":
    main()
