"""
BreatheSafe — Dataset Enrichment Script
========================================
Adds 3 missing columns to the base CSV:
  1. temperature_c   — from Open-Meteo historical API (free, no key needed)
  2. wind_speed_kmh  — from Open-Meteo historical API
  3. india_aqi       — computed from PM2.5/PM10/NO2/SO2/CO/O3 using CPCB formula

Usage:
    python enrich_dataset.py \
        --input  aqi_india_38cols_knn_final.csv \
        --output aqi_india_enriched.csv

Runtime: ~10–20 min (fetches 29 cities × 3.3 years of hourly data from Open-Meteo)
"""

import argparse
import sys
import time
import requests
import pandas as pd
import numpy as np
from pathlib import Path

# ── City coordinates (matches CSV city names exactly) ─────────────────────────
CITY_COORDS = {
    "agartala":          (23.8315,  91.2868),
    "aizawl":            (23.7271,  92.7176),
    "ahmedabad":         (23.0225,  72.5714),
    "bengaluru":         (12.9716,  77.5946),
    "bhopal":            (23.2599,  77.4126),
    "bhubaneswar":       (20.2961,  85.8245),
    "chandigarh":        (30.7333,  76.7794),
    "chennai":           (13.0827,  80.2707),
    "dehradun":          (30.3165,  78.0322),
    "delhi":             (28.6139,  77.2090),
    "gangtok":           (27.3389,  88.6065),
    "guwahati":          (26.1445,  91.7362),
    "gurugram":          (28.4595,  77.0266),
    "hyderabad":         (17.3850,  78.4867),
    "imphal":            (24.8170,  93.9368),
    "itanagar":          (27.0844,  93.6053),
    "jaipur":            (26.9124,  75.7873),
    "kohima":            (25.6747,  94.1086),
    "kolkata":           (22.5726,  88.3639),
    "lucknow":           (26.8467,  80.9462),
    "mumbai":            (19.0760,  72.8777),
    "panaji":            (15.4989,  73.8278),
    "patna":             (25.5941,  85.1376),
    "raipur":            (21.2514,  81.6296),
    "ranchi":            (23.3441,  85.3096),
    "shillong":          (25.5788,  91.8933),
    "shimla":            (31.1048,  77.1734),
    "thiruvananthapuram":(8.5241,   76.9366),
    "visakhapatnam":     (17.6868,  83.2185),
}

# ── CPCB AQI Breakpoints ───────────────────────────────────────────────────────
# Each entry: (conc_low, conc_high, aqi_low, aqi_high)
BREAKPOINTS = {
    "pm25": [
        (0,    30,   0,   50),
        (30,   60,  51,  100),
        (60,   90, 101,  200),
        (90,  120, 201,  300),
        (120, 250, 301,  400),
        (250, 999, 401,  500),
    ],
    "pm10": [
        (0,    50,   0,   50),
        (50,  100,  51,  100),
        (100, 250, 101,  200),
        (250, 350, 201,  300),
        (350, 430, 301,  400),
        (430, 999, 401,  500),
    ],
    "no2": [
        (0,    40,   0,   50),
        (40,   80,  51,  100),
        (80,  180, 101,  200),
        (180, 280, 201,  300),
        (280, 400, 301,  400),
        (400, 999, 401,  500),
    ],
    "so2": [
        (0,    40,   0,   50),
        (40,   80,  51,  100),
        (80,  380, 101,  200),
        (380, 800, 201,  300),
        (800,1600, 301,  400),
        (1600,9999,401,  500),
    ],
    "co": [
        # CO in CSV is µg/m³
        (0,    1000,   0,   50),
        (1000, 2000,  51,  100),
        (2000,10000, 101,  200),
        (10000,17000,201,  300),
        (17000,34000,301,  400),
        (34000,99999,401,  500),
    ],
    "o3": [
        (0,    50,   0,   50),
        (50,  100,  51,  100),
        (100, 168, 101,  200),
        (168, 208, 201,  300),
        (208, 748, 301,  400),
        (748, 9999,401,  500),
    ],
}

INDIA_AQI_CATEGORIES = [
    (0,   50,  "Good"),
    (51,  100, "Satisfactory"),
    (101, 200, "Moderately Polluted"),
    (201, 300, "Poor"),
    (301, 400, "Very Poor"),
    (401, 500, "Severe"),
]


