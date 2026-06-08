"""
BreatheSafe — Route Planner Pydantic Schemas
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.models.route import RouteTypeEnum, TravelModeEnum


class RouteRequest(BaseModel):
    source_lat:   float = Field(..., ge=-90,  le=90)
    source_lon:   float = Field(..., ge=-180, le=180)
    source_name:  Optional[str] = None
    dest_lat:     float = Field(..., ge=-90,  le=90)
    dest_lon:     float = Field(..., ge=-180, le=180)
    dest_name:    Optional[str] = None
    travel_mode:  TravelModeEnum = TravelModeEnum.driving
    # Optional via-point: when set, forces routing through this waypoint
    via_lat:      Optional[float] = Field(None, ge=-90,  le=90)
    via_lon:      Optional[float] = Field(None, ge=-180, le=180)
    via_name:     Optional[str] = None   # human-readable label for the via point


class RouteOut(BaseModel):
    route_type:             RouteTypeEnum
    travel_mode:            TravelModeEnum
    distance_km:            Optional[float]
    time_min:               Optional[float]
    avg_aqi_exposure:       Optional[float]
    exposure_reduction_pct: Optional[float]
    explanation:            Optional[str]
    route_geometry_json:    Optional[dict]

    model_config = {"from_attributes": True}


class RouteSuggestOut(BaseModel):
    source: str
    destination: str
    generated_at: datetime
    routes: List[RouteOut]


class OsrmRouteInput(BaseModel):
    """A single OSRM route geometry supplied by the browser."""
    distance_m: float
    duration_s: float
    geometry:   str             # encoded polyline string from OSRM
    via_lat:    Optional[float] = None
    via_lon:    Optional[float] = None


class RouteScoreRequest(BaseModel):
    """
    POST /route/score — browser sends pre-fetched OSRM geometries;
    backend scores AQI exposure and returns fastest/clean/balanced cards.
    Accepts the same optional via_* fields as RouteRequest so the via-picker
    flow works identically.
    """
    source_lat:   float = Field(..., ge=-90,  le=90)
    source_lon:   float = Field(..., ge=-180, le=180)
    source_name:  Optional[str] = None
    dest_lat:     float = Field(..., ge=-90,  le=90)
    dest_lon:     float = Field(..., ge=-180, le=180)
    dest_name:    Optional[str] = None
    travel_mode:  TravelModeEnum = TravelModeEnum.driving
    osrm_routes:  List[OsrmRouteInput]
    via_lat:      Optional[float] = Field(None, ge=-90,  le=90)
    via_lon:      Optional[float] = Field(None, ge=-180, le=180)
    via_name:     Optional[str] = None


class RouteSaveRequest(BaseModel):
    """Payload for POST /route/save — explicit user-initiated save with travel window."""
    route_type:             str
    source_lat:             float = Field(..., ge=-90,  le=90)
    source_lon:             float = Field(..., ge=-180, le=180)
    source_name:            Optional[str] = None
    dest_lat:               float = Field(..., ge=-90,  le=90)
    dest_lon:               float = Field(..., ge=-180, le=180)
    dest_name:              Optional[str] = None
    travel_mode:            str
    distance_km:            float
    time_min:               float
    avg_aqi_exposure:       float
    exposure_reduction_pct: Optional[float] = None
    explanation:            Optional[str]   = None
    planned_start:          datetime
    planned_end:            datetime
