"""
sync_csv.py — BreatheSafe CSV Sync Tool
========================================
Pulls new AQI rows from Supabase and appends them to the local
training CSV (aqi_india_enriched.csv), keeping it fully up to date.

Usage (run from deploy_breathesafe/ folder):
    python sync_csv.py                    # append new rows only
    python sync_csv.py --dry-run          # show what would be added, don't write
    python sync_csv.py --verbose          # show per-city row counts

Requirements:
    pip install psycopg2-binary pandas python-dotenv
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# ── Load .env file from the same directory as this script ─────────────────────
SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / ".env")

CSV_PATH = Path(os.getenv("SEED_CSV_PATH", str(SCRIPT_DIR / "data" / "aqi_india_enriched.csv")))

# ── Supabase connection string (from environment only — never hardcoded) ───────
# Set SUPABASE_DATABASE_URL in your .env file:
#   SUPABASE_DATABASE_URL=postgresql://postgres.<project>:<password>@...pooler.supabase.com:5432/postgres
SUPABASE_URL = os.getenv("SUPABASE_DATABASE_URL", "").strip()
if not SUPABASE_URL:
    print("ERROR: SUPABASE_DATABASE_URL is not set.")
    print("Add it to your .env file next to sync_csv.py and re-run.")
    sys.exit(1)

# ── CSV column order (must match aqi_india_enriched.csv exactly) ───────────────
CSV_COLUMNS = [
    "city", "state", "latitude", "longitude", "datetime",
    "month", "day_name", "is_weekend", "season", "time_of_day",
    "humidity_percent", "dew_point_c", "wind_gusts_kmh", "precipitation_mm",
    "is_raining", "heavy_rain", "pressure_msl_hpa", "cloud_cover_percent",
    "temperature_c", "wind_speed_kmh",
    "pm2_5_ugm3", "pm10_ugm3", "co_ugm3", "no2_ugm3", "so2_ugm3", "o3_ugm3",
    "dust_ugm3", "aod",
    "us_aqi", "india_aqi", "india_aqi_category",
    "aqi_category",          # US AQI category (derived from us_aqi)
    "pm25_category_india",
    "festival_period", "crop_burning_season",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def us_aqi_category(aqi_val):
    """Convert numeric US AQI to its category string."""
    if aqi_val is None:
        return None
    v = float(aqi_val)
    if v <= 50:   return "Good"
    if v <= 100:  return "Moderate"
    if v <= 150:  return "Unhealthy for Sensitive Groups"
    if v <= 200:  return "Unhealthy"
    if v <= 300:  return "Very Unhealthy"
    return "Hazardous"


def get_last_csv_datetime() -> datetime:
    """Read the CSV and return the latest datetime found."""
    import pandas as pd

    if not CSV_PATH.exists():
        raise FileNotFoundError(f"CSV not found: {CSV_PATH}")

    print(f"Reading CSV: {CSV_PATH}")
    # Use mixed format to handle both '%m/%d/%Y %H:%M' and '%Y-%m-%d %H:%M:%S'
    df = pd.read_csv(CSV_PATH, usecols=["datetime"])
    df["datetime"] = pd.to_datetime(df["datetime"], format="mixed", dayfirst=False)
    last_dt = df["datetime"].max()
    print(f"Last CSV datetime : {last_dt}")
    return last_dt.to_pydatetime()


def fetch_new_rows(last_dt: datetime, verbose: bool = False):
    """Query Supabase for all aqi_data rows newer than last_dt."""
    import psycopg2
    import psycopg2.extras

    db_url = os.environ.get("SUPABASE_DATABASE_URL", SUPABASE_URL)
    print(f"Connecting to Supabase…")
    conn = psycopg2.connect(db_url)
    cur  = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    query = """
        SELECT
            c.name            AS city,
            c.state           AS state,
            c.latitude        AS latitude,
            c.longitude       AS longitude,
            a.datetime        AS datetime,
            a.month           AS month,
            a.day_name        AS day_name,
            a.is_weekend      AS is_weekend,
            a.season          AS season,
            a.time_of_day     AS time_of_day,
            a.humidity_percent    AS humidity_percent,
            a.dew_point_c         AS dew_point_c,
            a.wind_gusts_kmh      AS wind_gusts_kmh,
            a.precipitation_mm    AS precipitation_mm,
            a.is_raining          AS is_raining,
            a.heavy_rain          AS heavy_rain,
            a.pressure_msl_hpa    AS pressure_msl_hpa,
            a.cloud_cover_percent AS cloud_cover_percent,
            a.temperature_c       AS temperature_c,
            a.wind_speed_kmh      AS wind_speed_kmh,
            a.pm2_5_ugm3  AS pm2_5_ugm3,
            a.pm10_ugm3   AS pm10_ugm3,
            a.co_ugm3     AS co_ugm3,
            a.no2_ugm3    AS no2_ugm3,
            a.so2_ugm3    AS so2_ugm3,
            a.o3_ugm3     AS o3_ugm3,
            a.dust_ugm3   AS dust_ugm3,
            a.aod         AS aod,
            a.us_aqi              AS us_aqi,
            a.india_aqi           AS india_aqi,
            a.india_aqi_category  AS india_aqi_category,
            a.pm25_category_india AS pm25_category_india,
            a.festival_period     AS festival_period,
            a.crop_burning_season AS crop_burning_season
        FROM aqi_data a
        JOIN monitoring_stations ms ON a.station_id = ms.id
        JOIN cities c               ON ms.city_id   = c.id
        WHERE a.datetime > %s
        ORDER BY c.name, a.datetime
    """

    print(f"Fetching rows newer than {last_dt} …")
    cur.execute(query, (last_dt,))
    rows = cur.fetchall()
    conn.close()

    print(f"Rows fetched from Supabase: {len(rows):,}")

    if verbose and rows:
        from collections import Counter
        city_counts = Counter(r["city"] for r in rows)
        for city, cnt in sorted(city_counts.items()):
            print(f"  {city:20s}: {cnt:,} rows")

    return rows


def build_dataframe(rows):
    """Convert psycopg2 DictRow list → pandas DataFrame with correct columns."""
    import pandas as pd

    records = []
    for r in rows:
        rec = {
            "city":                r["city"],
            "state":               r["state"],
            "latitude":            r["latitude"],
            "longitude":           r["longitude"],
            "datetime":            r["datetime"],
            "month":               r["month"],
            "day_name":            r["day_name"],
            "is_weekend":          r["is_weekend"],
            "season":              r["season"],
            "time_of_day":         r["time_of_day"],
            "humidity_percent":    r["humidity_percent"],
            "dew_point_c":         r["dew_point_c"],
            "wind_gusts_kmh":      r["wind_gusts_kmh"],
            "precipitation_mm":    r["precipitation_mm"],
            "is_raining":          r["is_raining"],
            "heavy_rain":          r["heavy_rain"],
            "pressure_msl_hpa":    r["pressure_msl_hpa"],
            "cloud_cover_percent": r["cloud_cover_percent"],
            "temperature_c":       r["temperature_c"],
            "wind_speed_kmh":      r["wind_speed_kmh"],
            "pm2_5_ugm3":          r["pm2_5_ugm3"],
            "pm10_ugm3":           r["pm10_ugm3"],
            "co_ugm3":             r["co_ugm3"],
            "no2_ugm3":            r["no2_ugm3"],
            "so2_ugm3":            r["so2_ugm3"],
            "o3_ugm3":             r["o3_ugm3"],
            "dust_ugm3":           r["dust_ugm3"],
            "aod":                 r["aod"],
            "us_aqi":              r["us_aqi"],
            "india_aqi":           r["india_aqi"],
            "india_aqi_category":  r["india_aqi_category"],
            "aqi_category":        us_aqi_category(r["us_aqi"]),   # derived
            "pm25_category_india": r["pm25_category_india"],
            "festival_period":     r["festival_period"],
            "crop_burning_season": r["crop_burning_season"],
        }
        records.append(rec)

    df = pd.DataFrame(records, columns=CSV_COLUMNS)

    # Format datetime exactly like the existing CSV rows (YYYY-MM-DD HH:MM:SS)
    df["datetime"] = pd.to_datetime(df["datetime"]).dt.strftime("%Y-%m-%d %H:%M:%S")

    return df


def append_to_csv(df):
    """Append new rows to the CSV without rewriting the whole file."""
    # append mode, no header, same encoding
    df.to_csv(CSV_PATH, mode="a", header=False, index=False)
    print(f"✓ Appended {len(df):,} rows to {CSV_PATH}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Sync Supabase → local CSV")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Show what would be added without writing")
    parser.add_argument("--verbose",  action="store_true",
                        help="Print per-city row counts")
    args = parser.parse_args()

    # Optional: load .env from script directory
    try:
        from dotenv import load_dotenv
        env_file = SCRIPT_DIR / ".env.sync"
        if env_file.exists():
            load_dotenv(env_file)
            print(f"Loaded env: {env_file}")
    except ImportError:
        pass

    try:
        last_dt = get_last_csv_datetime()
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    rows = fetch_new_rows(last_dt, verbose=args.verbose)

    if not rows:
        print("CSV is already up to date. Nothing to append.")
        return

    import pandas as pd
    df = build_dataframe(rows)

    print(f"\nDate range of new rows: {df['datetime'].min()}  →  {df['datetime'].max()}")
    print(f"Cities with new data  : {df['city'].nunique()}")
    print(f"Total rows to append  : {len(df):,}")

    if args.dry_run:
        print("\n[dry-run] No changes written.")
        return

    append_to_csv(df)
    print("\nDone! CSV is now up to date.")
    print("Re-run at any time to pull the latest data from Supabase.")
    print("Tip: schedule this script to run daily for automatic updates.")


if __name__ == "__main__":
    main()
