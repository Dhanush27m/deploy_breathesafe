"""
BreatheSafe — Export DB rows to CSV
=====================================
Reads rows from aqi_data that are newer than the CSV's last datetime,
then appends them to the master CSV file.

Usage (run inside the backend container):
    docker exec breathesafe_backend python /app/export_db_to_csv.py
"""

import os, sys, logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/app")
os.environ.setdefault("SEED_CSV_PATH", "/app/data/aqi_india_enriched.csv")
if not os.environ.get("DATABASE_URL"):
    print("ERROR: DATABASE_URL environment variable is not set.")
    print("Set it in your .env file or Render/Docker environment.")
    sys.exit(1)

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

import pandas as pd
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ["DATABASE_URL"]
CSV_PATH     = Path(os.environ["SEED_CSV_PATH"])

def main():
    print("\n" + "=" * 60)
    print("  BreatheSafe — DB → CSV Exporter")
    print("=" * 60)

    if not CSV_PATH.exists():
        print(f"ERROR: CSV not found at {CSV_PATH}")
        sys.exit(1)

    # Find last datetime in CSV
    existing = pd.read_csv(CSV_PATH)
    last_csv_dt = pd.to_datetime(existing["datetime"]).max()
    existing_rows = len(existing)
    print(f"  CSV rows          : {existing_rows:,}")
    print(f"  CSV last datetime : {last_csv_dt}")

    # Pull new rows from DB
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.connect() as conn:
        db_last = conn.execute(text("SELECT MAX(datetime) FROM aqi_data")).fetchone()[0]
        print(f"  DB  last datetime : {db_last}")

    if db_last is None or db_last <= last_csv_dt.to_pydatetime():
        print("\n  CSV is already up to date with DB. Nothing to export.")
        return

    print(f"\n  Exporting rows from {last_csv_dt} → {db_last} ...")

    query = text("""
        SELECT
            c.name          AS city,
            c.state,
            ms.latitude,
            ms.longitude,
            a.datetime,
            a.month,
            a.day_name,
            a.is_weekend,
            a.season,
            a.time_of_day,
            a.humidity_percent,
            a.dew_point_c,
            a.wind_gusts_kmh,
            a.precipitation_mm,
            a.is_raining,
            a.heavy_rain,
            a.pressure_msl_hpa,
            a.cloud_cover_percent,
            a.temperature_c,
            a.wind_speed_kmh,
            a.pm2_5_ugm3,
            a.pm10_ugm3,
            a.co_ugm3,
            a.no2_ugm3,
            a.so2_ugm3,
            a.o3_ugm3,
            a.dust_ugm3,
            a.aod,
            a.us_aqi,
            a.india_aqi,
            a.india_aqi_category,
            a.pm25_category_india,
            a.festival_period,
            a.crop_burning_season
        FROM aqi_data a
        JOIN monitoring_stations ms ON ms.id = a.station_id
        JOIN cities c ON c.id = ms.city_id
        WHERE a.datetime > :last_dt
        ORDER BY c.name, a.datetime
    """)

    with engine.connect() as conn:
        new_df = pd.read_sql(query, conn, params={"last_dt": last_csv_dt})

    if new_df.empty:
        print("  No new rows found in DB after last CSV datetime.")
        return

    # Derive aqi_category from us_aqi (not stored in DB, matches original CSV)
    def _us_cat(aqi):
        import math
        try:
            if aqi is None or math.isnan(float(aqi)): return None
        except (TypeError, ValueError):
            return None
        aqi = float(aqi)
        if aqi <= 50:  return "Good"
        if aqi <= 100: return "Moderate"
        if aqi <= 150: return "Unhealthy for Sensitive Groups"
        if aqi <= 200: return "Unhealthy"
        if aqi <= 300: return "Very Unhealthy"
        return "Hazardous"

    new_df.insert(
        new_df.columns.get_loc("pm25_category_india"),
        "aqi_category",
        new_df["us_aqi"].map(_us_cat),
    )

    print(f"  New rows to append : {len(new_df):,}")

    # Write ONLY the new rows (no header) to a small append file
    # This avoids touching the locked original CSV at all
    append_path = CSV_PATH.parent / "aqi_rows_to_append.csv"
    new_df.to_csv(append_path, index=False, header=False)

    print(f"\n  Written {len(new_df):,} new rows (no header) to: {append_path}")
    print(f"\n  *** NEXT STEP — run in PowerShell ***")
    print(r"  $d = 'C:\Users\<your-username>\path\to\breathesafe\data'")
    print(r"  Get-Content $d\aqi_rows_to_append.csv | Add-Content $d\aqi_india_enriched.csv")
    print(r"  Remove-Item $d\aqi_rows_to_append.csv")
    print(r"  Remove-Item $d\aqi_india_enriched_updated.csv")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
