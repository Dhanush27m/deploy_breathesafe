"""
BreatheSafe — Forecast Router (Phase 4)

Endpoints:
  GET  /forecast/cities              — list cities with trained models
  GET  /forecast/{city}/predict      — generate 1/3/7-day forecast
  GET  /forecast/{city}/accuracy     — model accuracy metrics
  POST /forecast/train               — trigger background model training (auth required)
"""

import subprocess
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.city import City
from app.models.aqi_data import AQIData
from app.models.monitoring_station import MonitoringStation
from app.models.prediction import Prediction
from app.models.user import User

router = APIRouter()


# ── Helper: fetch recent AQI rows for a city ──────────────────────────────────
def _get_recent_df(city_name: str, db: Session, lookback_days: int = 14):
    """Return a pandas DataFrame of the last `lookback_days` days for the city."""
    import pandas as pd

    city = db.query(City).filter(func.lower(City.name) == city_name.lower()).first()
    if not city:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"City '{city_name}' not found.",
        )

    station = db.query(MonitoringStation).filter(
        MonitoringStation.city_id == city.id
    ).first()
    if not station:
        raise HTTPException(status_code=404, detail="No monitoring station found.")

    latest_dt = (
        db.query(func.max(AQIData.datetime))
        .filter(AQIData.station_id == station.id)
        .scalar()
    )
    if not latest_dt:
        raise HTTPException(status_code=404, detail="No AQI data available.")

    cutoff = latest_dt - timedelta(days=lookback_days)
    rows = (
        db.query(AQIData)
        .filter(AQIData.station_id == station.id, AQIData.datetime >= cutoff)
        .order_by(AQIData.datetime)
        .all()
    )

    df = pd.DataFrame([{
        "datetime":          r.datetime,
        "india_aqi":         r.india_aqi,
        "temperature_c":     r.temperature_c     or 20.0,
        "wind_speed_kmh":    r.wind_speed_kmh    or 5.0,
        "humidity_percent":  r.humidity_percent  or 60.0,
        "pressure_msl_hpa":  r.pressure_msl_hpa  or 1013.0,
        "wind_gusts_kmh":    r.wind_gusts_kmh    or 8.0,
        "precipitation_mm":  r.precipitation_mm  or 0.0,
        "is_raining":        int(r.is_raining or False),
    } for r in rows if r.india_aqi is not None])

    return city, df


# ── 1. List cities with trained models ────────────────────────────────────────
@router.get("/cities", response_model=List[dict])
def forecast_cities():
    """List all cities that have trained models available."""
    from app.ml.predictor import trained_cities, _load_metadata

    cities  = trained_cities()
    meta    = _load_metadata()
    trained = meta.get("trained_at", "unknown")

    return [
        {
            "city":         c,
            "trained_at":   trained,
            "xgb_mae":      meta.get("cities", {}).get(c, {}).get("xgb", {}).get("mae"),
            "prophet_mae":  meta.get("cities", {}).get(c, {}).get("prophet", {}).get("mae"),
        }
        for c in sorted(cities)
    ]


