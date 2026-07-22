"""
BreatheSafe — Auth Router
Endpoints: register, login, refresh, /me, /debug-email
"""

import logging
import threading

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.auth import RefreshRequest, Token, UserLogin, UserOut, UserRegister

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Register ──────────────────────────────────────────────────────────────────
@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    """Create a new user account and return access + refresh tokens."""
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )

    user = User(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # ── Send welcome email in a background thread ─────────────────────────────
    # Non-blocking: registration succeeds even if email fails.
    # Errors are logged — check Render logs if emails aren't arriving.
    _user_name  = user.name
    _user_email = user.email

    def _send_welcome():
        try:
            from app.services.notifier import send_welcome_email
            ok = send_welcome_email(to_email=_user_email, user_name=_user_name)
            if ok:
                logger.info("Welcome email sent to %s", _user_email)
            else:
                logger.warning("Welcome email failed (send_welcome_email returned False) for %s", _user_email)
        except Exception as exc:
            logger.error("Welcome email exception for %s: %s", _user_email, exc, exc_info=True)

    threading.Thread(target=_send_welcome, daemon=True).start()

    return Token(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user=UserOut.model_validate(user),
    )


# ── Login ─────────────────────────────────────────────────────────────────────
@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    """Authenticate with email + password and return tokens."""
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive.",
        )

    return Token(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user=UserOut.model_validate(user),
    )


# ── Refresh ───────────────────────────────────────────────────────────────────
@router.post("/refresh", response_model=Token)
def refresh_token(payload: RefreshRequest, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for a new access + refresh token pair."""
    token_data = decode_token(payload.refresh_token)
    if not token_data or token_data.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )

    user_id = int(token_data["sub"])
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive.",
        )

    return Token(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user=UserOut.model_validate(user),
    )


# ── Me ────────────────────────────────────────────────────────────────────────
@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    """Return the profile of the currently authenticated user."""
    return current_user


# ── Debug Email ───────────────────────────────────────────────────────────────
@router.get("/debug-email")
def debug_email(current_user: User = Depends(get_current_user)):
    """
    Diagnostic endpoint — tests SMTP end-to-end and returns the full result.

    Requires authentication and always sends to the *caller's own* registered
    address. It previously accepted an arbitrary `?to=` address with no auth,
    which let anyone use the configured Gmail account to mail strangers and
    exposed the sending address to unauthenticated callers.

    Returns:
      - credential_status: what SMTP creds were resolved (no password value)
      - smtp_test: whether the actual SMTP connection and send succeeded
      - error: exact error message if it failed (SMTPAuthenticationError, etc.)
    """
    from app.services.notifier import _send_email_sync, get_email_debug_info

    to        = current_user.email
    cred_info = get_email_debug_info()

    if not cred_info["credentials_ok"]:
        return {
            "credential_status": cred_info,
            "smtp_test":         "skipped — credentials missing",
            "success":           False,
            "error":             "SMTP_USER or SMTP_PASSWORD not loaded. Check Render env vars.",
        }

    # Send an actual test email
    html_body = f"""<!DOCTYPE html>
<html><body style="background:#030712;color:#e2e8f0;
  font-family:sans-serif;padding:32px;">
  <h2 style="color:#38bdf8;">🍃 BreatheSafe — SMTP Test</h2>
  <p>This is a test email sent from <strong>/auth/debug-email</strong>.</p>
  <p>If you received this, Gmail SMTP is working correctly.</p>
  <p style="color:#64748b;font-size:12px;">Sent to: {to}</p>
</body></html>"""
    plain_body = (
        "BreatheSafe SMTP Test\n\n"
        "This is a test email sent from /auth/debug-email.\n"
        "If you received this, Gmail SMTP is working correctly.\n"
    )

    ok, error_detail = _send_email_sync(
        to_email   = to,
        subject    = "BreatheSafe — SMTP Test Email",
        html_body  = html_body,
        plain_body = plain_body,
    )

    return {
        "credential_status": cred_info,
        "smtp_test":         "passed" if ok else "failed",
        "success":           ok,
        "error":             error_detail if not ok else None,
        "sent_to":           to,
    }
