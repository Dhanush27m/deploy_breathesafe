"""
BreatheSafe — Full CSV Data Migration Script
============================================
Loads the complete aqi_india_enriched.csv (Aug 2022 → Apr 2026, ~944k rows)
into Supabase (production) and/or the local dev PostgreSQL database.

REQUIREMENTS (run once):
    pip install psycopg2-binary pandas

USAGE:
    python load_csv_to_db.py                  # loads into Supabase only
    python load_csv_to_db.py --local          # loads into local dev DB only
    python load_csv_to_db.py --both           # loads into both

HOW IT WORKS:
    1. Reads the CSV
    2. Maps city name → station_id (queried from the target DB)
    3. Bulk-inserts in batches of 5,000 rows using COPY for speed
    4. Skips rows already present (ON CONFLICT DO NOTHING)
"""

import argparse
import io
import math
import os
import sys
import time
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Load .env file from the same directory as this script
load_dotenv(Path(__file__).parent / ".env")

# ── Connection strings (read from environment — never hardcoded) ──────────────
# Set these in your .env file:
#   SUPABASE_DATABASE_URL=postgresql://postgres.<project>:<password>@...
#   LOCAL_DEV_DATABASE_URL=postgresql://breathesafe:<password>@localhost:5432/breathesafe
#   LOCAL_DEPLOY_DATABASE_URL=postgresql://breathesafe:<password>@localhost:5434/breathesafe_deploy

def _require_env(var: str) -> str:
    val = os.getenv(var, "").strip()
    if not val:
        print(f"ERROR: {var} is not set. Add it to your .env file.")
        sys.exit(1)
    return val

SUPABASE_URL      = os.getenv("SUPABASE_DATABASE_URL", "")
LOCAL_DEV_URL     = os.getenv("LOCAL_DEV_DATABASE_URL", "")
LOCAL_DEPLOY_URL  = os.getenv("LOCAL_DEPLOY_DATABASE_URL", "")

# ── CSV path (read from env or auto-detect relative to this script) ───────────
CSV_PATH = os.getenv(
    "SEED_CSV_PATH",
    str(Path(__file__).parent / "data" / "aqi_india_enriched.csv")
)

# ── Column mapping: CSV column → DB column ───────────────────────────────────
# Only columns that exist in both CSV and DB aqi_data table
DB_COLS = [
    "station_id",        # mapped from city name
    "datetime",
    "pm2_5_ugm3",
    "pm10_ugm3",
    "co_ugm3",
    "no2_ugm3",
    "so2_ugm3",
    "o3_ugm3",
    "dust_ugm3",
    "aod",
    "us_aqi",
    "india_aqi",
    "india_aqi_category",
    "pm25_category_india",
    "temperature_c",
    "wind_speed_kmh",
    "wind_gusts_kmh",
    "humidity_percent",
    "dew_point_c",
    "pressure_msl_hpa",
    "cloud_cover_percent",
    "precipitation_mm",
    "is_raining",
    "heavy_rain",
    "month",
    "day_name",
    "is_weekend",
    "season",
    "time_of_day",
    "festival_period",
    "crop_burning_season",
]

CSV_TO_DB = {
    "pm2_5_ugm3":       "pm2_5_ugm3",
    "pm10_ugm3":        "pm10_ugm3",
    "co_ugm3":          "co_ugm3",
    "no2_ugm3":         "no2_ugm3",
    "so2_ugm3":         "so2_ugm3",
    "o3_ugm3":          "o3_ugm3",
    "dust_ugm3":        "dust_ugm3",
    "aod":              "aod",
    "us_aqi":           "us_aqi",
    "india_aqi":        "india_aqi",
    "india_aqi_category": "india_aqi_category",
    "pm25_category_india": "pm25_category_india",
    "temperature_c":    "temperature_c",
    "wind_speed_kmh":   "wind_speed_kmh",
    "wind_gusts_kmh":   "wind_gusts_kmh",
    "humidity_percent": "humidity_percent",
    "dew_point_c":      "dew_point_c",
    "pressure_msl_hpa": "pressure_msl_hpa",
    "cloud_cover_percent": "cloud_cover_percent",
    "precipitation_mm": "precipitation_mm",
    "is_raining":       "is_raining",
    "heavy_rain":       "heavy_rain",
    "month":            "month",
    "day_name":         "day_name",
    "is_weekend":       "is_weekend",
    "season":           "season",
    "time_of_day":      "time_of_day",
    "festival_period":  "festival_period",
    "crop_burning_season": "crop_burning_season",
}


def get_station_map(conn):
    """Returns {city_name_lower: station_id} from the DB."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT LOWER(c.name), ms.id
            FROM monitoring_stations ms
            JOIN cities c ON c.id = ms.city_id
        """)
        return {row[0]: row[1] for row in cur.fetchall()}


