"""
BreatheSafe — ML Inference Service  (v2 — expanded features)
Loads trained XGBoost + Prophet models and generates 1/3/7-day forecasts.
Models are lazy-loaded on first use and cached in memory.
"""

import json
import os
from datetime import datetime, timedelta
from typing import List, Optional

import numpy as np
import pandas as pd

# ── Config ─────────────────────────────────────────────────────────────────────
MODELS_DIR = "/app/ml/models"

# Must match train_models.py FEATURE_COLS exactly
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

AQI_CATEGORIES = [
    (50,  "Good"),
    (100, "Satisfactory"),
    (200, "Moderately Polluted"),
    (300, "Poor"),
    (400, "Very Poor"),
    (500, "Severe"),
]

# Model cache: {city: {"xgb": ..., "prophet": ...}}
_MODEL_CACHE: dict = {}
_METADATA: Optional[dict] = None


def aqi_category(val: float) -> str:
    if val is None or np.isnan(val):
        return "Unknown"
    for threshold, cat in AQI_CATEGORIES:
        if val <= threshold:
            return cat
    return "Severe"


def _month_to_season(month: int) -> int:
    if month in [12, 1, 2]:   return 0  # winter
    if month in [3, 4, 5]:    return 1  # summer / pre-monsoon
    if month in [6, 7, 8, 9]: return 2  # monsoon
    return 3                             # post-monsoon (Oct, Nov)


def _is_festival_period(dt: datetime) -> int:
    """Approximate Indian festival period (Diwali/Dussehra window)."""
    return int(dt.month in [10, 11])


def _is_crop_burning(dt: datetime) -> int:
    """Approximate Punjab crop stubble burning season."""
    return int(dt.month in [10, 11])


# ── Model loading ──────────────────────────────────────────────────────────────
def _load_metadata() -> dict:
    global _METADATA
    if _METADATA is None:
        path = os.path.join(MODELS_DIR, "metadata.json")
        if os.path.exists(path):
            with open(path) as f:
                _METADATA = json.load(f)
        else:
            _METADATA = {}
    return _METADATA


def _load_models(city: str) -> dict:
    if city not in _MODEL_CACHE:
        import joblib
        cache = {}
        xgb_path     = os.path.join(MODELS_DIR, f"{city}_xgb.joblib")
        prophet_path = os.path.join(MODELS_DIR, f"{city}_prophet.joblib")
        if os.path.exists(xgb_path):
            cache["xgb"] = joblib.load(xgb_path)
        if os.path.exists(prophet_path):
            cache["prophet"] = joblib.load(prophet_path)
        _MODEL_CACHE[city] = cache
    return _MODEL_CACHE[city]


def models_available(city: str) -> bool:
    path = os.path.join(MODELS_DIR, f"{city}_xgb.joblib")
    return os.path.exists(path)


def trained_cities() -> List[str]:
    if not os.path.exists(MODELS_DIR):
        return []
    return [
        f.replace("_xgb.joblib", "")
        for f in os.listdir(MODELS_DIR)
        if f.endswith("_xgb.joblib")
    ]


