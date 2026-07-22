"""
BreatheSafe — Risk Assessment Router (Phase 5)

Endpoints:
  POST /risk/calculate        — compute PAERI score for authenticated user
  GET  /risk/history          — past risk calculations for the user
  GET  /risk/cities/snapshot  — risk snapshot for all 29 cities (uses a reference profile)
"""

from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.aqi_data import AQIData
from app.models.city import City
from app.models.health_profile import HealthProfile
from app.models.monitoring_station import MonitoringStation
from app.models.risk_log import RiskCategoryEnum, RiskLog
from app.models.user import User
from app.schemas.risk import RiskCalculateRequest
from app.services.paeri import calculate_paeri

router = APIRouter()


# ── Helper: get latest AQI for a city ────────────────────────────────────────
def _latest_aqi(city_id: int, db: Session) -> Optional[float]:
    station = (
        db.query(MonitoringStation)
        .filter(MonitoringStation.city_id == city_id)
        .first()
    )
    if not station:
        return None
    row = (
        db.query(AQIData)
        .filter(AQIData.station_id == station.id,
                AQIData.india_aqi != None)
        .order_by(desc(AQIData.datetime))
        .first()
    )
    return float(row.india_aqi) if row else None


# ── 1. Calculate PAERI ────────────────────────────────────────────────────────
@router.post("/calculate", response_model=dict)
def calculate_risk(
    payload: RiskCalculateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Compute a personalized PAERI risk score for the authenticated user.
    Requires an existing health profile (POST /profile/ first).
    """
    # ── Fetch health profile ──────────────────────────────────────────────────
    profile = (
        db.query(HealthProfile)
        .filter(HealthProfile.user_id == current_user.id)
        .first()
    )
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Health profile not found. Create one at POST /profile/ first.",
        )

    # ── Resolve city ──────────────────────────────────────────────────────────
    city = (
        db.query(City)
        .filter(func.lower(City.name) == payload.city.lower())
        .first()
    )
    if not city:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"City '{payload.city}' not found.",
        )

    # ── Get AQI ───────────────────────────────────────────────────────────────
    if payload.use_forecast:
        # Pull most recent stored prediction for the city
        from app.models.prediction import Prediction
        pred = (
            db.query(Prediction)
            .filter(
                Prediction.city_id == city.id,
                Prediction.horizon_days == payload.horizon_days,
            )
            .order_by(desc(Prediction.created_at))
            .first()
        )
        if not pred:
            raise HTTPException(
                status_code=404,
                detail=f"No forecast found for {payload.city}. "
                       "Call GET /forecast/{city}/predict first.",
            )
        aqi_value = pred.predicted_india_aqi
    else:
        aqi_value = _latest_aqi(city.id, db)
        if aqi_value is None:
            raise HTTPException(
                status_code=404,
                detail=f"No AQI data found for '{payload.city}'.",
            )

    # ── Compute PAERI ─────────────────────────────────────────────────────────
    activity_str = payload.activity_level.value  # "moderate" not "ActivityLevelEnum.moderate"
    result = calculate_paeri(
        aqi            = aqi_value,
        profile        = profile,
        exposure_hours = payload.exposure_hours,
        activity_level = activity_str,
    )

    # ── Map category string → enum ────────────────────────────────────────────
    cat_map = {"Low": RiskCategoryEnum.low, "Moderate": RiskCategoryEnum.moderate,
               "High": RiskCategoryEnum.high, "Severe": RiskCategoryEnum.severe}
    risk_cat_enum = cat_map.get(result.risk_category, RiskCategoryEnum.moderate)

    # ── Persist to risk_logs ──────────────────────────────────────────────────
    log = RiskLog(
        user_id        = current_user.id,
        city_id        = city.id,
        risk_score     = result.risk_score,
        risk_category  = risk_cat_enum,
        aqi_used       = result.aqi_used,
        exposure_hours = payload.exposure_hours,
        activity_level = activity_str,
        age_used       = profile.age,
        factors_json   = result.factors,
        explanation    = result.explanation,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    return {
        "id":              log.id,
        "risk_score":      result.risk_score,
        "risk_category":   result.risk_category,
        "aqi_used":        result.aqi_used,
        "city":            city.name,
        "state":           city.state,
        "timestamp":       log.timestamp,
        "factors":         result.factors,
        "recommendations": result.recommendations,
        "explanation":     result.explanation,
        "use_forecast":    payload.use_forecast,
    }


# ── 2. Risk history ────────────────────────────────────────────────────────────
@router.get("/history", response_model=dict)
def risk_history(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the authenticated user's past PAERI calculations."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    logs = (
        db.query(RiskLog)
        .filter(
            RiskLog.user_id == current_user.id,
            RiskLog.timestamp >= cutoff,
        )
        .order_by(desc(RiskLog.timestamp))
        .all()
    )

    records = [
        {
            "id":            log.id,
            "risk_score":    log.risk_score,
            "risk_category": log.risk_category,
            "aqi_used":      log.aqi_used,
            "city":          log.city.name if log.city else None,
            "activity_level":log.activity_level,
            "exposure_hours":log.exposure_hours,
            "timestamp":     log.timestamp,
            "explanation":   log.explanation,
        }
        for log in logs
    ]

    return {
        "user":        current_user.name,
        "days":        days,
        "total":       len(records),
        "records":     records,
    }


# ── 3. City-wide risk snapshot (all 29 cities, reference profile) ─────────────
@router.get("/cities/snapshot", response_model=List[dict])
def cities_risk_snapshot(
    age:              int   = Query(30,      ge=1,  le=100),
    exposure_hours:   float = Query(2.0,     ge=0,  le=24),
    activity_level:   str   = Query("light", pattern="^(resting|light|moderate|intense)$"),
    respiratory:      bool  = Query(False),
    heart_disease:    bool  = Query(False),
    db: Session = Depends(get_db),
):
    """
    Returns a risk snapshot for all 29 cities using a reference health profile.
    No login required — useful for the public dashboard.
    """
    # Build a lightweight in-memory profile object
    class _Profile:
        pass

    profile = _Profile()
    profile.age                 = age
    profile.respiratory_disease = respiratory
    profile.heart_disease       = heart_disease
    profile.diabetes            = False
    profile.kidney_disease      = False
    profile.is_smoker           = False
    profile.is_pregnant         = False
    profile.sensitivity_level   = "moderate"

    cities = db.query(City).filter(City.is_active == True).order_by(City.name).all()
    results = []

    for city in cities:
        aqi = _latest_aqi(city.id, db)
        if aqi is None:
            continue

        r = calculate_paeri(
            aqi            = aqi,
            profile        = profile,
            exposure_hours = exposure_hours,
            activity_level = activity_level,
        )

        results.append({
            "city":            city.name,
            "state":           city.state,
            "latitude":        city.latitude,
            "longitude":       city.longitude,
            "current_aqi":     aqi,
            "risk_score":      r.risk_score,
            "risk_category":   r.risk_category,
        })

    # Sort by risk score descending
    results.sort(key=lambda x: x["risk_score"], reverse=True)
    return results
