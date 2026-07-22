"""
BreatheSafe — Health Profile Pydantic Schemas
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.health_profile import ActivityLevelEnum, GenderEnum, SensitivityEnum


class HealthProfileCreate(BaseModel):
    age:                    Optional[int]   = Field(None, ge=1, le=120)
    gender:                 Optional[GenderEnum] = None
    respiratory_disease:    bool = False
    heart_disease:          bool = False
    diabetes:               bool = False
    kidney_disease:         bool = False
    is_smoker:              bool = False
    is_pregnant:            bool = False
    sensitivity_level:      SensitivityEnum = SensitivityEnum.moderate
    preferred_aqi_threshold:int  = Field(100, ge=0, le=500)
    exposure_hours_per_day: float = Field(2.0, ge=0.0, le=24.0)
    default_activity_level: ActivityLevelEnum = ActivityLevelEnum.light
    home_city:              Optional[str] = None


class HealthProfileUpdate(HealthProfileCreate):
    pass


class HealthProfileOut(HealthProfileCreate):
    id:         int
    user_id:    int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
