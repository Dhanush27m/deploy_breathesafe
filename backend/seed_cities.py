"""
BreatheSafe — Cloud Seed Script (Cities + Stations only)
=========================================================
Used for cloud/production deployment where the full AQI CSV is not available.

Seeds:
  1. 29 cities into the `cities` table
  2. One virtual monitoring station per city into `monitoring_stations`

AQI data is NOT seeded here — the backend scheduler fetches it automatically
via the hourly pipeline (data_pipeline.py) once the service starts.

Safe to run multiple times — all inserts check for existing rows first.

Usage:
    python seed_cities.py
"""

import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable is not set.")
    print("Set it in your .env file or pass it as an environment variable.")
    sys.exit(1)

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
    ("kohima",             "nagaland",           25.6751,  94.1086),
    ("kolkata",            "west bengal",        22.5726,  88.3639),
    ("lucknow",            "uttar pradesh",      26.8467,  80.9462),
    ("mumbai",             "maharashtra",        19.0760,  72.8777),
    ("panaji",             "goa",                15.4909,  73.8278),
    ("patna",              "bihar",              25.5941,  85.1376),
    ("raipur",             "chhattisgarh",       21.2514,  81.6296),
    ("ranchi",             "jharkhand",          23.3441,  85.3096),
    ("shillong",           "meghalaya",          25.5788,  91.8933),
    ("shimla",             "himachal pradesh",   31.1048,  77.1734),
    ("thiruvananthapuram", "kerala",              8.5241,  76.9366),
    ("visakhapatnam",      "andhra pradesh",     17.6868,  83.2185),
]


def seed():
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # ── 1. Cities ─────────────────────────────────────────────────────────
        print("Seeding cities...")
        city_id_map = {}

        for name, state, lat, lon in CITIES:
            existing = session.execute(
                text("SELECT id FROM cities WHERE name = :name"),
                {"name": name}
            ).fetchone()

            if existing:
                city_id_map[name] = existing[0]
            else:
                result = session.execute(
                    text("""
                        INSERT INTO cities (name, state, latitude, longitude, country, is_active)
                        VALUES (:name, :state, :lat, :lon, 'India', true)
                        RETURNING id
                    """),
                    {"name": name, "state": state, "lat": lat, "lon": lon}
                )
                city_id_map[name] = result.fetchone()[0]
                print(f"  + {name}")

        session.commit()
        print(f"Cities done: {len(city_id_map)} total")

        # ── 2. Monitoring Stations ─────────────────────────────────────────────
        print("Seeding monitoring stations...")
        seeded = 0

        for name, _, lat, lon in CITIES:
            station_code = name.upper().replace(" ", "_") + "_CSV"
            existing = session.execute(
                text("SELECT id FROM monitoring_stations WHERE station_id = :sid"),
                {"sid": station_code}
            ).fetchone()

            if not existing:
                session.execute(
                    text("""
                        INSERT INTO monitoring_stations
                            (station_id, station_name, city_id, latitude, longitude,
                             data_source, is_active)
                        VALUES (:sid, :sname, :cid, :lat, :lon, 'csv', true)
                    """),
                    {
                        "sid":   station_code,
                        "sname": f"{name.title()} (CSV Aggregate)",
                        "cid":   city_id_map[name],
                        "lat":   lat,
                        "lon":   lon,
                    }
                )
                seeded += 1
                print(f"  + {station_code}")

        session.commit()
        print(f"Stations done: {seeded} new, {len(CITIES) - seeded} already existed")
        print("Seed complete. AQI data will be fetched automatically by the scheduler.")

    except Exception as e:
        session.rollback()
        print(f"Seed failed: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    seed()
