"""
BreatheSafe — Auth Pydantic Schemas
Request/response models for registration, login, and JWT tokens.
"""

from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator


# ── Register ──────────────────────────────────────────────────────────────────
class UserRegister(BaseModel):
    name:     str
    email:    EmailStr
    password: str

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Name cannot be empty")
        return v.strip()

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        # bcrypt hard-rejects anything over 72 bytes — without this the request
        # would surface as an unhandled 500 instead of a validation error.
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 bytes")
        return v


# ── Login ─────────────────────────────────────────────────────────────────────
class UserLogin(BaseModel):
    email:    EmailStr
    password: str


# ── Token response ────────────────────────────────────────────────────────────
class Token(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    user:          "UserOut"


# ── User output (safe — no password) ──────────────────────────────────────────
class UserOut(BaseModel):
    id:         int
    name:       str
    email:      str
    is_active:  bool
    created_at: datetime

    model_config = {"from_attributes": True}


Token.model_rebuild()


# ── Refresh token request ─────────────────────────────────────────────────────
class RefreshRequest(BaseModel):
    refresh_token: str
