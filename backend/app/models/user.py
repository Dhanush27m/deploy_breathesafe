"""
BreatheSafe — User Model
Stores registered user accounts with hashed passwords.
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    name          = Column(String(100), nullable=False)
    email         = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(),
                           onupdate=func.now())

    # Relationships
    health_profile = relationship("HealthProfile", back_populates="user",
                                  uselist=False, cascade="all, delete-orphan")
    risk_logs      = relationship("RiskLog",       back_populates="user",
                                  cascade="all, delete-orphan")
    notifications  = relationship("Notification",  back_populates="user",
                                  cascade="all, delete-orphan")
    routes         = relationship("Route",         back_populates="user",
                                  cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User id={self.id} email={self.email}>"
