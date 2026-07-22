"""
BreatheSafe — Database Seed Script
====================================
Loads the enriched CSV (842,160 rows) into PostgreSQL in batches.

Steps performed:
  1. Insert 29 cities into `cities` table
  2. Create one virtual monitoring station per city  (e.g. "DELHI_CSV")
  3. Bulk-insert all AQI + weather rows into `aqi_data` table

Usage (run inside the backend Docker container):
    docker exec -it breathesafe_backend python seed_data.py

Or locally (with DATABASE_URL pointing to running PostgreSQL):
    python seed_data.py

Runtime: ~3–6 minutes for 842K rows (bulk insert, 5000 rows/batch)
"""

import math
import os
import sys
import time

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable is not set.")
    print("Set it in your .env file or pass it as an environment variable.")
    sys.exit(1)

CSV_PATH = os.getenv(
    "SEED_CSV_PATH",
    "/app/data/aqi_india_enriched.csv"
)

BATCH_SIZE = 5000   # rows per INSERT batch — tune up/down for your RAM


# ── City metadata (matches CSV exactly) ──────────────────────────────────────
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


def safe_val(v):
    """Convert numpy/pandas NaN/NA to Python None for PostgreSQL compatibility."""
    if v is None:
        return None
    try:
        if math.isnan(float(v)):
            return None
    except (TypeError, ValueError):
        pass
    return v