# ── 2. Generate forecast ──────────────────────────────────────────────────────
@router.get("/{city_name}/predict", response_model=dict)
def predict_city(
    city_name: str,
    horizon: int = Query(7, ge=1, le=7, description="Forecast horizon in days (1, 3, or 7)"),
    save: bool  = Query(True, description="Persist predictions to DB"),
    db: Session = Depends(get_db),
):
    """
    Generate AQI forecast for the given city.
    Uses XGBoost + Prophet ensemble (60/40 blend).
    If no trained models exist, returns a statistical baseline forecast.
    """
    from app.ml.predictor import generate_forecast, models_available

    city_obj, recent_df = _get_recent_df(city_name, db, lookback_days=14)

    if len(recent_df) < 24:
        raise HTTPException(
            status_code=400,
            detail="Insufficient recent data to generate forecast (need ≥24 hours).",
        )

    # ── Model-based or statistical baseline ──
    if models_available(city_obj.name):
        predictions = generate_forecast(city_obj.name, recent_df, horizon_days=horizon)
        source = "ml_ensemble"
    else:
        # Statistical fallback: 7-day rolling mean ± std
        predictions = _statistical_baseline(recent_df, horizon, city_name)
        source = "statistical_baseline"

    # ── Persist to DB (non-fatal — prediction still returns even if save fails) ──
    if save:
        try:
            # Use timezone-aware UTC datetime so PostgreSQL timestamptz comparison works
            one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
            db.query(Prediction).filter(
                Prediction.city_id == city_obj.id,
                Prediction.created_at >= one_hour_ago,
            ).delete(synchronize_session=False)

            for p in predictions:
                db.add(Prediction(
                    city_id             = city_obj.id,
                    predicted_for_date  = p["predicted_for_date"],
                    predicted_india_aqi = p["predicted_india_aqi"],
                    confidence_lower    = p["confidence_lower"],
                    confidence_upper    = p["confidence_upper"],
                    predicted_category  = p["predicted_category"],
                    horizon_days        = p["horizon_days"],
                    model_version       = "xgb_v1.0" if source == "ml_ensemble" else "baseline",
                ))
            db.commit()
        except Exception as db_err:
            db.rollback()
            print(f"[forecast] DB save failed (non-fatal): {db_err}")

    # Serialise datetime objects to ISO strings so JSON encoding always succeeds
    serialised_predictions = [
        {**p, "predicted_for_date": p["predicted_for_date"].isoformat()}
        for p in predictions
    ]

    return {
        "city":             city_obj.name,
        "state":            city_obj.state,
        "generated_at":     datetime.now(timezone.utc).isoformat(),
        "source":           source,
        "horizon_days":     horizon,
        "anchor_datetime":  recent_df["datetime"].max().isoformat(),
        "current_aqi":      float(recent_df["india_aqi"].iloc[-1]),
        "predictions":      serialised_predictions,
    }


def _statistical_baseline(recent_df, horizon: int, city_name: str) -> List[dict]:
    """Fallback: use 7-day rolling stats when no trained model is available."""
    import numpy as np
    from app.ml.predictor import aqi_category

    series = recent_df["india_aqi"]
    mean   = float(series.tail(168).mean())
    std    = float(series.tail(168).std()) if len(series) > 1 else 20.0
    anchor = recent_df["datetime"].max()

    results = []
    for day in range(1, horizon + 1):
        target_dt = anchor + timedelta(days=day)
        # Simple seasonal adjustment: use same weekday from last week
        same_dow = recent_df[
            recent_df["datetime"].dt.dayofweek == target_dt.weekday()
        ]["india_aqi"]
        est = float(same_dow.tail(4).mean()) if len(same_dow) else mean
        results.append({
            "predicted_for_date":  target_dt.replace(hour=0, minute=0, second=0, microsecond=0),
            "predicted_india_aqi": round(max(0, min(500, est)), 1),
            "confidence_lower":    round(max(0,   est - std), 1),
            "confidence_upper":    round(min(500, est + std), 1),
            "predicted_category":  aqi_category(est),
            "horizon_days":        day,
        })
    return results


# ── 3. Model accuracy metrics ─────────────────────────────────────────────────
@router.get("/{city_name}/accuracy", response_model=dict)
def model_accuracy(city_name: str):
    """Return MAE / RMSE metrics from the last training run."""
    from app.ml.predictor import _load_metadata

    meta  = _load_metadata()
    city  = city_name.lower().strip()
    stats = meta.get("cities", {}).get(city)

    if not stats:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No training metrics found for '{city_name}'. "
                   "Run POST /forecast/train first.",
        )

    return {
        "city":          city,
        "trained_at":    meta.get("trained_at"),
        "model_version": meta.get("model_version"),
        "xgb":           stats.get("xgb",     {}),
        "prophet":       stats.get("prophet",  {}),
    }


# ── 4. Trigger training ───────────────────────────────────────────────────────
@router.post("/train", status_code=status.HTTP_202_ACCEPTED)
def trigger_training(
    background_tasks: BackgroundTasks,
    city: Optional[str] = Query(None, description="Train one city only; omit for all"),
    skip_prophet: bool   = Query(False),
    current_user: User   = Depends(get_current_user),
):
    """
    Kick off model training in the background.
    Returns immediately; training runs asynchronously.
    """
    def _run_training(city_arg, skip_prophet_arg):
        cmd = ["python", "/app/train_models.py"]
        if city_arg:
            cmd += ["--city", city_arg.lower()]
        if skip_prophet_arg:
            cmd.append("--skip-prophet")
        subprocess.run(cmd, check=False)

    background_tasks.add_task(_run_training, city, skip_prophet)

    return {
        "status":  "accepted",
        "message": f"Training started for {'all cities' if not city else city}. "
                   "Check GET /forecast/cities for completion.",
        "city":    city or "all",
    }