# ── Inference ──────────────────────────────────────────────────────────────────
def _build_feature_row(
    target_dt:    datetime,
    history:      pd.Series,   # historical india_aqi indexed by datetime
    weather_ctx:  dict,        # last-known weather readings
) -> dict:
    """Build one feature dict for a single future timestamp."""
    def _get(dt):
        if dt in history.index:
            return history[dt]
        for h in range(1, 3):
            for d in [dt - timedelta(hours=h), dt + timedelta(hours=h)]:
                if d in history.index:
                    return history[d]
        return history.mean()

    # Lag features
    lag_24h  = _get(target_dt - timedelta(hours=24))
    lag_48h  = _get(target_dt - timedelta(hours=48))
    lag_72h  = _get(target_dt - timedelta(hours=72))
    lag_168h = _get(target_dt - timedelta(hours=168))
    lag_336h = _get(target_dt - timedelta(hours=336))

    # Rolling windows
    past = history[history.index < target_dt]
    w24  = past.tail(24)
    w72  = past.tail(72)
    w168 = past.tail(168)
    w336 = past.tail(336)

    return {
        # Time
        "hour":             target_dt.hour,
        "day_of_week":      target_dt.weekday(),
        "month":            target_dt.month,
        "day_of_year":      target_dt.timetuple().tm_yday,
        "week_of_year":     int(target_dt.isocalendar()[1]),
        "is_weekend":       int(target_dt.weekday() >= 5),
        "season_enc":       _month_to_season(target_dt.month),
        # Lags
        "lag_24h":          float(lag_24h),
        "lag_48h":          float(lag_48h),
        "lag_72h":          float(lag_72h),
        "lag_168h":         float(lag_168h),
        "lag_336h":         float(lag_336h),
        # Rolling
        "rolling_24h_mean": float(w24.mean())  if len(w24)  else float(lag_24h),
        "rolling_3d_mean":  float(w72.mean())  if len(w72)  else float(lag_24h),
        "rolling_7d_mean":  float(w168.mean()) if len(w168) else float(lag_24h),
        "rolling_14d_mean": float(w336.mean()) if len(w336) else float(lag_24h),
        "rolling_7d_std":   float(w168.std())  if len(w168) > 1 else 10.0,
        "rolling_3d_std":   float(w72.std())   if len(w72)  > 1 else 10.0,
        # Weather — carry forward last known values
        "temperature_c":    weather_ctx.get("temperature_c",    20.0),
        "wind_speed_kmh":   weather_ctx.get("wind_speed_kmh",    5.0),
        "humidity_percent": weather_ctx.get("humidity_percent",  60.0),
        "pressure_msl_hpa": weather_ctx.get("pressure_msl_hpa", 1013.0),
        "wind_gusts_kmh":   weather_ctx.get("wind_gusts_kmh",    8.0),
        "precipitation_mm": weather_ctx.get("precipitation_mm",  0.0),
        "is_raining":       weather_ctx.get("is_raining",        0),
        # Domain
        "festival_period":      _is_festival_period(target_dt),
        "crop_burning_season":  _is_crop_burning(target_dt),
    }


def _xgb_predict_horizon(
    city:          str,
    models:        dict,
    recent_df:     pd.DataFrame,
    horizon_hours: int,
) -> List[dict]:
    xgb_bundle = models.get("xgb")
    if not xgb_bundle:
        return []

    model        = xgb_bundle["model"]
    feature_cols = xgb_bundle.get("feature_cols", FEATURE_COLS)

    history = recent_df.set_index("datetime")["india_aqi"].copy()
    history = history[~history.index.duplicated(keep="last")]

    # Collect last-known weather context from recent_df
    last = recent_df.ffill().iloc[-1]
    weather_ctx = {
        "temperature_c":    float(last.get("temperature_c",    20.0) or 20.0),
        "wind_speed_kmh":   float(last.get("wind_speed_kmh",    5.0) or  5.0),
        "humidity_percent": float(last.get("humidity_percent",  60.0) or 60.0),
        "pressure_msl_hpa": float(last.get("pressure_msl_hpa", 1013.0) or 1013.0),
        "wind_gusts_kmh":   float(last.get("wind_gusts_kmh",    8.0) or  8.0),
        "precipitation_mm": float(last.get("precipitation_mm",  0.0) or  0.0),
        "is_raining":       int(bool(last.get("is_raining", False))),
    }

    start_dt = recent_df["datetime"].max() + timedelta(hours=1)
    results  = []

    for h in range(1, horizon_hours + 1):
        target_dt = start_dt + timedelta(hours=h - 1)
        feat = _build_feature_row(target_dt, history, weather_ctx)
        X    = pd.DataFrame([feat])[feature_cols]
        pred = float(model.predict(X)[0])
        pred = max(0.0, min(500.0, pred))

        meta  = _load_metadata()
        rmse  = (meta.get("cities", {}).get(city, {})
                 .get("xgb", {}).get("rmse", 40.0)) or 40.0
        lower = max(0.0,   pred - rmse * 0.8)
        upper = min(500.0, pred + rmse * 0.8)

        results.append({"datetime": target_dt, "aqi": pred, "lower": lower, "upper": upper})
        history[target_dt] = pred

    return results