def load_csv(csv_path):
    """Read and prepare the CSV."""
    print(f"Reading CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    print(f"  Loaded {len(df):,} rows")

    # Parse datetime
    df["datetime"] = pd.to_datetime(df["datetime"], format="mixed", dayfirst=False)

    # Normalise city name
    df["city"] = df["city"].str.lower().str.strip()

    # Boolean columns — convert to proper bool
    for col in ["is_raining", "heavy_rain", "is_weekend", "festival_period", "crop_burning_season"]:
        if col in df.columns:
            df[col] = df[col].map({"True": True, "False": False, True: True, False: False}).fillna(False)

    return df


def insert_dataframe(conn, df, station_map, batch_size=5000):
    """Insert DataFrame rows into aqi_data in batches using executemany."""
    total = len(df)
    n_batches = math.ceil(total / batch_size)
    inserted = 0
    skipped_cities = set()

    col_str = ", ".join(DB_COLS)
    placeholders = ", ".join(["%s"] * len(DB_COLS))
    sql = f"""
        INSERT INTO aqi_data ({col_str})
        VALUES ({placeholders})
        ON CONFLICT DO NOTHING
    """

    with conn.cursor() as cur:
        for batch_idx in range(n_batches):
            chunk = df.iloc[batch_idx * batch_size : (batch_idx + 1) * batch_size]
            rows = []

            for _, row in chunk.iterrows():
                city = row["city"]
                station_id = station_map.get(city)
                if station_id is None:
                    skipped_cities.add(city)
                    continue

                record = [station_id, row["datetime"]]
                for csv_col in list(CSV_TO_DB.keys()):
                    val = row.get(csv_col)
                    if pd.isna(val):
                        record.append(None)
                    else:
                        record.append(val)
                rows.append(tuple(record))

            if rows:
                psycopg2.extras.execute_batch(cur, sql, rows, page_size=1000)
                conn.commit()
                inserted += len(rows)

            pct = (batch_idx + 1) / n_batches * 100
            print(f"  Batch {batch_idx+1}/{n_batches} ({pct:.0f}%) — {inserted:,} rows inserted", end="\r")

    print()  # newline after progress
    if skipped_cities:
        print(f"  Skipped cities not in DB: {skipped_cities}")

    return inserted


def run_migration(db_url, db_label, df):
    print(f"\n{'='*60}")
    print(f"Connecting to: {db_label}")
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = False
    except Exception as e:
        print(f"  ERROR connecting: {e}")
        return

    station_map = get_station_map(conn)
    print(f"  Found {len(station_map)} stations in DB: {sorted(station_map.keys())}")

    # Check existing data
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM aqi_data")
        existing = cur.fetchone()[0]
    print(f"  Existing rows in aqi_data: {existing:,}")

    if existing > 0:
        confirm = input(f"  aqi_data already has {existing:,} rows. Clear and reload? [y/N]: ").strip().lower()
        if confirm == "y":
            with conn.cursor() as cur:
                cur.execute("DELETE FROM aqi_data")
            conn.commit()
            print("  Cleared existing data.")
        else:
            print("  Inserting new rows only (skipping duplicates).")

    t0 = time.time()
    n = insert_dataframe(conn, df, station_map)
    elapsed = time.time() - t0
    print(f"  Done: {n:,} rows inserted in {elapsed:.1f}s")

    # Verify
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*), MIN(datetime), MAX(datetime) FROM aqi_data")
        row = cur.fetchone()
    print(f"  Final: {row[0]:,} rows | {row[1]} → {row[2]}")
    conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true", help="Load into local dev DB")
    parser.add_argument("--local-deploy", action="store_true", help="Load into local deploy DB")
    parser.add_argument("--supabase", action="store_true", help="Load into Supabase (default)")
    parser.add_argument("--both", action="store_true", help="Load into Supabase + local dev")
    args = parser.parse_args()

    df = load_csv(CSV_PATH)

    if args.local:
        if not LOCAL_DEV_URL:
            print("ERROR: LOCAL_DEV_DATABASE_URL not set in .env"); sys.exit(1)
        run_migration(LOCAL_DEV_URL, "Local Dev DB (port 5432)", df)
    elif args.local_deploy:
        if not LOCAL_DEPLOY_URL:
            print("ERROR: LOCAL_DEPLOY_DATABASE_URL not set in .env"); sys.exit(1)
        run_migration(LOCAL_DEPLOY_URL, "Local Deploy DB (port 5434)", df)
    elif args.both:
        if not SUPABASE_URL or not LOCAL_DEV_URL:
            print("ERROR: SUPABASE_DATABASE_URL and LOCAL_DEV_DATABASE_URL must both be set in .env"); sys.exit(1)
        run_migration(SUPABASE_URL, "Supabase", df)
        run_migration(LOCAL_DEV_URL, "Local Dev DB (port 5432)", df)
    else:
        # Default: Supabase
        if not SUPABASE_URL:
            print("ERROR: SUPABASE_DATABASE_URL not set in .env"); sys.exit(1)
        run_migration(SUPABASE_URL, "Supabase", df)


if __name__ == "__main__":
    main()
