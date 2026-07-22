"""
BreatheSafe — City Model
Master list of supported Indian cities.
"""

from sqlalchemy import Boolean, Column, Float, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class City(Base):
    __tablename__ = "cities"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(100), unique=True, index=True, nullable=False)
    state       = Column(String(100), nullable=False)
    latitude    = Column(Float, nullable=False)
    longitude   = Column(Float, nullable=False)
    country     = Column(String(50), default="India")
    is_active   = Column(Boolean, default=True)

    # Relationships
    stations    = relationship("MonitoringStation", back_populates="city",
                               cascade="all, delete-orphan")
    predictions = relationship("Prediction", back_populates="city",
                               cascade="all, delete-orphan")
    risk_logs   = relationship("RiskLog", back_populates="city")
    notifications = relationship("Notification", back_populates="city")

    def __repr__(self):
        return f"<City id={self.id} name={self.name} state={self.state}>"
