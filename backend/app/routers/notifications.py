"""
BreatheSafe — Notifications Router (Phase 8)

Endpoints:
  GET   /notifications/              — list user's notifications (unread first)
  GET   /notifications/unread-count  — count of unread notifications
  PATCH /notifications/{id}/read     — mark one notification as read
  PATCH /notifications/read-all      — mark all notifications as read
  DELETE /notifications/{id}         — delete a notification
  POST  /notifications/test          — create a test notification (dev/demo)
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.city import City
from app.models.notification import Notification, NotificationTypeEnum
from app.models.user import User
from app.services.notifier import create_notification

router = APIRouter()


# ── 1. List notifications ─────────────────────────────────────────────────────
@router.get("/", response_model=dict)
def list_notifications(
    unread_only: bool = Query(False),
    limit:       int  = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the user's notifications, most recent first (unread first if unread_only=False)."""
    q = db.query(Notification).filter(Notification.user_id == current_user.id)
    if unread_only:
        q = q.filter(Notification.is_read == False)

    notifications = q.order_by(Notification.is_read, desc(Notification.sent_at)).limit(limit).all()

    return {
        "user":  current_user.name,
        "total": len(notifications),
        "notifications": [_format(n, db) for n in notifications],
    }


# ── 2. Unread count ────────────────────────────────────────────────────────────
@router.get("/unread-count", response_model=dict)
def unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    count = (
        db.query(Notification)
        .filter(
            Notification.user_id == current_user.id,
            Notification.is_read == False,
        )
        .count()
    )
    return {"unread": count}


# ── 3. Mark one as read ────────────────────────────────────────────────────────
@router.patch("/{notification_id}/read", response_model=dict)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    n = db.query(Notification).filter(
        Notification.id      == notification_id,
        Notification.user_id == current_user.id,
    ).first()
    if not n:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Notification not found.")
    if not n.is_read:
        n.is_read = True
        n.read_at = datetime.utcnow()
        db.commit()
    return {"id": n.id, "is_read": True}


# ── 4. Mark all as read ───────────────────────────────────────────────────────
@router.patch("/read-all", response_model=dict)
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    updated = (
        db.query(Notification)
        .filter(
            Notification.user_id == current_user.id,
            Notification.is_read == False,
        )
        .all()
    )
    now = datetime.utcnow()
    for n in updated:
        n.is_read = True
        n.read_at = now
    db.commit()
    return {"marked_read": len(updated)}


# ── 5. Delete a notification ──────────────────────────────────────────────────
@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    n = db.query(Notification).filter(
        Notification.id      == notification_id,
        Notification.user_id == current_user.id,
    ).first()
    if not n:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Notification not found.")
    db.delete(n)
    db.commit()


