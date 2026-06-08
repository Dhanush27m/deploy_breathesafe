"""
BreatheSafe — ML Training Pipeline  (v2 — expanded features)
Trains XGBoost (per-city hourly) + Prophet (per-city daily) models.

Usage (inside backend container):
    python train_models.py [--city delhi] [--skip-prophet]
    python train_models.py --from-db [--city delhi] [--skip-prophet]

Output:
    /app/ml/models/{city}_xgb.joblib
    /app/ml/models/{city}_prophet.joblib
    /app/ml/models/metadata.json
"""

import argparse
import json
import os
import sys
import time
import warnings
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from xgboost import XGBRegressor

warnings.filterwarnings("ignore")

# ── Config ─────────────────────────────────────────────────────────────────────
CSV_PATH    = "/app/data/aqi_india_enriched.csv"
MODELS_DIR  = "/app/ml/models"
MODEL_VER   = "v2.0"
TEST_DAYS   = 30      # Last N days held out for evaluation

# XGBoost hyperparameters — tuned for AQI time-series
MAX_DEPTH        = 7
N_ESTIMATORS     = 1000   # will be cut short by early stopping
LEARNING_RATE    = 0.03
EARLY_STOP_ROUNDS = 50

# ── Expanded feature set ───────────────────────────────────────────────────────
FEATURE_COLS = [
    # Time
    "hour", "day_of_week", "month", "day_of_year", "week_of_year",
    "is_weekend", "season_enc",
    # Lag features
    "lag_24h", "lag_48h", "lag_72h", "lag_168h", "lag_336h",
    # Rolling mean / std
    "rolling_24h_mean", "rolling_3d_mean", "rolling_7d_mean", "rolling_14d_mean",
    "rolling_7d_std",   "rolling_3d_std",
    # Weather
    "temperature_c", "wind_speed_kmh", "humidity_percent",
    "pressure_msl_hpa", "wind_gusts_kmh", "precipitation_mm", "is_raining",
    # Domain context
    "festival_period", "crop_burning_season",
]

TARGET_COL = "india_aqi"

# CPCB AQI category thresholds
AQI_CATEGORIES = [
    (50,  "Good"),
    (100, "Satisfactory"),
    (200, "Moderately Polluted"),
    (300, "Poor"),
    (400, "Very Poor"),
    (500, "Severe"),
]


def aqi_category(val: float) -> str:
    if val is None or np.isnan(val):
        return "Unknown"
    for threshold, cat in AQI_CATEGORIES:
        if val <= threshold:
            return cat
    return "Severe"


def month_to_season(month: int) -> int:
    """Encode Indian meteorological seasons as integers."""
    if month in [12, 1, 2]:  return 0  # winter
    if month in [3, 4, 5]:   return 1  # summer / pre-monsoon
    if month in [6, 7, 8, 9]: return 2  # monsoon
    return 3                             # post-monsoon (Oct, Nov)


