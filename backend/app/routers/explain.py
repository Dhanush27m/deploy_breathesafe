"""
BreatheSafe — Explainability Router (Phase 7)

Endpoints:
  GET /explain/forecast/{city}       — SHAP feature importance for XGBoost prediction
  GET /explain/risk/{log_id}         — Factor breakdown for a PAERI risk log
  GET /explain/aqi/{city}/trends     — Natural language AQI trend summary
  GET /explain/aqi/{city}/pollutants — Pollutant contribution breakdown
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.aqi_data import AQIData
from app.models.city import City
from app.models.monitoring_station import MonitoringStation
from app.models.risk_log import RiskLog
from app.models.user import User

router = APIRouter()

# ── Human-readable feature names ──────────────────────────────────────────────
FEATURE_LABELS = {
    "hour":             "Hour of day",
    "day_of_week":      "Day of week",
    "month":            "Month",
    "is_weekend":       "Weekend effect",
    "lag_24h":          "AQI 24 h ago",
    "lag_48h":          "AQI 48 h ago",
    "lag_168h":         "AQI 7 days ago",
    "rolling_24h_mean": "24-hour rolling average",
    "rolling_7d_mean":  "7-day rolling average",
    "rolling_7d_std":   "AQI variability (7-day std)",
    "temperature_c":    "Temperature (°C)",
    "wind_speed_kmh":   "Wind speed (km/h)",
}


def _get_city_or_404(city_name: str, db: Session) -> City:
    city = db.query(City).filter(func.lower(City.name) == city_name.lower()).first()
    if not city:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"City '{city_name}' not found.",
        )
    return city


def _get_station(city_id: int, db: Session) -> MonitoringStation:
    station = db.query(MonitoringStation).filter(
        MonitoringStation.city_id == city_id
    ).first()
    if not station:
        raise HTTPException(status_code=404, detail="No monitoring station found.")
    return station


# ── 1. SHAP forecast explanation ──────────────────────────────────────────────
@router.get("/forecast/{city_name}", response_model=dict)
def explain_forecast(city_name: str, db: Session = Depends(get_db)):
    """
    Run SHAP TreeExplainer on the trained XGBoost model for this city
    and return the top feature contributions for the latest prediction point.
    """
    from app.ml.predictor import _load_models, models_available

    city = _get_city_or_404(city_name, db)
    cname = city.name.lower()

    if not models_available(cname):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No trained model for '{city_name}'. "
                   "Run POST /forecast/train first.",
        )

    # ── Build feature row from latest actuals ─────────────────────────────────
    station  = _get_station(city.id, db)
    latest_q = (
        db.query(AQIData)
        .filter(AQIData.station_id == station.id, AQIData.india_aqi != None)
        .order_by(desc(AQIData.datetime))
        .limit(200)
        .all()
    )
    if len(latest_q) < 50:
        raise HTTPException(status_code=400, detail="Insufficient data for SHAP analysis.")

    import pandas as pd

    df = pd.DataFrame([{
        "datetime":       r.datetime,
        "india_aqi":      r.india_aqi,
        "temperature_c":  r.temperature_c or 20.0,
        "wind_speed_kmh": r.wind_speed_kmh or 5.0,
    } for r in reversed(latest_q)])

    df = df.sort_values("datetime").reset_index(drop=True)

    # Build features for the most recent row
    df["hour"]        = df["datetime"].dt.hour
    df["day_of_week"] = df["datetime"].dt.dayofweek
    df["month"]       = df["datetime"].dt.month
    df["is_weekend"]  = df["day_of_week"].isin([5, 6]).astype(int)

    aqi = df["india_aqi"]
    df["lag_24h"]          = aqi.shift(24)
    df["lag_48h"]          = aqi.shift(48)
    df["lag_168h"]         = aqi.shift(168)
    df["rolling_24h_mean"] = aqi.shift(1).rolling(24,  min_periods=8).mean()
    df["rolling_7d_mean"]  = aqi.shift(1).rolling(168, min_periods=24).mean()
    df["rolling_7d_std"]   = aqi.shift(1).rolling(168, min_periods=24).std()

    feature_cols = list(FEATURE_LABELS.keys())
    df = df.dropna(subset=feature_cols)

    if df.empty:
        raise HTTPException(status_code=400, detail="Could not compute features.")

    X = df[feature_cols].tail(50)  # last 50 rows for SHAP background

    # ── SHAP analysis ─────────────────────────────────────────────────────────
    try:
        import shap
        models   = _load_models(cname)
        xgb_mdl  = models["xgb"]["model"]

        explainer   = shap.TreeExplainer(xgb_mdl)
        shap_values = explainer.shap_values(X)

        # Last row = most recent prediction point
        last_shap   = shap_values[-1]
        last_X      = X.iloc[-1]

        contributions = []
        for i, feat in enumerate(feature_cols):
            contributions.append({
                "feature":      feat,
                "label":        FEATURE_LABELS.get(feat, feat),
                "feature_value":round(float(last_X[feat]), 3),
                "shap_value":   round(float(last_shap[i]), 3),
                "direction":    "increases_aqi" if last_shap[i] > 0 else "decreases_aqi",
            })

        contributions.sort(key=lambda x: abs(x["shap_value"]), reverse=True)
        top5 = contributions[:5]

        # Build narrative
        top_pos = [c for c in top5 if c["shap_value"] > 0]
        top_neg = [c for c in top5 if c["shap_value"] < 0]
        pos_str = ", ".join(c["label"] for c in top_pos[:2]) if top_pos else "none"
        neg_str = ", ".join(c["label"] for c in top_neg[:2]) if top_neg else "none"
        narrative = (
            f"For {city.name.title()}, the main factors driving AQI higher are: {pos_str}. "
            f"Factors helping keep AQI lower: {neg_str}."
        )

        return {
            "city":          city.name,
            "analysis_time": datetime.utcnow().isoformat(),
            "base_value":    round(float(explainer.expected_value), 1),
            "predicted_aqi": round(float(xgb_mdl.predict(X.tail(1))[0]), 1),
            "top_features":  top5,
            "all_features":  contributions,
            "narrative":     narrative,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"SHAP analysis failed: {str(e)}",
        )


# ── 2. PAERI risk log explanation ─────────────────────────────────────────────
@router.get("/risk/{log_id}", response_model=dict)
def explain_risk(
    log_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return a detailed factor breakdown for a stored PAERI risk calculation.
    """
    log = db.query(RiskLog).filter(
        RiskLog.id == log_id,
        RiskLog.user_id == current_user.id,
    ).first()

    if not log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Risk log {log_id} not found.",
        )

    factors = log.factors_json or {}

    # Build human-readable breakdown
    FACTOR_LABELS = {
        "aqi_contribution":           "Base AQI risk level",
        "age_contribution":           "Age-adjusted multiplier",
        "condition_contribution":     "Health condition multiplier",
        "activity_contribution":      "Physical activity level",
        "duration_contribution":      "Outdoor exposure duration",
        "sensitivity_contribution":   "Personal sensitivity level",
    }

    FACTOR_TIPS = {
        "age_contribution": (
            "Children (<13) and elderly (>60) are more vulnerable to air pollution." ),
        "condition_contribution": (
            "Pre-existing conditions like asthma or heart disease amplify risk." ),
        "activity_contribution": (
            "Intense activity means faster/deeper breathing, increasing pollutant intake." ),
        "duration_contribution": (
            "Longer outdoor exposure accumulates more pollutant intake." ),
        "sensitivity_contribution": (
            "Your self-reported sensitivity level adjusts the final score." ),
    }

    breakdown = []
    for key, val in factors.items():
        breakdown.append({
            "factor":      key,
            "label":       FACTOR_LABELS.get(key, key),
            "value":       val,
            "impact":      "neutral" if val == 1.0 else ("increases_risk" if val > 1.0 else "decreases_risk"),
            "tip":         FACTOR_TIPS.get(key, ""),
        })

    # Dominant factors
    dominant = sorted(breakdown, key=lambda x: abs(x["value"] - 1.0), reverse=True)

    # Narrative
    dom_labels = [d["label"] for d in dominant[:2] if d["value"] != 1.0]
    if dom_labels:
        narrative = (
            f"Your risk score of {log.risk_score:.0f}/100 ({log.risk_category}) "
            f"was most influenced by: {', '.join(dom_labels)}."
        )
    else:
        narrative = (
            f"Your risk score of {log.risk_score:.0f}/100 ({log.risk_category}) "
            "is primarily driven by the current AQI level."
        )

    return {
        "log_id":         log.id,
        "risk_score":     log.risk_score,
        "risk_category":  log.risk_category,
        "aqi_used":       log.aqi_used,
        "timestamp":      log.timestamp,
        "factor_breakdown": breakdown,
        "dominant_factors": [d["label"] for d in dominant[:3]],
        "narrative":      narrative,
        "original_explanation": log.explanation,
    }


