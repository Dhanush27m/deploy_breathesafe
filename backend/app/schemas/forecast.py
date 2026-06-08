"""
BreatheSafe — Forecast Pydantic Schemas
"""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class PredictionOut(BaseModel):
    predicted_for_date:  datetime
    predicted_india_aqi: float
    confidence_lower:    Optional[float]
    confidence_upper:    Optional[float]
    predicted_category:  Optional[str]
    horizon_days:        int

    model_config = {"from_attributes": True}


class ForecastOut(BaseModel):
    city:        str
    generated_at: datetime
    predictions: List[PredictionOut]
    model_version: Optional[str]
    mae:          Optional[float]
    rmse:         Optional[float]


class ForecastAccuracyOut(BaseModel):
    city:    str
    mae:     Optional[float]
    rmse:    Optional[float]
    mape:    Optional[float]
    model_version: Optional[str]