# ── Feature Engineering ────────────────────────────────────────────────────────
def make_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add lag, rolling, and contextual features to a city's hourly dataframe."""
    df = df.sort_values("datetime").copy()

    # ── Time features ──────────────────────────────────────────────────────────
    df["hour"]        = df["datetime"].dt.hour
    df["day_of_week"] = df["datetime"].dt.dayofweek
    df["month"]       = df["datetime"].dt.month
    df["day_of_year"] = df["datetime"].dt.dayofyear
    df["week_of_year"]= df["datetime"].dt.isocalendar().week.astype(int)
    df["is_weekend"]  = df["day_of_week"].isin([5, 6]).astype(int)
    df["season_enc"]  = df["month"].apply(month_to_season)

    # ── AQI lag features ───────────────────────────────────────────────────────
    aqi = df[TARGET_COL]
    df["lag_24h"]  = aqi.shift(24)
    df["lag_48h"]  = aqi.shift(48)
    df["lag_72h"]  = aqi.shift(72)
    df["lag_168h"] = aqi.shift(168)
    df["lag_336h"] = aqi.shift(336)

    # ── Rolling features ───────────────────────────────────────────────────────
    df["rolling_24h_mean"]  = aqi.shift(1).rolling(24,  min_periods=12).mean()
    df["rolling_3d_mean"]   = aqi.shift(1).rolling(72,  min_periods=36).mean()
    df["rolling_7d_mean"]   = aqi.shift(1).rolling(168, min_periods=72).mean()
    df["rolling_14d_mean"]  = aqi.shift(1).rolling(336, min_periods=168).mean()
    df["rolling_7d_std"]    = aqi.shift(1).rolling(168, min_periods=72).std()
    df["rolling_3d_std"]    = aqi.shift(1).rolling(72,  min_periods=36).std()

    # ── Weather features ────────────────────────────────────────────────────────
    weather_cols = {
        "temperature_c":    20.0,
        "wind_speed_kmh":    5.0,
        "humidity_percent":  60.0,
        "pressure_msl_hpa": 1013.0,
        "wind_gusts_kmh":    8.0,
        "precipitation_mm":  0.0,
    }
    for col, default in weather_cols.items():
        if col in df.columns:
            df[col] = df[col].ffill().bfill().fillna(default)
        else:
            df[col] = default

    # Boolean weather
    if "is_raining" in df.columns:
        df["is_raining"] = df["is_raining"].fillna(False).astype(int)
    else:
        df["is_raining"] = 0

    # ── Domain context features ────────────────────────────────────────────────
    for col in ["festival_period", "crop_burning_season"]:
        if col in df.columns:
            df[col] = df[col].fillna(False).astype(int)
        else:
            # Approximate from month if column absent
            df[col] = df["month"].isin([10, 11]).astype(int)

    return df.dropna(subset=FEATURE_COLS + [TARGET_COL])


# ── Train XGBoost ──────────────────────────────────────────────────────────────
def train_xgb(df: pd.DataFrame, city: str, models_dir: str = MODELS_DIR) -> dict:
    df = make_features(df)
    if len(df) < 500:
        print(f"  ⚠️  {city}: not enough rows ({len(df)}) — skipping XGB")
        return {}

    split_ts = df["datetime"].max() - pd.Timedelta(days=TEST_DAYS)
    train    = df[df["datetime"] <= split_ts]
    test     = df[df["datetime"] >  split_ts]

    X_train, y_train = train[FEATURE_COLS], train[TARGET_COL]
    X_test,  y_test  = test[FEATURE_COLS],  test[TARGET_COL]

    model = XGBRegressor(
        n_estimators      = N_ESTIMATORS,
        max_depth         = MAX_DEPTH,
        learning_rate     = LEARNING_RATE,
        subsample         = 0.8,
        colsample_bytree  = 0.75,
        min_child_weight  = 3,
        gamma             = 0.1,
        reg_alpha         = 0.1,
        reg_lambda        = 1.0,
        random_state      = 42,
        n_jobs            = -1,
        verbosity         = 0,
        early_stopping_rounds = EARLY_STOP_ROUNDS,
    )
    model.fit(
        X_train, y_train,
        eval_set  = [(X_test, y_test)],
        verbose   = False,
    )

    best_n = model.best_iteration + 1
    preds  = model.predict(X_test).clip(0, 500)
    mae    = mean_absolute_error(y_test, preds)
    rmse   = np.sqrt(mean_squared_error(y_test, preds))

    path = os.path.join(models_dir, f"{city}_xgb.joblib")
    joblib.dump({
        "model":        model,
        "feature_cols": FEATURE_COLS,
        "version":      MODEL_VER,
    }, path)

    return {
        "mae":        round(mae,   2),
        "rmse":       round(rmse,  2),
        "best_n_estimators": best_n,
        "train_rows": len(train),
        "test_rows":  len(test),
    }