# ── 3. AQI trend summary ──────────────────────────────────────────────────────
@router.get("/aqi/{city_name}/trends", response_model=dict)
def aqi_trends(
    city_name: str,
    db: Session = Depends(get_db),
):
    """
    Natural language trend summary: 7-day vs 30-day change,
    worst time of day, best/worst day of week, seasonal pattern.
    """
    city    = _get_city_or_404(city_name, db)
    station = _get_station(city.id, db)

    has_data = (
        db.query(func.count(AQIData.id))
        .filter(AQIData.station_id == station.id)
        .scalar()
    )
    if not has_data:
        raise HTTPException(status_code=404, detail="No AQI data found.")

    # Anchor to current IST time so "last 7 days" always means real last 7 days
    latest_dt = datetime.utcnow() + timedelta(hours=5, minutes=30)

    # Pull last 90 days
    cutoff = latest_dt - timedelta(days=90)
    rows = (
        db.query(AQIData)
        .filter(
            AQIData.station_id == station.id,
            AQIData.datetime >= cutoff,
            AQIData.india_aqi != None,
        )
        .order_by(AQIData.datetime)
        .all()
    )

    if len(rows) < 24:
        raise HTTPException(status_code=400, detail="Insufficient data for trend analysis.")

    import pandas as pd
    df = pd.DataFrame([{
        "datetime":   r.datetime,
        "india_aqi":  r.india_aqi,
        "time_of_day":r.time_of_day,
        "season":     r.season,
    } for r in rows])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["date"]     = df["datetime"].dt.date
    df["dow_name"] = df["datetime"].dt.day_name()
    df["hour"]     = df["datetime"].dt.hour

    # ── Last 7 days vs prior 7 days ───────────────────────────────────────────
    last7   = df[df["datetime"] >= latest_dt - timedelta(days=7)]["india_aqi"]
    prior7  = df[(df["datetime"] >= latest_dt - timedelta(days=14)) &
                 (df["datetime"] <  latest_dt - timedelta(days=7))]["india_aqi"]
    last30  = df[df["datetime"] >= latest_dt - timedelta(days=30)]["india_aqi"]

    avg_7d  = round(float(last7.mean()),  1) if len(last7)  else None
    avg_30d = round(float(last30.mean()), 1) if len(last30) else None
    change_7d = None
    trend_dir = "stable"
    if avg_7d and len(prior7):
        prior_avg = float(prior7.mean())
        if prior_avg > 0:
            change_pct = (avg_7d - prior_avg) / prior_avg * 100
            change_7d  = round(change_pct, 1)
            trend_dir  = "improving" if change_pct < -5 else ("worsening" if change_pct > 5 else "stable")

    # ── Worst time of day ─────────────────────────────────────────────────────
    # Derive time_of_day from hour if the column is null (pipeline lag)
    df["time_of_day"] = df["time_of_day"].fillna(
        df["hour"].map(
            lambda h: "night" if h < 6 else ("morning" if h < 12 else ("afternoon" if h < 18 else "evening"))
        )
    )
    tod_avg = df.groupby("time_of_day")["india_aqi"].mean()
    worst_tod = tod_avg.idxmax() if len(tod_avg) else "unknown"
    best_tod  = tod_avg.idxmin() if len(tod_avg) else "unknown"

    # ── Day of week pattern ───────────────────────────────────────────────────
    dow_avg = df.groupby("dow_name")["india_aqi"].mean()
    worst_dow = dow_avg.idxmax() if len(dow_avg) else "unknown"
    best_dow  = dow_avg.idxmin() if len(dow_avg) else "unknown"

    # ── Season pattern ────────────────────────────────────────────────────────
    season_avg = df.dropna(subset=["season"]).groupby("season")["india_aqi"].mean()
    worst_season = season_avg.idxmax() if len(season_avg) else "unknown"
    best_season  = season_avg.idxmin() if len(season_avg) else "unknown"

    # ── Narrative ─────────────────────────────────────────────────────────────
    trend_sentence = {
        "improving": f"Air quality has improved by {abs(change_7d):.0f}% over the last 7 days.",
        "worsening": f"Air quality has worsened by {abs(change_7d):.0f}% over the last 7 days.",
        "stable":    "Air quality has been relatively stable over the last 7 days.",
    }.get(trend_dir, "")

    narrative = (
        f"{city.name.title()} — {trend_sentence} "
        f"Avoid outdoor activity during {worst_tod.replace('_', ' ')} hours. "
        f"Air is cleanest during {best_tod.replace('_', ' ')}. "
        f"Worst season historically: {worst_season.replace('_', ' ')}."
    )

    return {
        "city":          city.name,
        "state":         city.state,
        "data_through":  latest_dt.isoformat(),
        "trend_direction": trend_dir,
        "avg_aqi_7d":    avg_7d,
        "avg_aqi_30d":   avg_30d,
        "change_7d_pct": change_7d,
        "time_of_day_pattern": {
            "worst": worst_tod,
            "best":  best_tod,
            "averages": {k: round(float(v), 1) for k, v in tod_avg.items()},
        },
        "day_of_week_pattern": {
            "worst": worst_dow,
            "best":  best_dow,
            "averages": {k: round(float(v), 1) for k, v in dow_avg.items()},
        },
        "seasonal_pattern": {
            "worst": worst_season,
            "best":  best_season,
            "averages": {k: round(float(v), 1) for k, v in season_avg.items()},
        },
        "narrative": narrative,
    }


