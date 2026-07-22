"""
BreatheSafe — Health Profile Router
GET / POST / PUT the authenticated user's health profile.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.health_profile import HealthProfile
from app.models.user import User
from app.schemas.profile import HealthProfileCreate, HealthProfileOut, HealthProfileUpdate

router = APIRouter()


# ── Get my profile ────────────────────────────────────────────────────────────
@router.get("/", response_model=HealthProfileOut)
def get_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the health profile for the authenticated user."""
    profile = db.query(HealthProfile).filter(
        HealthProfile.user_id == current_user.id
    ).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Health profile not found. Use POST /profile/ to create one.",
        )
    return profile


# ── Create profile ────────────────────────────────────────────────────────────
@router.post("/", response_model=HealthProfileOut, status_code=status.HTTP_201_CREATED)
def create_profile(
    payload: HealthProfileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a health profile for the authenticated user (one profile per user)."""
    existing = db.query(HealthProfile).filter(
        HealthProfile.user_id == current_user.id
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Health profile already exists. Use PUT /profile/ to update.",
        )

    profile = HealthProfile(user_id=current_user.id, **payload.model_dump())
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


# ── Update profile ────────────────────────────────────────────────────────────
@router.put("/", response_model=HealthProfileOut)
def update_profile(
    payload: HealthProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the health profile for the authenticated user."""
    profile = db.query(HealthProfile).filter(
        HealthProfile.user_id == current_user.id
    ).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Health profile not found. Use POST /profile/ to create one.",
        )

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return profile