# ── Train Prophet ──────────────────────────────────────────────────────────────
def train_prophet(df: pd.DataFrame, city: str, models_dir: str = MODELS_DIR) -> dict:
    try:
        from prophet import Prophet
    except ImportError:
        print("not installed")
        return {}

    daily = (
        df.groupby(df["datetime"].dt.date)[TARGET_COL]
        .mean()
        .reset_index()
        .rename(columns={"datetime": "ds", TARGET_COL: "y"})
    )
    daily["ds"] = pd.to_datetime(daily["ds"])
    daily       = daily.dropna(subset=["y"])

    if len(daily) < 60:
        print(f"not enough rows ({len(daily)})")
        return {}

    split_ts = daily["ds"].max() - pd.Timedelta(days=TEST_DAYS)
    train_d  = daily[daily["ds"] <= split_ts]
    test_d   = daily[daily["ds"] >  split_ts]

    try:
        m = Prophet(
            yearly_seasonality   = True,
            weekly_seasonality   = True,
            daily_seasonality    = False,
            interval_width       = 0.80,
            changepoint_prior_scale = 0.05,
        )
        m.fit(train_d)
    except Exception as e:
        print(f"Prophet init/fit failed: {e}")
        return {}

    try:
        future      = m.make_future_dataframe(periods=TEST_DAYS)
        forecast_df = m.predict(future)
        merged = forecast_df[forecast_df["ds"].isin(test_d["ds"])].merge(test_d, on="ds")
        if len(merged):
            mae  = mean_absolute_error(merged["y"], merged["yhat"].clip(0, 500))
            rmse = np.sqrt(mean_squared_error(merged["y"], merged["yhat"].clip(0, 500)))
        else:
            mae, rmse = None, None

        path = os.path.join(models_dir, f"{city}_prophet.joblib")
        joblib.dump({"model": m, "version": MODEL_VER}, path)

        return {
            "mae":        round(mae,  2) if mae  else None,
            "rmse":       round(rmse, 2) if rmse else None,
            "daily_rows": len(daily),
        }
    except Exception as e:
        print(f"Prophet predict/save failed: {e}")
        return {}