# ── 6. Test notification + email ─────────────────────────────────────────────
@router.post("/test", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_test_notification(
    city: Optional[str] = Query(None, description="City name for the test alert"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a test AQI threshold notification AND send a test email to the user.
    Returns the notification plus email_sent flag so the frontend can show feedback.
    """
    from sqlalchemy import func

    from app.services.notifier import _send_email

    city_obj = None
    if city:
        city_obj = db.query(City).filter(func.lower(City.name) == city.lower()).first()

    city_label = (city_obj.name if city_obj else None) or city or "Delhi"

    # ── Create in-app notification ────────────────────────────────────────────
    n = create_notification(
        db                = db,
        user_id           = current_user.id,
        city_id           = city_obj.id if city_obj else None,
        notification_type = NotificationTypeEnum.aqi_threshold,
        message           = (
            f"Test Alert: AQI in {city_label} has reached 215 (Moderately Polluted), "
            "exceeding your threshold. This is a test notification from BreatheSafe."
        ),
        aqi_value         = 215.0,
    )

    # ── Send test email ───────────────────────────────────────────────────────
    html_body = _build_test_email_html(current_user.name, city_label)
    plain_body = (
        f"BreatheSafe — Test Alert\n\n"
        f"Hi {current_user.name},\n\n"
        f"This is a test email from BreatheSafe.\n\n"
        f"If you received this, your email notifications are working correctly.\n\n"
        f"AQI in {city_label} is currently 215 (Moderately Polluted).\n\n"
        f"© 2026 BreatheSafe"
    )
    email_sent, email_error = await _send_email(
        to_email   = current_user.email,
        subject    = "✅ BreatheSafe — Test Alert (Email Working)",
        html_body  = html_body,
        plain_body = plain_body,
    )

    # Mark sent_via_email on the notification if email succeeded
    if email_sent:
        n.sent_via_email = True
        db.commit()
        db.refresh(n)

    result = _format(n, db)
    result["email_sent"]    = email_sent
    result["email_address"] = current_user.email
    result["email_error"]   = email_error   # populated when email_sent=False
    return result


def _build_test_email_html(user_name: str, city: str) -> str:
    """HTML body for the test email."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>BreatheSafe Test Alert</title>
</head>
<body style="margin:0;padding:0;background:#030712;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#030712;padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

        <!-- Header -->
        <tr>
          <td style="background:#0f172a;border:1px solid #1e293b;border-radius:16px 16px 0 0;
                     padding:28px 32px;text-align:center;">
            <p style="margin:0;font-size:22px;font-weight:700;color:#38bdf8;letter-spacing:-0.5px;">
              🍃 BreatheSafe
            </p>
            <p style="margin:6px 0 0;font-size:13px;color:#64748b;">Personalised Air Quality Intelligence</p>
          </td>
        </tr>

        <!-- Green success banner -->
        <tr>
          <td style="background:#052e16;border-left:1px solid #166534;border-right:1px solid #166534;
                     padding:20px 32px;text-align:center;">
            <p style="margin:0;font-size:26px;font-weight:800;color:#4ade80;">
              ✅ Email Notifications Working
            </p>
            <p style="margin:8px 0 0;font-size:14px;color:#86efac;">
              Your test alert was delivered successfully
            </p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="background:#0f172a;border:1px solid #1e293b;border-radius:0 0 16px 16px;
                     padding:28px 32px;">
            <p style="margin:0 0 16px;font-size:15px;color:#e2e8f0;">
              Hi <strong style="color:#f8fafc;">{user_name}</strong>,
            </p>
            <p style="margin:0 0 24px;font-size:14px;color:#94a3b8;line-height:1.6;">
              This is a test notification from BreatheSafe. If you're reading this,
              your Gmail email alerts are set up and working correctly.
            </p>

            <!-- Sample alert card -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#1e293b;border-radius:12px;border:1px solid #334155;margin-bottom:24px;">
              <tr>
                <td style="padding:20px 24px;">
                  <p style="margin:0 0 6px;font-size:11px;font-weight:600;color:#64748b;
                             text-transform:uppercase;letter-spacing:1px;">Sample AQI Alert</p>
                  <p style="margin:0;font-size:14px;color:#d1d5db;line-height:1.6;">
                    AQI in <strong style="color:#f1f5f9;">{city}</strong> has reached
                    <strong style="color:#fbbf24;">215</strong>
                    <span style="color:#fbbf24;">(Moderately Polluted)</span>,
                    exceeding your notification threshold.
                  </p>
                  <p style="margin:12px 0 0;font-size:13px;color:#64748b;">
                    💡 Avoid prolonged outdoor activity and consider wearing a mask.
                  </p>
                </td>
              </tr>
            </table>

            <p style="margin:0 0 8px;font-size:13px;color:#64748b;text-align:center;">
              Real alerts are sent automatically when AQI crosses your threshold or
              when a saved route poses a health risk.
            </p>
            <p style="margin:24px 0 0;font-size:12px;color:#475569;text-align:center;
                      border-top:1px solid #1e293b;padding-top:20px;">
              © 2026 BreatheSafe · Protecting your every breath
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ── Formatter ─────────────────────────────────────────────────────────────────
_TITLES = {
    "aqi_threshold":  "AQI Threshold Alert",
    "forecast_alert": "Forecast Alert",
    "risk_alert":     "Health Risk Alert",
}

def _format(n: Notification, db: Session) -> dict:
    city_name = None
    if n.city_id:
        c = db.query(City).filter(City.id == n.city_id).first()
        city_name = c.name if c else None
    ntype = n.notification_type.value if hasattr(n.notification_type, "value") else str(n.notification_type)
    return {
        "id":                n.id,
        "notification_type": ntype,
        "title":             _TITLES.get(ntype, "Notification"),
        "message":           n.message,
        "aqi_value":         n.aqi_value,
        "city":              city_name,
        "is_read":           n.is_read,
        "sent_via_email":    n.sent_via_email,
        "created_at":        n.sent_at,   # alias sent_at → created_at for frontend
        "read_at":           n.read_at,
    }
