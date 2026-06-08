"""
BreatheSafe — Standalone Pipeline Runner
=========================================
Run the data pipeline manually from inside the Docker container.

Usage:
    # Standard hourly update (DB only):
    docker exec breathesafe_backend python /app/pipeline_runner.py

    # Daily update (DB + CSV):
    docker exec breathesafe_backend python /app/pipeline_runner.py --mode daily

    # Force refresh from a specific date (DB only):
    docker exec breathesafe_backend python /app/pipeline_runner.py --from 2026-04-20

    # Force refresh from a specific date AND update CSV:
    docker exec breathesafe_backend python /app/pipeline_runner.py --from 2026-04-20 --csv

    # Just refresh the OpenAQ station cache:
    docker exec breathesafe_backend python /app/pipeline_runner.py --refresh-cache

    # Show pipeline status (last row in DB, CSV row count):
    docker exec breathesafe_backend python /app/pipeline_runner.py --status
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta

# ── Setup path so we can import app modules ───────────────────────────────────
sys.path.insert(0, "/app")
os.environ.setdefault("SEED_CSV_PATH", "/app/data/aqi_india_enriched.csv")
if not os.environ.get("DATABASE_URL"):
    print("ERROR: DATABASE_URL environment variable is not set.")
    print("Set it in your .env file or Render/Docker environment.")
    sys.exit(1)

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def show_status():
    """Print current DB and CSV status."""
    from sqlalchemy import create_engine, text
    from pathlib import Path

    db_url  = os.environ["DATABASE_URL"]
    csv_path = Path(os.environ["SEED_CSV_PATH"])
    engine  = create_engine(db_url, pool_pre_ping=True)

    print("\n" + "=" * 60)
    print("  BreatheSafe — Pipeline Status")
    print("=" * 60)

    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT MAX(datetime), COUNT(*) FROM aqi_data")).fetchone()
            last_dt, total_rows = row
        print(f"  DB last datetime : {last_dt}")
        print(f"  DB total rows    : {total_rows:,}")
        now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
        if last_dt:
            gap_h = int((now_ist - last_dt).total_seconds() / 3600)
            print(f"  DB gap (approx)  : {gap_h} hours behind current IST time")
    except Exception as e:
        print(f"  DB error: {e}")

    if csv_path.exists():
        import pandas as pd
        try:
            df = pd.read_csv(csv_path, usecols=["datetime"], parse_dates=["datetime"])
            print(f"\n  CSV path         : {csv_path}")
            print(f"  CSV row count    : {len(df):,}")
            print(f"  CSV last datetime: {df['datetime'].max()}")
        except Exception as e:
            print(f"  CSV error: {e}")
    else:
        print(f"\n  CSV not found at {csv_path}")

    # Check pipeline cache
    cache_path = csv_path.parent / "openaq_stations_cache.json"
    if cache_path.exists():
        import json
        try:
            with open(cache_path) as f:
                cached = json.load(f)
            ts = cached.get("_ts", 0)
            age_h = (time.time() - ts) / 3600
            city_count = len([k for k in cached if not k.startswith("_")])
            print(f"\n  OpenAQ cache     : {city_count} cities cached ({age_h:.1f}h old)")
        except Exception as e:
            print(f"  Cache error: {e}")
    else:
        print("\n  OpenAQ cache     : not found (will discover on next run)")

    print("=" * 60 + "\n")


def refresh_cache():
    """Delete the OpenAQ station cache to force re-discovery."""
    from pathlib import Path
    cache_path = Path(os.environ["SEED_CSV_PATH"]).parent / "openaq_stations_cache.json"
    if cache_path.exists():
        cache_path.unlink()
        print(f"Deleted cache: {cache_path}")
        print("Next pipeline run will re-discover OpenAQ stations.")
    else:
        print("No cache file found.")

    # Re-discover now
    print("Discovering OpenAQ stations now (this may take a minute)...")
    from app.services.data_pipeline import discover_stations
    city_sensors = discover_stations()
    print(f"Done. Discovered {len(city_sensors)} cities with OpenAQ stations.")


def run_with_override(from_date: str, update_csv: bool):
    """
    Override the pipeline start date (bypasses MAX(datetime) check).
    Temporarily monkeypatches _get_last_datetime to return a fixed date.
    """
    import app.services.data_pipeline as pipeline

    try:
        override_dt = datetime.strptime(from_date, "%Y-%m-%d") - timedelta(hours=1)
    except ValueError:
        print(f"Invalid date format: {from_date}. Use YYYY-MM-DD.")
        sys.exit(1)

    original_fn = pipeline._get_last_datetime

    def patched_fn(engine):
        log.info("Date override: starting from %s", from_date)
        return override_dt

    pipeline._get_last_datetime = patched_fn
    try:
        result = pipeline.run_pipeline(update_csv=update_csv, verbose=True)
    finally:
        pipeline._get_last_datetime = original_fn

    return result


def main():
    parser = argparse.ArgumentParser(
        description="BreatheSafe data pipeline manual runner"
    )
    parser.add_argument(
        "--mode", choices=["hourly", "daily"], default="hourly",
        help="hourly = DB only | daily = DB + CSV (default: hourly)",
    )
    parser.add_argument(
        "--from", dest="from_date", default=None, metavar="YYYY-MM-DD",
        help="Override start date (skip MAX(datetime) detection)",
    )
    parser.add_argument(
        "--csv", action="store_true",
        help="Force CSV update (even in hourly mode)",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show pipeline status (DB rows, CSV rows, cache) and exit",
    )
    parser.add_argument(
        "--refresh-cache", action="store_true",
        help="Delete OpenAQ station cache and re-discover, then exit",
    )
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.refresh_cache:
        refresh_cache()
        return

    update_csv = (args.mode == "daily") or args.csv

    print("\n" + "=" * 60)
    print("  BreatheSafe — Data Pipeline Runner")
    print(f"  Mode      : {args.mode}")
    print(f"  Update CSV: {update_csv}")
    if args.from_date:
        print(f"  Start from: {args.from_date} (override)")
    print("=" * 60 + "\n")

    t0 = time.time()

    if args.from_date:
        result = run_with_override(args.from_date, update_csv)
    else:
        from app.services.data_pipeline import run_pipeline
        result = run_pipeline(update_csv=update_csv, verbose=True)

    elapsed = time.time() - t0

    print("\n" + "=" * 60)
    print("  Pipeline Complete")
    print(f"  From         : {result['start_dt']}")
    print(f"  To           : {result['end_dt']}")
    print(f"  Rows fetched : {result['rows_fetched']:,}")
    print(f"  Rows inserted: {result['rows_inserted']:,}")
    if update_csv:
        print(f"  CSV rows add : {result['csv_rows_added']:,}")
    print(f"  Time taken   : {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