# ── Load from DB ───────────────────────────────────────────────────────────────
def load_from_db(db_url: str) -> pd.DataFrame:
    from sqlalchemy import create_engine, text as sa_text

    print("  Connecting to database...")
    engine = create_engine(db_url, pool_pre_ping=True)

    query = sa_text("""
        SELECT
            LOWER(c.name)           AS city,
            ad.datetime,
            ad.india_aqi,
            ad.temperature_c,
            ad.wind_speed_kmh,
            ad.humidity_percent,
            ad.pressure_msl_hpa,
            ad.wind_gusts_kmh,
            ad.precipitation_mm,
            ad.is_raining,
            ad.festival_period,
            ad.crop_burning_season
        FROM aqi_data ad
        JOIN monitoring_stations ms ON ms.id = ad.station_id
        JOIN cities c               ON c.id  = ms.city_id
        WHERE ad.india_aqi IS NOT NULL
        ORDER BY c.name, ad.datetime
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    df["datetime"] = pd.to_datetime(df["datetime"])
    print(f"  Loaded {len(df):,} rows from DB | Cities: {df['city'].nunique()}")
    return df


# ── Skip if models already exist ───────────────────────────────────────────────
def models_already_trained(cities: list) -> bool:
    """Return True if v2 .joblib files already exist for every city."""
    for c in cities:
        path = os.path.join(MODELS_DIR, f"{c}_xgb.joblib")
        if not os.path.exists(path):
            return False
        try:
            bundle = joblib.load(path)
            if bundle.get("version") != MODEL_VER:
                return False  # old version — retrain
        except Exception:
            return False
    return True


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="BreatheSafe ML Training v2")
    parser.add_argument("--city",         type=str, default=None)
    parser.add_argument("--skip-prophet", action="store_true")
    parser.add_argument("--from-db",      action="store_true")
    parser.add_argument("--db-url",       type=str, default=None)
    parser.add_argument("--csv",          type=str, default=CSV_PATH,
                        help="Override CSV path")
    parser.add_argument("--models-dir",   type=str, default=MODELS_DIR,
                        help="Override output directory for .joblib files")
    args = parser.parse_args()

    models_out = args.models_dir
    os.makedirs(models_out, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  BreatheSafe ML Training v2 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Features: {len(FEATURE_COLS)}")
    print(f"{'='*60}")

    # ── Load data ──────────────────────────────────────────────────────────────
    if args.from_db:
        db_url = args.db_url or os.getenv("DATABASE_URL")
        if not db_url:
            print("❌  --from-db requires DATABASE_URL env var or --db-url flag")
            sys.exit(1)
        print(f"  Source: DATABASE")
        df = load_from_db(db_url)
        print(f"  📊 {len(df):,} rows | {df['city'].nunique()} cities | "
              f"{df['datetime'].min().date()} → {df['datetime'].max().date()}")
    else:
        csv_path = args.csv
        print(f"  Source: CSV ({csv_path})")
        if not os.path.exists(csv_path):
            print(f"❌  CSV not found: {csv_path}")
            sys.exit(1)
        print("📂 Loading CSV...")
        df = pd.read_csv(csv_path)
        df["datetime"] = pd.to_datetime(df["datetime"], format="mixed",
                                        dayfirst=False, errors="coerce")
        df = df.dropna(subset=["datetime"])
        print(f"   Loaded {len(df):,} rows | Cities: {df['city'].nunique()}")

    df["city"] = df["city"].str.lower().str.strip()
    df = df.dropna(subset=[TARGET_COL])
    total_rows = len(df)

    cities = sorted(df["city"].unique().tolist())
    if args.city:
        args.city = args.city.lower().strip()
        if args.city not in cities:
            print(f"❌ City '{args.city}' not in data. Available: {cities}")
            sys.exit(1)
        cities = [args.city]

    # ── Skip if already trained (idempotent for Docker restarts) ──────────────
    if args.from_db and models_already_trained(cities):
        print(f"\n  ✅  v2 models exist for all {len(cities)} cities — skipping.")
        print(f"     Delete ml/models/*.joblib to force retraining.")
        sys.exit(0)

    metadata = {
        "trained_at":      datetime.now().isoformat(),
        "model_version":   MODEL_VER,
        "trained_on_rows": total_rows,
        "n_features":      len(FEATURE_COLS),
        "feature_cols":    FEATURE_COLS,
        "cities":          {},
    }
    t0 = time.time()

    for i, city in enumerate(cities, 1):
        city_df = df[df["city"] == city].copy()
        print(f"\n[{i:02d}/{len(cities)}] {city.upper()} — {len(city_df):,} rows")

        # XGBoost
        print("   🌲 XGBoost...", end=" ", flush=True)
        t1 = time.time()
        xgb_metrics = train_xgb(city_df, city, models_out)
        elapsed = time.time() - t1
        if xgb_metrics:
            best_n = xgb_metrics.get("best_n_estimators", "?")
            print(f"MAE={xgb_metrics['mae']:.1f}  RMSE={xgb_metrics['rmse']:.1f}"
                  f"  trees={best_n}  ({elapsed:.0f}s)")
        else:
            print("skipped")

        # Prophet
        prophet_metrics = {}
        if not args.skip_prophet:
            print("   🔮 Prophet...", end=" ", flush=True)
            t1 = time.time()
            prophet_metrics = train_prophet(city_df, city, models_out)
            elapsed = time.time() - t1
            if prophet_metrics:
                print(f"MAE={prophet_metrics.get('mae','?')}  ({elapsed:.0f}s)")
            else:
                print("skipped")

        metadata["cities"][city] = {
            "xgb":     xgb_metrics,
            "prophet": prophet_metrics,
        }

    # Save metadata
    meta_path = os.path.join(models_out, "metadata.json")
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    total = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  ✅ Training complete — {len(cities)} cities in {total:.0f}s")
    print(f"  Trained on {total_rows:,} rows with {len(FEATURE_COLS)} features")
    print(f"  Models saved to: {models_out}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
