"""
BreatheSafe — Health Profile Model
Stores user's health data used for personalized PAERI risk scoring.
"""

import enum

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class GenderEnum(str, enum.Enum):
    male        = "male"
    female      = "female"
    other       = "other"
    prefer_not  = "prefer_not_to_say"


class SensitivityEnum(str, enum.Enum):
    low      = "low"
    moderate = "moderate"
    high     = "high"
    very_high = "very_high"


class ActivityLevelEnum(str, enum.Enum):
    resting  = "resting"
    light    = "light"
    moderate = "moderate"
    intense  = "intense"


class HealthProfile(Base):
    __tablename__ = "health_profiles"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                         unique=True, nullable=False)

    # Demographics
    age         = Column(Integer, nullable=True)
    gender      = Column(SAEnum(GenderEnum), nullable=True)

    # Health conditions (boolean flags)
    respiratory_disease = Column(Boolean, default=False)   # Asthma, COPD, etc.
    heart_disease       = Column(Boolean, default=False)
    diabetes            = Column(Boolean, default=False)
    kidney_disease      = Column(Boolean, default=False)
    is_smoker           = Column(Boolean, default=False)
    is_pregnant         = Column(Boolean, default=False)

    # Preferences
    sensitivity_level       = Column(SAEnum(SensitivityEnum),
                                     default=SensitivityEnum.moderate)
    preferred_aqi_threshold = Column(Integer, default=100)   # Alert above this
    exposure_hours_per_day  = Column(Float,   default=2.0)   # Avg outdoor hours
    default_activity_level  = Column(SAEnum(ActivityLevelEnum),
                                     default=ActivityLevelEnum.light)

    # Home city (for default dashboard view)
    home_city   = Column(String(100), nullable=True)

    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="health_profile")

    def __repr__(self):
        return f"<HealthProfile user_id={self.user_id} age={self.age}>"
