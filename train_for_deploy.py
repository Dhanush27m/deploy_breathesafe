"""
BreatheSafe — Local Training Script for Deployment
====================================================
Run this script ONCE from your local machine (where you have the full
944k-row CSV and xgboost/sklearn installed).

It trains one XGBoost model per city on the real data and saves the
.joblib files directly into backend/ml/models/ — ready to commit & push
to GitHub so Render can use them at startup without any retraining.

Usage (from the deploy_breathesafe root folder):
    python train_for_deploy.py

Or specify a custom CSV path:
    python train_for_deploy.py --csv "C:/path/to/aqi_india_enriched.csv"

After it finishes:
    git add backend/ml/models/
    git commit -m "add pre-trained XGBoost models (944k rows)"
    git push
    → Render redeploys and uses these models immediately.
"""

import argparse
import json
import os
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

# ── Where to save models (relative to this script's directory) ─────────────────
SCRIPT_DIR  = Path(__file__).parent
MODELS_DIR  = SCRIPT_DIR / "backend" / "ml" / "models"
MODEL_VER   = "v1.0"

# ── Default CSV search paths ───────────────────────────────────────────────────
# Try the sibling breathesafe project first, then common locations
CANDIDATE_CSV_PATHS = [
    # sibling folder (common layout: both projects side by side)
    SCRIPT_DIR.parent / "breathesafe" / "data" / "aqi_india_enriched.csv",
    SCRIPT_DIR.parent / "breathesafe" / "backend" / "data" / "aqi_india_enriched.csv",
    # inside this repo's data folder (if someone put it there)
    SCRIPT_DIR / "data" / "aqi_india_enriched.csv",
    SCRIPT_DIR / "backend" / "data" / "aqi_india_enriched.csv",
]

# ── Model hyper-parameters (same as local version) ─────────────────────────────
MAX_DEPTH      = 6
N_ESTIMATORS   = 400
LEARNING_RATE  = 0.05
TEST_DAYS      = 30

FEATURE_COLS = [
    "hour", "day_of_week", "month", "is_weekend",
    "lag_24h", "lag_48h", "lag_168h",
    "rolling_24h_mean", "rolling_7d_mean", "rolling_7d_std",
    "temperature_c", "wind_speed_kmh",
]
TARGET_COL = "india_aqi"


# ── Feature engineering (identical to local train_models.py) ──────────────────
def make_features(df):
    import numpy as np
    df = df.sort_values("datetime").copy()
    df["hour"]        = df["datetime"].dt.hour
    df["day_of_week"] = df["datetime"].dt.dayofweek
    df["month"]       = df["datetime"].dt.month
    df["is_weekend"]  = df["day_of_week"].isin([5, 6]).astype(int)

    aqi = df[TARGET_COL]
    df["lag_24h"]          = aqi.shift(24)
    df["lag_48h"]          = aqi.shift(48)
    df["lag_168h"]         = aqi.shift(168)
    df["rolling_24h_mean"] = aqi.shift(1).rolling(24,  min_periods=12).mean()
    df["rolling_7d_mean"]  = aqi.shift(1).rolling(168, min_periods=72).mean()
    df["rolling_7d_std"]   = aqi.shift(1).rolling(168, min_periods=72).std()

    for col in ["temperature_c", "wind_speed_kmh"]:
        if col in df.columns:
            df[col] = df[col].ffill().bfill().fillna(0.0)
        else:
            df[col] = 0.0

    return df.dropna(subset=FEATURE_COLS + [TARGET_COL])


