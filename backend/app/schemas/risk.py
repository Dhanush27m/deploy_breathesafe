"""
BreatheSafe — Risk Assessment Pydantic Schemas
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, List
from datetime import datetime
from app.models.risk_log import RiskCategoryEnum
from app.models.health_profile import ActivityLevelEnum


class RiskCalculateRequest(BaseModel):
    city:            str
    exposure_hours:  float = Field(2.0, ge=0.0, le=24.0)
    activity_level:  ActivityLevelEnum = ActivityLevelEnum.light
    use_forecast:    bool  = False   # Use forecasted AQI vs current AQI
    horizon_days:    int   = Field(1, ge=1, le=7)


class FactorsOut(BaseModel):
    aqi_contribution:       float
    age_contribution:       float
    condition_contribution: float
    duration_contribution:  float
    activity_contribution:  float


class RiskOut(BaseModel):
    risk_score:    float
    risk_category: RiskCategoryEnum
    aqi_used:      float
    factors:       FactorsOut
    explanation:   str
    city:          str
    timestamp:     datetime

    model_config = {"from_attributes": True}


class RiskLogOut(BaseModel):
    id:            int
    risk_score:    float
    risk_category: RiskCategoryEnum
    aqi_used:      float
    explanation:   Optional[str]
    timestamp:     datetime

    model_config = {"from_attributes": True}


class RiskHistoryOut(BaseModel):
    days:    int
    records: List[RiskLogOut]
