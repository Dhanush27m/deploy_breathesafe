"""
BreatheSafe — Seed Recent AQI Data
====================================
Inserts the LAST 30 days of data per city from the master CSV into the
aqi_data table.  This gives:
  • Current readings for the dashboard         (~21k rows total)
  • 14-day lookback window for XGBoost forecasts
  • 90-day history for trend/pollutant analysis

This replaces the old approach of loading the ENTIRE 944k-row training
dataset into Supabase.  Run this ONCE after a fresh deploy, or whenever
the aqi_data table is empty.

USAGE (inside the backend container, or locally pointing at the DB):
    python seed_recent.py                   # seeds last 30 days
    python seed_recent.py --days 60         # seeds last 60 days
    python seed_recent.py --force           # clears + re-seeds even if rows exist

The scheduler's pipeline_hourly_job will keep the table fresh from here on.
The scheduler's cleanup_job will delete rows older than 90 days automatically.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# ── Config ─────────────────────────────────────────────────────────────────────
CSV_PATH   = os.getenv("CSV_PATH",     "/app/data/aqi_india_enriched.csv")
DB_URL     = os.getenv("DATABASE_URL", "")
BATCH_SIZE = 500          # rows per INSERT commit

if not DB_URL:
    print("ERROR: DATABASE_URL environment variable is not set.")
    print("Set it in your .env file or Render/Docker environment.")
    sys.exit(1)

# ── Column mapping (CSV col → DB col) ─────────────────────────────────────────
DB_COLS = [
    "station_id", "datetime",
    "pm2_5_ugm3", "pm10_ugm3", "co_ugm3", "no2_ugm3", "so2_ugm3",
    "o3_ugm3", "dust_ugm3", "aod", "us_aqi", "india_aqi",
    "india_aqi_category", "pm25_category_india",
    "temperature_c", "wind_speed_kmh", "wind_gusts_kmh",
    "humidity_percent", "dew_point_c", "pressure_msl_hpa",
    "cloud_cover_percent", "precipitation_mm",
    "is_raining", "heavy_rain",
    "month", "day_name", "is_weekend",
    "season", "time_of_day", "festival_period", "crop_burning_season",
]

CSV_METRIC_COLS = [c for c in DB_COLS if c not in ("station_id", "datetime")]


def get_station_map(engine) -> dict:
    """Return {city_name_lower: station_id} queried from the DB."""
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT LOWER(c.name), ms.id "
            "FROM monitoring_stations ms "
            "JOIN cities c ON c.id = ms.city_id"
        )).fetchall()
    return {r[0]: r[1] for r in rows}


def existing_row_count(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM aqi_data")).scalar()


def load_recent_csv(csv_path: str, days: int) -> pd.DataFrame:
    """Read CSV and return only the last `days` days per city."""
    print(f"  Reading CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    print(f"  Loaded {len(df):,} total rows from CSV")

    # Parse mixed datetime formats
    df["datetime"] = pd.to_datetime(
        df["datetime"], format="mixed", dayfirst=False, errors="coerce"
    )
    df = df.dropna(subset=["datetime"])

    # Normalise city names
    df["city"] = df["city"].str.lower().str.strip()

    # Boolean columns
    bool_cols = ["is_raining", "heavy_rain", "is_weekend", "festival_period", "crop_burning_season"]
    for col in bool_cols:
        if col in df.columns:
            df[col] = df[col].map(
                {True: True, False: False, "True": True, "False": False, 1: True, 0: False}
            ).fillna(False).astype(bool)

    # Keep only the last `days` days per city
    cutoff = df["datetime"].max() - timedelta(days=days)
    df = df[df["datetime"] >= cutoff]
    print(f"  After filtering last {days} days: {len(df):,} rows "
          f"({df['city'].nunique()} cities)")
    return df


def insert_rows(engine, df: pd.DataFrame, station_map: dict) -> int:
    """Bulk-insert rows into aqi_data using SQLAlchemy core."""
    Session = sessionmaker(bind=engine)
    session = Session()

    col_str = ", ".join(DB_COLS)
    placeholders = ", ".join([f":{c}" for c in DB_COLS])
    upsert_sql = text(
        f"INSERT INTO aqi_data ({col_str}) VALUES ({placeholders}) "
        "ON CONFLICT DO NOTHING"
    )

    inserted = 0
    skipped_cities: set = set()
    batch = []

    def _flush(batch):
        if batch:
            session.execute(upsert_sql, batch)
            session.commit()

    for _, row in df.iterrows():
        city    = str(row["city"]).lower().strip()
        sid     = station_map.get(city)
        if sid is None:
            skipped_cities.add(city)
            continue

        record = {"station_id": sid, "datetime": row["datetime"]}
        for col in CSV_METRIC_COLS:
            v = row.get(col)
            if isinstance(v, float) and pd.isna(v):
                record[col] = None
            else:
                record[col] = v
        batch.append(record)

        if len(batch) >= BATCH_SIZE:
            _flush(batch)
            inserted += len(batch)
            batch = []

    _flush(batch)
    inserted += len(batch)

    session.close()

    if skipped_cities:
        print(f"  ⚠️  Skipped cities not found in DB: {skipped_cities}")

    return inserted


def main():
    parser = argparse.ArgumentParser(
        description="Seed aqi_data with recent rows from master CSV."
    )
    parser.add_argument(
        "--days", type=int, default=30,
        help="How many days of recent data to seed (default: 30)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Clear existing aqi_data rows and re-seed even if rows exist"
    )
    parser.add_argument(
        "--db-url", type=str, default=None,
        help="Override DATABASE_URL (otherwise uses env var)"
    )
    parser.add_argument(
        "--csv", type=str, default=None,
        help="Override CSV_PATH"
    )
    args = parser.parse_args()

    db_url   = args.db_url  or DB_URL
    csv_path = args.csv     or CSV_PATH

    print(f"\n{'='*60}")
    print(f"  BreatheSafe — Seed Recent AQI Data")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    print(f"  CSV:     {csv_path}")
    print(f"  DB:      {db_url[:40]}...")
    print(f"  Days:    {args.days}")
    print(f"  Force:   {args.force}")
    print()

    if not os.path.exists(csv_path):
        print(f"⚠️   CSV not found: {csv_path}")
        print("    Skipping initial seed — the hourly pipeline will populate")
        print("    aqi_data automatically once the scheduler starts.")
        print("    To seed manually: mount the CSV and re-run seed_recent.py")
        sys.exit(0)

    engine = create_engine(db_url, pool_pre_ping=True)

    # ── Check existing rows ────────────────────────────────────────────────────
    existing = existing_row_count(engine)
    print(f"  Current aqi_data rows: {existing:,}")

    if existing > 0 and not args.force:
        print(f"\n  ✅  aqi_data already has {existing:,} rows — nothing to do.")
        print("     Pass --force to clear and re-seed.")
        sys.exit(0)

    if existing > 0 and args.force:
        print("  🗑️   Clearing existing rows (--force)...")
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM aqi_data"))
            conn.commit()
        print("  Cleared.")

    # ── Station map ────────────────────────────────────────────────────────────
    station_map = get_station_map(engine)
    print(f"  Stations in DB: {len(station_map)} → {sorted(station_map.keys())}")

    # ── Load CSV ───────────────────────────────────────────────────────────────
    df = load_recent_csv(csv_path, args.days)

    # ── Insert ─────────────────────────────────────────────────────────────────
    t0 = time.time()
    print(f"\n  Inserting into aqi_data...")
    n = insert_rows(engine, df, station_map)
    elapsed = time.time() - t0

    # ── Verify ─────────────────────────────────────────────────────────────────
    final = existing_row_count(engine)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT MIN(datetime), MAX(datetime) FROM aqi_data")
        ).fetchone()

    print(f"\n{'='*60}")
    print(f"  ✅  Done in {elapsed:.1f}s")
    print(f"  Rows inserted:  {n:,}")
    print(f"  Total in table: {final:,}")
    if row[0]:
        print(f"  Date range:     {row[0]} → {row[1]}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