def safe_bool(v):
    """Convert various truthy values to Python bool or None."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes")
    return bool(v)


def run_seed():
    print("\n" + "=" * 60)
    print("  BreatheSafe — Database Seed")
    print("=" * 60)

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # ── 1. Cities ─────────────────────────────────────────────────────────
        print("\n📍 Seeding cities...")
        city_id_map = {}   # city_name → db id

        for name, state, lat, lon in CITIES:
            existing = session.execute(
                text("SELECT id FROM cities WHERE name = :name"),
                {"name": name}
            ).fetchone()

            if existing:
                city_id_map[name] = existing[0]
                print(f"   ⏭  {name:25s} already exists (id={existing[0]})")
            else:
                result = session.execute(
                    text("""
                        INSERT INTO cities (name, state, latitude, longitude, country, is_active)
                        VALUES (:name, :state, :lat, :lon, 'India', true)
                        RETURNING id
                    """),
                    {"name": name, "state": state, "lat": lat, "lon": lon}
                )
                city_id = result.fetchone()[0]
                city_id_map[name] = city_id
                print(f"   ✅ {name:25s} inserted  (id={city_id})")

        session.commit()
        print(f"\n   Total cities: {len(city_id_map)}")

        # ── 2. Monitoring Stations (one virtual station per CSV city) ──────────
        print("\n📡 Seeding monitoring stations...")
        station_id_map = {}   # city_name → monitoring_stations.id

        for name, _, lat, lon in CITIES:
            station_code = name.upper().replace(" ", "_") + "_CSV"
            existing = session.execute(
                text("SELECT id FROM monitoring_stations WHERE station_id = :sid"),
                {"sid": station_code}
            ).fetchone()

            if existing:
                station_id_map[name] = existing[0]
                print(f"   ⏭  {station_code:30s} already exists")
            else:
                result = session.execute(
                    text("""
                        INSERT INTO monitoring_stations
                            (station_id, station_name, city_id, latitude, longitude,
                             data_source, is_active)
                        VALUES (:sid, :sname, :cid, :lat, :lon, 'csv', true)
                        RETURNING id
                    """),
                    {
                        "sid":   station_code,
                        "sname": f"{name.title()} (CSV Aggregate)",
                        "cid":   city_id_map[name],
                        "lat":   lat,
                        "lon":   lon,
                    }
                )
                db_id = result.fetchone()[0]
                station_id_map[name] = db_id
                print(f"   ✅ {station_code:30s} inserted (id={db_id})")

        session.commit()

        # ── 3. AQI Data ────────────────────────────────────────────────────────
        print(f"\n📊 Loading CSV: {CSV_PATH}")
        t_start = time.time()

        df = pd.read_csv(CSV_PATH, parse_dates=["datetime"])
        total_rows = len(df)
        print(f"   Rows loaded : {total_rows:,}")
        print(f"   Columns     : {len(df.columns)}")

        # Check if aqi_data already has rows — skip if seeded
        existing_count = session.execute(
            text("SELECT COUNT(*) FROM aqi_data")
        ).scalar()
        if existing_count > 0:
            print(f"\n   ⏭  aqi_data already has {existing_count:,} rows. Skipping.")
            print("   To reseed, run: TRUNCATE aqi_data RESTART IDENTITY CASCADE;")
            session.close()
            return

        print(f"\n⏳ Inserting {total_rows:,} rows in batches of {BATCH_SIZE}...")

        inserted   = 0
        batch_num  = 0
        total_batches = math.ceil(total_rows / BATCH_SIZE)

        for start in range(0, total_rows, BATCH_SIZE):
            batch = df.iloc[start: start + BATCH_SIZE]
            batch_num += 1

            rows = []
            for _, row in batch.iterrows():
                city_name = str(row["city"]).lower().strip()
                station_db_id = station_id_map.get(city_name)
                if station_db_id is None:
                    continue   # skip unknown city

                rows.append({
                    "station_id":          station_db_id,
                    "datetime":            row["datetime"],
                    # Pollutants
                    "pm2_5_ugm3":          safe_val(row.get("pm2_5_ugm3")),
                    "pm10_ugm3":           safe_val(row.get("pm10_ugm3")),
                    "co_ugm3":             safe_val(row.get("co_ugm3")),
                    "no2_ugm3":            safe_val(row.get("no2_ugm3")),
                    "so2_ugm3":            safe_val(row.get("so2_ugm3")),
                    "o3_ugm3":             safe_val(row.get("o3_ugm3")),
                    "dust_ugm3":           safe_val(row.get("dust_ugm3")),
                    "aod":                 safe_val(row.get("aod")),
                    # AQI
                    "us_aqi":              safe_val(row.get("us_aqi")),
                    "india_aqi":           safe_val(row.get("india_aqi")),
                    "india_aqi_category":  safe_val(row.get("india_aqi_category")),
                    "pm25_category_india": safe_val(row.get("pm25_category_india")),
                    # Weather
                    "temperature_c":       safe_val(row.get("temperature_c")),
                    "wind_speed_kmh":      safe_val(row.get("wind_speed_kmh")),
                    "wind_gusts_kmh":      safe_val(row.get("wind_gusts_kmh")),
                    "humidity_percent":    safe_val(row.get("humidity_percent")),
                    "dew_point_c":         safe_val(row.get("dew_point_c")),
                    "pressure_msl_hpa":    safe_val(row.get("pressure_msl_hpa")),
                    "cloud_cover_percent": safe_val(row.get("cloud_cover_percent")),
                    "precipitation_mm":    safe_val(row.get("precipitation_mm")),
                    "is_raining":          safe_bool(row.get("is_raining")),
                    "heavy_rain":          safe_bool(row.get("heavy_rain")),
                    # Temporal
                    "month":               safe_val(row.get("month")),
                    "day_name":            safe_val(row.get("day_name")),
                    "is_weekend":          safe_bool(row.get("is_weekend")),
                    "season":              safe_val(row.get("season")),
                    "time_of_day":         safe_val(row.get("time_of_day")),
                    "festival_period":     safe_bool(row.get("festival_period")),
                    "crop_burning_season": safe_bool(row.get("crop_burning_season")),
                })

            if rows:
                session.execute(
                    text("""
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
                        )
                    """),
                    rows
                )
                session.commit()
                inserted += len(rows)

            elapsed = time.time() - t_start
            rate    = inserted / elapsed if elapsed > 0 else 0
            eta     = (total_rows - inserted) / rate if rate > 0 else 0
            pct     = 100 * inserted / total_rows
            print(f"   Batch {batch_num:4d}/{total_batches} | "
                  f"{inserted:>7,}/{total_rows:,} rows ({pct:5.1f}%) | "
                  f"{rate:,.0f} rows/s | ETA {eta:.0f}s",
                  end="\r", flush=True)

        print()   # newline after progress
        elapsed = time.time() - t_start
        print(f"\n{'='*60}")
        print("  ✅ Seed complete!")
        print(f"  Rows inserted : {inserted:,}")
        print(f"  Time taken    : {elapsed:.1f}s  ({elapsed/60:.1f} min)")
        print(f"  Avg speed     : {inserted/elapsed:,.0f} rows/sec")
        print(f"{'='*60}\n")

    except Exception as e:
        session.rollback()
        print(f"\n❌ Seed failed: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    run_seed()
