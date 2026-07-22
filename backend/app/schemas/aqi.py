"""
BreatheSafe — AQI Pydantic Schemas
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class CityOut(BaseModel):
    id:        int
    name:      str
    state:     str
    latitude:  float
    longitude: float

    model_config = {"from_attributes": True}


class AQIDataOut(BaseModel):
    id:                  int
    datetime:            datetime
    city:                str
    state:               str
    india_aqi:           Optional[float]
    india_aqi_category:  Optional[str]
    us_aqi:              Optional[float]
    pm2_5_ugm3:          Optional[float]
    pm10_ugm3:           Optional[float]
    no2_ugm3:            Optional[float]
    so2_ugm3:            Optional[float]
    co_ugm3:             Optional[float]
    o3_ugm3:             Optional[float]
    temperature_c:       Optional[float]
    wind_speed_kmh:      Optional[float]
    humidity_percent:    Optional[float]
    season:              Optional[str]

    model_config = {"from_attributes": True}


class AQICurrentOut(BaseModel):
    city:               str
    state:              str
    latitude:           float
    longitude:          float
    datetime:           datetime
    india_aqi:          Optional[float]
    india_aqi_category: Optional[str]
    pm2_5_ugm3:         Optional[float]
    pm10_ugm3:          Optional[float]
    temperature_c:      Optional[float]
    wind_speed_kmh:     Optional[float]
    humidity_percent:   Optional[float]

    model_config = {"from_attributes": True}


class AQIHistoryOut(BaseModel):
    city:    str
    days:    int
    records: List[AQIDataOut]
