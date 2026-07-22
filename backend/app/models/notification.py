"""
BreatheSafe — Notification Model
Stores in-app and email alerts sent to users.
"""

import enum

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class NotificationTypeEnum(str, enum.Enum):
    aqi_threshold  = "aqi_threshold"   # Current AQI exceeded user's threshold
    forecast_alert = "forecast_alert"  # Forecasted AQI will be high
    risk_alert     = "risk_alert"      # User's personal risk is High/Severe (in-app)
    route_saved    = "route_saved"     # Route save confirmation (email tracking)
    route_monitor  = "route_monitor"   # Scheduled AQI update for a saved route


class Notification(Base):
    __tablename__ = "notifications"

    id                = Column(Integer, primary_key=True, index=True)
    user_id           = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                               nullable=False, index=True)
    city_id           = Column(Integer, ForeignKey("cities.id"), nullable=True)
    route_id          = Column(Integer, ForeignKey("routes.id", ondelete="SET NULL"),
                               nullable=True, index=True)

    # Content
    notification_type = Column(String(30), nullable=False)
    message           = Column(String(500), nullable=False)
    aqi_value         = Column(Float, nullable=True)    # AQI that triggered alert

    # Status
    is_read           = Column(Boolean, default=False)
    sent_via_email    = Column(Boolean, default=False)

    sent_at    = Column(DateTime(timezone=True), server_default=func.now(),
                        index=True)
    read_at    = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="notifications")
    city = relationship("City", back_populates="notifications")

    def __repr__(self):
        return (f"<Notification user={self.user_id} "
                f"type={self.notification_type} read={self.is_read}>")