# ── 4. Pollutant contribution breakdown ───────────────────────────────────────
@router.get("/aqi/{city_name}/pollutants", response_model=dict)
def pollutant_breakdown(
    city_name: str,
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """
    Show the average concentration and contribution of each pollutant
    to India AQI over the last N days.
    """
    city    = _get_city_or_404(city_name, db)
    station = _get_station(city.id, db)

    latest_dt = (
        db.query(func.max(AQIData.datetime))
        .filter(AQIData.station_id == station.id)
        .scalar()
    )
    if not latest_dt:
        raise HTTPException(status_code=404, detail="No AQI data found.")

    cutoff = latest_dt - timedelta(days=days)
    rows = (
        db.query(AQIData)
        .filter(AQIData.station_id == station.id, AQIData.datetime >= cutoff)
        .all()
    )

    import numpy as np

    POLLUTANTS = {
        "pm2_5_ugm3":  {"name": "PM2.5",  "unit": "µg/m³", "standard": 60.0},
        "pm10_ugm3":   {"name": "PM10",   "unit": "µg/m³", "standard": 100.0},
        "no2_ugm3":    {"name": "NO₂",    "unit": "µg/m³", "standard": 80.0},
        "so2_ugm3":    {"name": "SO₂",    "unit": "µg/m³", "standard": 80.0},
        "co_ugm3":     {"name": "CO",     "unit": "µg/m³", "standard": 10000.0},
        "o3_ugm3":     {"name": "O₃",     "unit": "µg/m³", "standard": 100.0},
    }

    data = {col: [] for col in POLLUTANTS}
    for r in rows:
        for col in POLLUTANTS:
            v = getattr(r, col, None)
            if v is not None:
                data[col].append(v)

    results = []
    for col, meta in POLLUTANTS.items():
        vals = data[col]
        if not vals:
            continue
        avg = float(np.mean(vals))
        pct_over = round(sum(1 for v in vals if v > meta["standard"]) / len(vals) * 100, 1)
        results.append({
            "pollutant":         meta["name"],
            "column":            col,
            "avg_concentration": round(avg, 2),
            "unit":              meta["unit"],
            "national_standard": meta["standard"],
            "pct_exceeding_standard": pct_over,
            "status": "Exceeds standard" if avg > meta["standard"] else "Within standard",
        })

    results.sort(key=lambda x: x["pct_exceeding_standard"], reverse=True)

    dominant = results[0]["pollutant"] if results else "Unknown"
    narrative = (
        f"Over the last {days} days in {city.name.title()}, "
        f"{dominant} is the dominant pollutant by exceedance frequency. "
        + (f"PM2.5 exceeded national standards "
           f"{next((r['pct_exceeding_standard'] for r in results if 'PM2.5' in r['pollutant']), 0):.0f}% "
           "of the time." if any("PM2.5" in r["pollutant"] for r in results) else "")
    )

    return {
        "city":       city.name,
        "days":       days,
        "from":       cutoff.isoformat(),
        "to":         latest_dt.isoformat(),
        "pollutants": results,
        "dominant_pollutant": dominant,
        "narrative":  narrative,
    }