def train_xgb(city_df, city):
    import joblib
    import numpy as np
    from sklearn.metrics import mean_absolute_error, mean_squared_error
    from xgboost import XGBRegressor

    df = make_features(city_df)
    if len(df) < 500:
        print(f"  ⚠️  {city}: not enough rows ({len(df)}) — skipping")
        return {}

    split_ts = df["datetime"].max() - __import__("pandas").Timedelta(days=TEST_DAYS)
    train    = df[df["datetime"] <= split_ts]
    test     = df[df["datetime"] >  split_ts]

    X_train, y_train = train[FEATURE_COLS], train[TARGET_COL]
    X_test,  y_test  = test[FEATURE_COLS],  test[TARGET_COL]

    model = XGBRegressor(
        n_estimators=N_ESTIMATORS,
        max_depth=MAX_DEPTH,
        learning_rate=LEARNING_RATE,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=-1,
        verbosity=0,
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    preds = model.predict(X_test).clip(0, 500)
    mae   = mean_absolute_error(y_test, preds)
    rmse  = float(mean_squared_error(y_test, preds) ** 0.5)

    path = MODELS_DIR / f"{city}_xgb.joblib"
    joblib.dump({"model": model, "feature_cols": FEATURE_COLS, "version": MODEL_VER}, path)

    return {
        "mae":        round(mae,  2),
        "rmse":       round(rmse, 2),
        "train_rows": len(train),
        "test_rows":  len(test),
    }


def main():
    parser = argparse.ArgumentParser(description="Train BreatheSafe models locally for deployment")
    parser.add_argument("--csv",  type=str, default=None,
                        help="Path to aqi_india_enriched.csv")
    parser.add_argument("--city", type=str, default=None,
                        help="Train only one city (e.g. delhi)")
    args = parser.parse_args()

    # ── Check imports ──────────────────────────────────────────────────────────
    try:
        import joblib
        import pandas as pd
        import numpy as np
        from xgboost import XGBRegressor
        from sklearn.metrics import mean_absolute_error
    except ImportError as e:
        print(f"\n❌  Missing package: {e}")
        print("   Install with:  pip install xgboost scikit-learn joblib pandas")
        sys.exit(1)

    # ── Find CSV ───────────────────────────────────────────────────────────────
    csv_path = None
    if args.csv:
        csv_path = Path(args.csv)
        if not csv_path.exists():
            print(f"❌  CSV not found at: {csv_path}")
            sys.exit(1)
    else:
        for candidate in CANDIDATE_CSV_PATHS:
            if candidate.exists():
                csv_path = candidate
                break
        if csv_path is None:
            print("\n❌  Could not auto-locate aqi_india_enriched.csv")
            print("   Searched:")
            for p in CANDIDATE_CSV_PATHS:
                print(f"     {p}")
            print("\n   Run with: python train_for_deploy.py --csv <path/to/csv>")
            sys.exit(1)

    # ── Setup ──────────────────────────────────────────────────────────────────
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*65}")
    print(f"  BreatheSafe — Local Training for Deployment")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*65}")
    print(f"  CSV:    {csv_path}")
    print(f"  Output: {MODELS_DIR}")
    print(f"{'='*65}\n")

    # ── Load CSV ───────────────────────────────────────────────────────────────
    print("📂 Loading CSV...")
    df = pd.read_csv(csv_path)
    # Handle both "8/5/2022 0:00" (legacy) and ISO "2026-04-15 00:00:00" formats
    df["datetime"] = pd.to_datetime(df["datetime"], format="mixed", dayfirst=False, errors="coerce")
    df = df.dropna(subset=["datetime", TARGET_COL])
    df["city"] = df["city"].str.lower().str.strip()

    print(f"   ✅ Loaded {len(df):,} rows | {df['city'].nunique()} cities")
    print(f"   Date range: {df['datetime'].min().date()} → {df['datetime'].max().date()}\n")

    cities = sorted(df["city"].unique().tolist())
    if args.city:
        args.city = args.city.lower().strip()
        if args.city not in cities:
            print(f"❌  City '{args.city}' not found. Available: {cities}")
            sys.exit(1)
        cities = [args.city]

    # ── Train ──────────────────────────────────────────────────────────────────
    metadata = {
        "trained_at": datetime.now().isoformat(),
        "model_version": MODEL_VER,
        "trained_on_rows": len(df),
        "cities": {}
    }
    t0 = time.time()
    good = 0

    for i, city in enumerate(cities, 1):
        city_df = df[df["city"] == city].copy()
        print(f"[{i:02d}/{len(cities)}] {city.upper()} — {len(city_df):,} rows")

        print(f"          🌲 Training XGBoost...", end=" ", flush=True)
        t1 = time.time()
        metrics = train_xgb(city_df, city)
        elapsed = time.time() - t1

        if metrics:
            print(f"MAE={metrics['mae']:.1f}  RMSE={metrics['rmse']:.1f}  ({elapsed:.0f}s)")
            good += 1
        else:
            print("skipped")

        metadata["cities"][city] = {"xgb": metrics, "prophet": {}}

    # ── Save metadata ──────────────────────────────────────────────────────────
    meta_path = MODELS_DIR / "metadata.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    total = time.time() - t0
    print(f"\n{'='*65}")
    print(f"  ✅ Done! {good}/{len(cities)} cities trained in {total:.0f}s")
    print(f"  Models saved to: {MODELS_DIR}")
    print(f"{'='*65}")
    print(f"\n📋 Next steps:")
    print(f"   1. git add backend/ml/models/")
    print(f"   2. git commit -m \"feat: add pre-trained XGBoost models (944k rows)\"")
    print(f"   3. git push  →  Render auto-deploys with real-data models\n")


if __name__ == "__main__":
    main()