def linear_interpolate(conc, bp_list):
    """Compute AQI sub-index for a pollutant concentration using CPCB breakpoints."""
    if pd.isna(conc) or conc < 0:
        return np.nan
    for (c_lo, c_hi, aqi_lo, aqi_hi) in bp_list:
        if c_lo <= conc <= c_hi:
            return aqi_lo + (conc - c_lo) * (aqi_hi - aqi_lo) / (c_hi - c_lo)
    # Beyond highest breakpoint
    return 500.0


def compute_india_aqi(row):
    """Compute India AQI for a single row using CPCB worst-pollutant method."""
    sub_indices = []
    mapping = {
        "pm25": "pm2_5_ugm3",
        "pm10": "pm10_ugm3",
        "no2":  "no2_ugm3",
        "so2":  "so2_ugm3",
        "co":   "co_ugm3",
        "o3":   "o3_ugm3",
    }
    for pollutant, col in mapping.items():
        val = row.get(col, np.nan)
        si = linear_interpolate(val, BREAKPOINTS[pollutant])
        if not np.isnan(si):
            sub_indices.append(si)

    if not sub_indices:
        return np.nan
    return round(max(sub_indices), 1)


def aqi_to_category(aqi):
    """Map numeric India AQI to category string."""
    if pd.isna(aqi):
        return "Unknown"
    for lo, hi, cat in INDIA_AQI_CATEGORIES:
        if lo <= aqi <= hi:
            return cat
    return "Severe"


def fetch_meteo_for_city(city, lat, lon, start_date, end_date, retries=3):
    """
    Fetch hourly temperature + wind speed from Open-Meteo historical API.
    Free, no API key required.
    Returns a DataFrame indexed by datetime.
    """
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude":  lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date":   end_date,
        "hourly":    "temperature_2m,wind_speed_10m",
        "timezone":  "Asia/Kolkata",
        "wind_speed_unit": "kmh",
    }

    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            hourly = data["hourly"]
            df = pd.DataFrame({
                "datetime":       pd.to_datetime(hourly["time"]),
                "temperature_c":  hourly["temperature_2m"],
                "wind_speed_kmh": hourly["wind_speed_10m"],
            })
            df.set_index("datetime", inplace=True)
            return df
        except Exception as e:
            print(f"  ⚠️  Attempt {attempt+1}/{retries} failed for {city}: {e}")
            time.sleep(5 * (attempt + 1))

    print(f"  ❌ All retries failed for {city}. Filling with NaN.")
    return None


