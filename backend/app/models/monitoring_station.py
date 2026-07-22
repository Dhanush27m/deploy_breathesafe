"""
BreatheSafe — Monitoring Station Model
Each station is a physical or virtual AQI monitoring point.
  - CSV cities  → one virtual station per city  (e.g. station_id='DELHI_CSV')
  - OpenAQ      → real stations with OpenAQ location_id
"""

import enum

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class DataSourceEnum(str, enum.Enum):
    csv    = "csv"       # Historical CSV data (29 state capitals)
    openaq = "openaq"    # Live OpenAQ feed


class MonitoringStation(Base):
    __tablename__ = "monitoring_stations"

    id           = Column(Integer, primary_key=True, index=True)
    station_id   = Column(String(100), unique=True, index=True, nullable=False)
    # e.g. "DELHI_CSV" for virtual, or "2178" for real OpenAQ location_id
    station_name = Column(String(200), nullable=True)
    city_id      = Column(Integer, ForeignKey("cities.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    latitude     = Column(Float, nullable=True)
    longitude    = Column(Float, nullable=True)
    data_source  = Column(SAEnum(DataSourceEnum), nullable=False,
                          default=DataSourceEnum.csv)
    is_active    = Column(Boolean, default=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    city     = relationship("City", back_populates="stations")
    aqi_data = relationship("AQIData", back_populates="station",
                            cascade="all, delete-orphan")

    def __repr__(self):
        return (f"<MonitoringStation id={self.id} "
                f"station_id={self.station_id} source={self.data_source}>")
