"""
BreatheSafe — AQI Data Model
Hourly AQI + weather readings per monitoring station.
Directly mirrors the enriched CSV schema (35 columns).
"""

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base

# Using plain String instead of PostgreSQL ENUM for season/time_of_day
# so that any new CSV values (e.g. 'early_morning', 'night_late') never
# cause InvalidTextRepresentation errors during seeding.


class AQIData(Base):
    __tablename__ = "aqi_data"

    id         = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("monitoring_stations.id",
                        ondelete="CASCADE"), nullable=False, index=True)
    datetime   = Column(DateTime(timezone=False), nullable=False, index=True)

    # ── Pollutants (µg/m³) ────────────────────────────────────────────────────
    pm2_5_ugm3  = Column(Float, nullable=True)
    pm10_ugm3   = Column(Float, nullable=True)
    co_ugm3     = Column(Float, nullable=True)
    no2_ugm3    = Column(Float, nullable=True)
    so2_ugm3    = Column(Float, nullable=True)
    o3_ugm3     = Column(Float, nullable=True)
    dust_ugm3   = Column(Float, nullable=True)
    aod         = Column(Float, nullable=True)   # Aerosol Optical Depth

    # ── AQI Indices ───────────────────────────────────────────────────────────
    us_aqi              = Column(Float,   nullable=True)
    india_aqi           = Column(Float,   nullable=True, index=True)
    india_aqi_category  = Column(String(30), nullable=True)
    pm25_category_india = Column(String(30), nullable=True)

    # ── Weather ───────────────────────────────────────────────────────────────
    temperature_c      = Column(Float, nullable=True)   # From Open-Meteo
    wind_speed_kmh     = Column(Float, nullable=True)   # From Open-Meteo
    wind_gusts_kmh     = Column(Float, nullable=True)
    humidity_percent   = Column(Float, nullable=True)
    dew_point_c        = Column(Float, nullable=True)
    pressure_msl_hpa   = Column(Float, nullable=True)
    cloud_cover_percent= Column(Float, nullable=True)
    precipitation_mm   = Column(Float, nullable=True)
    is_raining         = Column(Boolean, nullable=True)
    heavy_rain         = Column(Boolean, nullable=True)

    # ── Temporal / Contextual ─────────────────────────────────────────────────
    month           = Column(Integer, nullable=True)
    day_name        = Column(String(10), nullable=True)
    is_weekend      = Column(Boolean, nullable=True)
    season          = Column(String(20), nullable=True)
    time_of_day     = Column(String(20), nullable=True)
    festival_period = Column(Boolean, nullable=True)
    crop_burning_season = Column(Boolean, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    station = relationship("MonitoringStation", back_populates="aqi_data")

    # Composite index for fast time-range + station queries
    __table_args__ = (
        Index("ix_aqi_data_station_datetime", "station_id", "datetime"),
    )

    def __repr__(self):
        return (f"<AQIData station={self.station_id} "
                f"dt={self.datetime} india_aqi={self.india_aqi}>")