def enrich(input_path: str, output_path: str):
    print(f"\n{'='*60}")
    print(f"  BreatheSafe Dataset Enrichment")
    print(f"{'='*60}")
    print(f"  Input  : {input_path}")
    print(f"  Output : {output_path}\n")

    # ── Load base CSV ──────────────────────────────────────────────────────────
    print("📂 Loading base CSV...")
    df = pd.read_csv(input_path, parse_dates=["datetime"])
    print(f"   Loaded {len(df):,} rows × {len(df.columns)} columns")

    start_date = df["datetime"].min().strftime("%Y-%m-%d")
    end_date   = df["datetime"].max().strftime("%Y-%m-%d")
    print(f"   Date range: {start_date} → {end_date}")

    cities = sorted(df["city"].unique())
    print(f"   Cities: {len(cities)}")

    # ── Step 1: Fetch temperature + wind speed per city ────────────────────────
    print(f"\n🌡️  Fetching temperature & wind speed from Open-Meteo...")
    print(f"   (free API, no key needed — ~{len(cities)} requests)\n")

    meteo_frames = []
    for i, city in enumerate(cities, 1):
        if city not in CITY_COORDS:
            print(f"  [{i:2}/{len(cities)}] {city:20s} — ⚠️  No coordinates, skipping")
            continue

        lat, lon = CITY_COORDS[city]
        print(f"  [{i:2}/{len(cities)}] {city:20s} (lat={lat}, lon={lon})...", end=" ", flush=True)
        meteo_df = fetch_meteo_for_city(city, lat, lon, start_date, end_date)

        if meteo_df is not None:
            meteo_df["city"] = city
            meteo_frames.append(meteo_df.reset_index())
            print(f"✅ {len(meteo_df):,} rows")
        else:
            print("❌ Failed")

        time.sleep(1)  # polite rate limiting

    # ── Merge meteo data ───────────────────────────────────────────────────────
    print(f"\n🔗 Merging weather data...")

    # Drop pre-existing placeholder columns if present (avoids _x/_y rename conflict)
    for _col in ["temperature_c", "wind_speed_kmh"]:
        if _col in df.columns:
            df.drop(columns=[_col], inplace=True)

    if meteo_frames:
        meteo_combined = pd.concat(meteo_frames, ignore_index=True)
        meteo_combined["datetime"] = pd.to_datetime(meteo_combined["datetime"]).dt.floor("h")
        df["datetime"] = pd.to_datetime(df["datetime"]).dt.floor("h")

        df = df.merge(
            meteo_combined[["city", "datetime", "temperature_c", "wind_speed_kmh"]],
            on=["city", "datetime"],
            how="left",
        )
        filled = df["temperature_c"].notna().sum()
        print(f"   Merged: {filled:,}/{len(df):,} rows have temperature data "
              f"({100*filled/len(df):.1f}%)")
    else:
        df["temperature_c"]  = np.nan
        df["wind_speed_kmh"] = np.nan
        print("   ⚠️  No meteo data fetched — columns added as NaN")

    # ── Step 2: Compute India AQI ──────────────────────────────────────────────
    print(f"\n🇮🇳 Computing India AQI (CPCB standard)...")
    df["india_aqi"] = df.apply(compute_india_aqi, axis=1)
    df["india_aqi_category"] = df["india_aqi"].apply(aqi_to_category)

    valid = df["india_aqi"].notna().sum()
    print(f"   Computed: {valid:,}/{len(df):,} rows ({100*valid/len(df):.1f}%)")
    print(f"\n   India AQI distribution:")
    print(df["india_aqi_category"].value_counts().to_string(index=True))

    # ── Step 3: Column ordering ────────────────────────────────────────────────
    # Insert new columns right after cloud_cover_percent (column 17)
    cols = list(df.columns)
    insert_after = "cloud_cover_percent"
    if insert_after in cols:
        idx = cols.index(insert_after) + 1
        for new_col in ["temperature_c", "wind_speed_kmh"]:
            if new_col in cols:
                cols.remove(new_col)
                cols.insert(idx, new_col)
                idx += 1
    # india_aqi columns go after us_aqi
    if "us_aqi" in cols:
        idx2 = cols.index("us_aqi") + 1
        for new_col in ["india_aqi", "india_aqi_category"]:
            if new_col in cols:
                cols.remove(new_col)
                cols.insert(idx2, new_col)
                idx2 += 1
    df = df[cols]

    # ── Save (atomic write via temp file to avoid permission/lock errors) ────────
    print(f"\n💾 Saving enriched dataset...")
    output_path = Path(output_path)
    tmp_path = output_path.with_suffix(".tmp.csv")

    try:
        df.to_csv(tmp_path, index=False)
        # Atomic replace — removes lock conflict when output == input
        if output_path.exists():
            output_path.unlink()
        tmp_path.rename(output_path)
    except PermissionError:
        # Fallback: save with _enriched suffix next to the original
        fallback = output_path.with_stem(output_path.stem + "_enriched")
        df.to_csv(fallback, index=False)
        print(f"  ⚠️  Could not write to {output_path.name} (file locked).")
        print(f"  ✅ Saved to fallback: {fallback.name}")
        output_path = fallback

    print(f"\n{'='*60}")
    print(f"  ✅ Enrichment complete!")
    print(f"  Output : {output_path}")
    print(f"  Rows   : {len(df):,}")
    print(f"  Columns: {len(df.columns)}")
    print(f"  New    : temperature_c, wind_speed_kmh, india_aqi, india_aqi_category")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enrich BreatheSafe AQI dataset")
    parser.add_argument("--input",  default="aqi_india_38cols_knn_final.csv",
                        help="Path to original CSV")
    parser.add_argument("--output", default="aqi_india_enriched.csv",
                        help="Path for enriched output CSV")
    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"❌ Input file not found: {args.input}")
        sys.exit(1)

    enrich(args.input, args.output)