def _prophet_predict_horizon(
    models:       dict,
    anchor_dt:    datetime,
    horizon_days: int,
) -> pd.DataFrame:
    prophet_bundle = models.get("prophet")
    if not prophet_bundle:
        return pd.DataFrame()
    m      = prophet_bundle["model"]
    future = m.make_future_dataframe(periods=horizon_days, freq="D")
    fc     = m.predict(future)
    fc     = fc[fc["ds"] >= pd.Timestamp(anchor_dt.date())]
    return fc[["ds", "yhat", "yhat_lower", "yhat_upper"]].copy()


def generate_forecast(
    city:         str,
    recent_df:    pd.DataFrame,
    horizon_days: int = 7,
) -> List[dict]:
    """
    Main entry point for forecast generation.

    Args:
        city:         City name (lowercase)
        recent_df:    DataFrame with last 14+ days of actuals.
                      Required columns: datetime, india_aqi
                      Optional (improves accuracy): temperature_c, wind_speed_kmh,
                      humidity_percent, pressure_msl_hpa, wind_gusts_kmh,
                      precipitation_mm, is_raining
        horizon_days: 1, 3, or 7

    Returns:
        List of per-day prediction dicts
    """
    models = _load_models(city)
    if not models:
        raise ValueError(f"No trained models found for city '{city}'.")

    horizon_hours = horizon_days * 24
    anchor_dt     = recent_df["datetime"].max()

    xgb_hourly    = _xgb_predict_horizon(city, models, recent_df, horizon_hours)
    prophet_daily = _prophet_predict_horizon(models, anchor_dt, horizon_days)

    results = []
    for day in range(1, horizon_days + 1):
        target_date = (anchor_dt + timedelta(days=day)).date()

        day_xgb = [r for r in xgb_hourly if r["datetime"].date() == target_date]
        if day_xgb:
            xgb_mean  = float(np.mean([r["aqi"]   for r in day_xgb]))
            xgb_lower = float(np.mean([r["lower"] for r in day_xgb]))
            xgb_upper = float(np.mean([r["upper"] for r in day_xgb]))
        else:
            xgb_mean  = float(recent_df["india_aqi"].iloc[-1])
            xgb_lower = xgb_mean * 0.8
            xgb_upper = xgb_mean * 1.2

        p_row = (prophet_daily[
                     pd.to_datetime(prophet_daily["ds"]).dt.date == target_date
                 ] if len(prophet_daily) else pd.DataFrame())

        if len(p_row):
            p_val   = float(p_row["yhat"].iloc[0])
            p_lower = float(p_row["yhat_lower"].iloc[0])
            p_upper = float(p_row["yhat_upper"].iloc[0])
            final     = max(0, min(500, 0.6 * xgb_mean  + 0.4 * p_val))
            final_low = max(0, min(500, 0.6 * xgb_lower + 0.4 * p_lower))
            final_up  = max(0, min(500, 0.6 * xgb_upper + 0.4 * p_upper))
        else:
            final, final_low, final_up = xgb_mean, xgb_lower, xgb_upper

        results.append({
            "predicted_for_date":  datetime.combine(target_date, datetime.min.time()),
            "predicted_india_aqi": round(final,     1),
            "confidence_lower":    round(final_low, 1),
            "confidence_upper":    round(final_up,  1),
            "predicted_category":  aqi_category(final),
            "horizon_days":        day,
        })

    return results
