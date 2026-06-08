"""
BreatheSafe — Models Package
Import all models here so SQLAlchemy/Alembic can discover them.
"""

from app.models.user               import User
from app.models.health_profile     import HealthProfile
from app.models.city               import City
from app.models.monitoring_station import MonitoringStation
from app.models.aqi_data           import AQIData
from app.models.prediction         import Prediction
from app.models.risk_log           import RiskLog
from app.models.notification       import Notification
from app.models.route              import Route

__all__ = [
    "User", "HealthProfile", "City", "MonitoringStation",
    "AQIData", "Prediction", "RiskLog", "Notification", "Route",
]