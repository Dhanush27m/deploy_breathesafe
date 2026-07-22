"""
BreatheSafe — Notifier Service

Responsibilities:
  1. In-app notification creation (create_notification, create_route_notification)
  2. Dedup helpers (already_notified_recently, route_notified_recently)
  3. Email dispatch:
       send_route_saved_email()   — always sent on route save (safe or unsafe)
       send_route_aqi_update_email() — sent by scheduler when AQI changes for saved route
       send_email_alert()         — generic plain-text alert
"""

import logging
import os
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.notification import Notification, NotificationTypeEnum

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════════
# In-app notification helpers
# ════════════════════════════════════════════════════════════════════════════════

def create_notification(
    db: Session,
    user_id: int,
    city_id: Optional[int],
    notification_type: NotificationTypeEnum,
    message: str,
    aqi_value: Optional[float] = None,
) -> Notification:
    """Create a standard in-app notification (no route association)."""
    n = Notification(
        user_id           = user_id,
        city_id           = city_id,
        notification_type = notification_type,
        message           = message,
        aqi_value         = aqi_value,
        sent_via_email    = False,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


def create_route_notification(
    db: Session,
    user_id: int,
    route_id: int,
    city_id: Optional[int],
    notification_type: NotificationTypeEnum,
    message: str,
    aqi_value: Optional[float] = None,
) -> Notification:
    """Create an in-app notification tied to a specific saved route."""
    n = Notification(
        user_id           = user_id,
        route_id          = route_id,
        city_id           = city_id,
        notification_type = notification_type,
        message           = message,
        aqi_value         = aqi_value,
        sent_via_email    = True,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


def already_notified_recently(
    db: Session,
    user_id: int,
    city_id: Optional[int],
    notification_type: NotificationTypeEnum,
    hours: int = 6,
) -> bool:
    """Return True if a notification of this type was sent to this user within `hours`."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = (
        db.query(Notification)
        .filter(
            Notification.user_id           == user_id,
            Notification.notification_type == notification_type,
            Notification.sent_at           >= cutoff,
        )
    )
    if city_id is not None:
        q = q.filter(Notification.city_id == city_id)
    return q.first() is not None


def route_notified_recently(
    db: Session,
    route_id: int,
    user_id: int,
    hours: float = 6,
) -> bool:
    """
    Return True if any route_saved or route_monitor notification was
    created for this route within the last `hours`.
    Used by the monitoring job to enforce cooldowns.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return (
        db.query(Notification)
        .filter(
            Notification.route_id == route_id,
            Notification.user_id  == user_id,
            Notification.notification_type.in_([
                NotificationTypeEnum.route_saved,
                NotificationTypeEnum.route_monitor,
            ]),
            Notification.sent_at >= cutoff,
        )
        .first()
    ) is not None


# ════════════════════════════════════════════════════════════════════════════════
# Generic email alert
# ════════════════════════════════════════════════════════════════════════════════

def send_email_alert(to_email: str, subject: str, body: str) -> bool:
    ok, _ = _send_email_sync(to_email, subject, html_body=body, plain_body=body)
    return ok


# ════════════════════════════════════════════════════════════════════════════════
# Alert message builders (used by check_alerts_job)
# ════════════════════════════════════════════════════════════════════════════════

def build_aqi_alert_message(city_name: str, aqi: float, threshold: int, category: str) -> str:
    return (
        f"AQI Alert: {city_name.title()} AQI is now {aqi:.0f} ({category}), "
        f"exceeding your threshold of {threshold}. Consider limiting outdoor activity."
    )


def build_forecast_alert_message(city_name: str, aqi: float, days: int, category: str) -> str:
    return (
        f"Forecast Alert: {city_name.title()} AQI is predicted to reach "
        f"{aqi:.0f} ({category}) in {days} day(s). Plan accordingly."
    )


def build_risk_alert_message(city_name: str, risk_score: float, category: str) -> str:
    return (
        f"Health Risk Alert: Your personal risk score for {city_name.title()} "
        f"is {risk_score:.0f}/100 ({category}). Take protective measures."
    )


# ════════════════════════════════════════════════════════════════════════════════
# Colour palette for risk levels
# ════════════════════════════════════════════════════════════════════════════════

_RISK_THEME = {
    None: {
        "accent":  "#38bdf8",   # sky blue — neutral
        "banner":  "#0f172a",
        "border":  "#1e293b",
        "label":   "Route Saved",
        "emoji":   "📍",
    },
    "Low": {
        "accent":  "#22c55e",   # green-500
        "banner":  "#052e16",
        "border":  "#166534",
        "label":   "Safe to Travel",
        "emoji":   "✅",
    },
    "Moderate": {
        "accent":  "#eab308",   # yellow-500
        "banner":  "#422006",
        "border":  "#a16207",
        "label":   "Use Caution",
        "emoji":   "⚠️",
    },
    "High": {
        "accent":  "#f97316",   # orange-500
        "banner":  "#431407",
        "border":  "#c2410c",
        "label":   "Health Warning",
        "emoji":   "⚠️",
    },
    "Severe": {
        "accent":  "#ef4444",   # red-500
        "banner":  "#450a0a",
        "border":  "#b91c1c",
        "label":   "Severe Health Risk",
        "emoji":   "🚨",
    },
}


def _theme(risk_category: Optional[str]) -> dict:
    return _RISK_THEME.get(risk_category, _RISK_THEME[None])


# ════════════════════════════════════════════════════════════════════════════════
# Welcome Email — sent once on account creation
# ════════════════════════════════════════════════════════════════════════════════

def _build_welcome_html(user_name: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Welcome to BreatheSafe</title>
</head>
<body style="margin:0;padding:0;background:#030712;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#030712;padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;">

        <!-- Header -->
        <tr>
          <td style="background:#0f172a;border:1px solid #1e293b;
                     border-radius:16px 16px 0 0;padding:28px 32px;text-align:center;">
            <p style="margin:0;font-size:28px;font-weight:700;
                       color:#38bdf8;letter-spacing:-0.5px;">
              🍃 BreatheSafe
            </p>
            <p style="margin:6px 0 0;font-size:13px;color:#64748b;">
              Personalised Air Quality Intelligence
            </p>
          </td>
        </tr>

        <!-- Banner -->
        <tr>
          <td style="background:#052e16;border-left:1px solid #166534;
                     border-right:1px solid #166534;
                     padding:24px 32px;text-align:center;">
            <p style="margin:0;font-size:24px;font-weight:800;color:#22c55e;">
              ✅ Welcome to BreatheSafe!
            </p>
            <p style="margin:8px 0 0;font-size:14px;color:#d1d5db;">
              Your account is ready. Start breathing smarter.
            </p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="background:#0f172a;border:1px solid #1e293b;
                     border-radius:0 0 16px 16px;padding:28px 32px;">

            <p style="margin:0 0 16px;font-size:15px;color:#e2e8f0;">
              Hi <strong style="color:#f8fafc;">{user_name}</strong>,
            </p>
            <p style="margin:0 0 24px;font-size:14px;color:#94a3b8;line-height:1.7;">
              Welcome to <strong style="color:#38bdf8;">BreatheSafe</strong> —
              India's personalised air quality platform. Here's what you can do:
            </p>

            <!-- Features grid -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#1e293b;border-radius:12px;
                          border:1px solid #334155;margin-bottom:24px;">
              <tr>
                <td style="padding:20px 24px;">
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td style="padding:8px 0;font-size:14px;color:#e2e8f0;">
                        🌡️ &nbsp;<strong>Live AQI</strong>
                        <span style="color:#94a3b8;"> — Monitor 29 cities in real time</span>
                      </td>
                    </tr>
                    <tr>
                      <td style="padding:8px 0;font-size:14px;color:#e2e8f0;">
                        🔮 &nbsp;<strong>7-Day Forecast</strong>
                        <span style="color:#94a3b8;"> — XGBoost + Prophet ensemble predictions</span>
                      </td>
                    </tr>
                    <tr>
                      <td style="padding:8px 0;font-size:14px;color:#e2e8f0;">
                        🫁 &nbsp;<strong>Personal Risk Score</strong>
                        <span style="color:#94a3b8;"> — Set your health profile for a custom PAERI score</span>
                      </td>
                    </tr>
                    <tr>
                      <td style="padding:8px 0;font-size:14px;color:#e2e8f0;">
                        🗺️ &nbsp;<strong>Clean Routes</strong>
                        <span style="color:#94a3b8;"> — Find lowest-pollution paths for your journeys</span>
                      </td>
                    </tr>
                    <tr>
                      <td style="padding:8px 0;font-size:14px;color:#e2e8f0;">
                        🔔 &nbsp;<strong>Email Alerts</strong>
                        <span style="color:#94a3b8;"> — Get notified when your route AQI changes</span>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>

            <!-- CTA -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="margin-bottom:28px;">
              <tr>
                <td align="center" style="padding:8px 0;">
                  <p style="margin:0;font-size:13px;color:#64748b;">
                    💡 <strong style="color:#38bdf8;">Tip:</strong> Complete your
                    Health Profile to unlock personalised risk scoring on every route.
                  </p>
                </td>
              </tr>
            </table>

            <!-- Footer -->
            <p style="margin:24px 0 0;font-size:12px;color:#475569;text-align:center;
                       border-top:1px solid #1e293b;padding-top:20px;">
              You received this because you created a BreatheSafe account.<br/>
              © 2026 BreatheSafe · Protecting your every breath
            </p>

          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_welcome_email(to_email: str, user_name: str) -> bool:
    """
    Send a welcome email immediately after account creation.
    Non-blocking from the caller's perspective — always wrapped in try/except by auth.py.
    Returns True if sent successfully, False otherwise.
    """
    subject   = "Welcome to BreatheSafe — Your account is ready 🍃"
    html_body = _build_welcome_html(user_name)
    plain_body = (
        f"Welcome to BreatheSafe, {user_name}!\n\n"
        "Your account is ready. Here's what you can do:\n\n"
        "🌡️  Live AQI — Monitor 29 cities in real time\n"
        "🔮  7-Day Forecast — XGBoost + Prophet ensemble predictions\n"
        "🫁  Personal Risk Score — PAERI score based on your health profile\n"
        "🗺️  Clean Routes — Find lowest-pollution paths for your journeys\n"
        "🔔  Email Alerts — Get notified when your route AQI changes\n\n"
        "Tip: Complete your Health Profile to unlock personalised risk scoring.\n\n"
        "© 2026 BreatheSafe · Protecting your every breath"
    )
    ok, _ = _send_email_sync(to_email, subject, html_body, plain_body)
    return ok


# ════════════════════════════════════════════════════════════════════════════════
# Route Save Confirmation Email
# (sent every time a route is saved, regardless of risk level)
# ════════════════════════════════════════════════════════════════════════════════

def build_route_save_email_html(
    user_name:      str,
    source:         str,
    destination:    str,
    route_type:     str,
    travel_mode:    str,
    distance_km:    float,
    time_min:       float,
    avg_aqi:        float,
    planned_start:  datetime,
    planned_end:    datetime,
    risk_score:     Optional[float],
    risk_category:  Optional[str],
    recommendations: List[str],
) -> str:
    """
    Unified HTML email for route save confirmation.
    Adapts colour scheme and messaging based on risk level (or None if no health profile).
    """
    t = _theme(risk_category)
    start_str = planned_start.strftime("%d %b %Y, %I:%M %p")
    end_str   = planned_end.strftime("%I:%M %p")
    mode_icon = {"driving": "🚗", "walking": "🚶", "cycling": "🚴"}.get(travel_mode, "🗺")

    # Risk score section — shown only if profile exists
    if risk_score is not None and risk_category is not None:
        aqi_cat_text = {
            "Low":      "Air quality is acceptable.",
            "Moderate": "Moderate pollution — sensitive individuals should take care.",
            "High":     "Unhealthy conditions — precautions recommended.",
            "Severe":   "Hazardous conditions — avoid prolonged outdoor exposure.",
        }.get(risk_category, "")

        risk_section = f"""
            <!-- Risk score card -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:{t['banner']};border-radius:12px;
                          border:1px solid {t['border']};margin-bottom:24px;">
              <tr>
                <td style="padding:20px 24px;text-align:center;">
                  <p style="margin:0 0 4px;font-size:11px;font-weight:600;color:#94a3b8;
                             text-transform:uppercase;letter-spacing:1px;">
                    Your Personal Risk Score
                  </p>
                  <p style="margin:0;font-size:48px;font-weight:800;
                             color:{t['accent']};line-height:1.1;">
                    {risk_score:.0f}<span style="font-size:20px;color:#94a3b8;
                    font-weight:400;">/100</span>
                  </p>
                  <p style="margin:8px 0 0;font-size:13px;color:{t['accent']};
                             font-weight:600;">
                    {risk_category} Risk &nbsp;·&nbsp; Route AQI: {avg_aqi:.0f}
                  </p>
                  <p style="margin:6px 0 0;font-size:12px;color:#94a3b8;">
                    {aqi_cat_text}
                  </p>
                </td>
              </tr>
            </table>"""
    else:
        # No health profile — show basic AQI chip
        risk_section = f"""
            <!-- Basic AQI card (no profile) -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#1e293b;border-radius:12px;
                          border:1px solid #334155;margin-bottom:24px;">
              <tr>
                <td style="padding:16px 24px;text-align:center;">
                  <p style="margin:0;font-size:13px;color:#94a3b8;">
                    Route avg AQI: <strong style="color:{t['accent']};
                    font-size:18px;">{avg_aqi:.0f}</strong>
                  </p>
                  <p style="margin:8px 0 0;font-size:12px;color:#64748b;">
                    💡 Complete your
                    <span style="color:{t['accent']};">Health Profile</span>
                    in the app for a personalised risk score on every journey.
                  </p>
                </td>
              </tr>
            </table>"""

    # Recommendations section
    if recommendations:
        rec_items = "".join(
            f'<li style="margin:6px 0;color:#d1d5db;">{r}</li>'
            for r in recommendations[:5]
        )
        recs_section = f"""
            <!-- Recommendations -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#1e293b;border-radius:12px;
                          border:1px solid #334155;margin-bottom:28px;">
              <tr>
                <td style="padding:20px 24px;">
                  <p style="margin:0 0 12px;font-size:11px;font-weight:600;color:#64748b;
                             text-transform:uppercase;letter-spacing:1px;">
                    Recommendations
                  </p>
                  <ul style="margin:0;padding-left:18px;">{rec_items}</ul>
                </td>
              </tr>
            </table>"""
    else:
        recs_section = ""

    banner_subtitle = {
        None:       "Your route has been saved to BreatheSafe.",
        "Low":      "Great news — air quality looks fine for your journey.",
        "Moderate": "Conditions are manageable — a few precautions help.",
        "High":     "Your journey has elevated health risk — please review recommendations.",
        "Severe":   "Hazardous air quality detected on your route — take precautions.",
    }.get(risk_category, "Your route has been saved.")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>BreatheSafe — Route Saved</title>
</head>
<body style="margin:0;padding:0;background:#030712;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#030712;padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;">

        <!-- ── Header ──────────────────────────────────────────── -->
        <tr>
          <td style="background:#0f172a;border:1px solid #1e293b;
                     border-radius:16px 16px 0 0;padding:28px 32px;text-align:center;">
            <p style="margin:0;font-size:22px;font-weight:700;
                       color:#38bdf8;letter-spacing:-0.5px;">
              🍃 BreatheSafe
            </p>
            <p style="margin:6px 0 0;font-size:13px;color:#64748b;">
              Personalised Air Quality Intelligence
            </p>
          </td>
        </tr>

        <!-- ── Status banner ────────────────────────────────────── -->
        <tr>
          <td style="background:{t['banner']};border-left:1px solid {t['border']};
                     border-right:1px solid {t['border']};
                     padding:20px 32px;text-align:center;">
            <p style="margin:0;font-size:26px;font-weight:800;color:{t['accent']};">
              {t['emoji']} {t['label']}
            </p>
            <p style="margin:8px 0 0;font-size:14px;color:#d1d5db;">
              {banner_subtitle}
            </p>
          </td>
        </tr>

        <!-- ── Body ─────────────────────────────────────────────── -->
        <tr>
          <td style="background:#0f172a;border:1px solid #1e293b;
                     border-radius:0 0 16px 16px;padding:28px 32px;">

            <p style="margin:0 0 20px;font-size:15px;color:#e2e8f0;">
              Hi <strong style="color:#f8fafc;">{user_name}</strong>,
            </p>
            <p style="margin:0 0 24px;font-size:14px;color:#94a3b8;line-height:1.6;">
              Here's a summary of your saved journey:
            </p>

            <!-- Journey details card -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#1e293b;border-radius:12px;
                          border:1px solid #334155;margin-bottom:24px;">
              <tr>
                <td style="padding:20px 24px;">
                  <p style="margin:0 0 14px;font-size:11px;font-weight:600;
                             color:#64748b;text-transform:uppercase;letter-spacing:1px;">
                    Journey Details {mode_icon}
                  </p>
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td style="padding:5px 0;color:#64748b;font-size:13px;">From</td>
                      <td style="padding:5px 0;text-align:right;
                                 color:#f1f5f9;font-size:13px;font-weight:600;
                                 text-transform:capitalize;">{source}</td>
                    </tr>
                    <tr>
                      <td style="padding:5px 0;color:#64748b;font-size:13px;">To</td>
                      <td style="padding:5px 0;text-align:right;
                                 color:#f1f5f9;font-size:13px;font-weight:600;
                                 text-transform:capitalize;">{destination}</td>
                    </tr>
                    <tr>
                      <td style="padding:5px 0;color:#64748b;font-size:13px;">
                        Departure
                      </td>
                      <td style="padding:5px 0;text-align:right;
                                 color:#f1f5f9;font-size:13px;">
                        {start_str} → {end_str}
                      </td>
                    </tr>
                    <tr>
                      <td style="padding:5px 0;color:#64748b;font-size:13px;">Route</td>
                      <td style="padding:5px 0;text-align:right;
                                 color:#f1f5f9;font-size:13px;text-transform:capitalize;">
                        {route_type} &nbsp;·&nbsp; {travel_mode}
                        &nbsp;·&nbsp; {distance_km:.1f} km
                        &nbsp;·&nbsp; {time_min:.0f} min
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>

            {risk_section}
            {recs_section}

            <!-- Footer note -->
            <p style="margin:0 0 8px;font-size:13px;color:#64748b;text-align:center;">
              Open the app to view or cancel this journey.
            </p>
            <p style="margin:24px 0 0;font-size:12px;color:#475569;text-align:center;
                       border-top:1px solid #1e293b;padding-top:20px;">
              You received this because you saved a route on BreatheSafe.<br/>
              We'll alert you if air quality changes significantly before your journey.
              <br/><br/>
              © 2026 BreatheSafe · Protecting your every breath
            </p>

          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_route_saved_email(
    to_email:       str,
    user_name:      str,
    source:         str,
    destination:    str,
    route_type:     str,
    travel_mode:    str,
    distance_km:    float,
    time_min:       float,
    avg_aqi:        float,
    planned_start:  datetime,
    planned_end:    datetime,
    risk_score:     Optional[float] = None,
    risk_category:  Optional[str]   = None,
    recommendations: Optional[List[str]] = None,
) -> bool:
    """
    Send a route save confirmation email (synchronous — safe for BackgroundTasks).
    Always sent — colour/tone adapts based on risk_category:
      None         → neutral blue (no health profile)
      Low/Moderate → green/yellow confirmation
      High/Severe  → orange/red health warning
    """
    if recommendations is None:
        recommendations = []

    if risk_category in ("High", "Severe"):
        subject = (
            f"BreatheSafe: {risk_category} Health Risk — "
            f"{source} → {destination} journey saved"
        )
    elif risk_category in ("Low", "Moderate"):
        subject = f"Route Saved — {source} to {destination} (Safe to Travel)"
    else:
        subject = f"Route Saved — {source} to {destination}"

    html_body = build_route_save_email_html(
        user_name=user_name, source=source, destination=destination,
        route_type=route_type, travel_mode=travel_mode,
        distance_km=distance_km, time_min=time_min, avg_aqi=avg_aqi,
        planned_start=planned_start, planned_end=planned_end,
        risk_score=risk_score, risk_category=risk_category,
        recommendations=recommendations,
    )

    plain_body = (
        f"BreatheSafe — Route Saved\n\n"
        f"Hi {user_name},\n\n"
        f"Your journey from {source} to {destination} has been saved.\n"
        f"Departure: {planned_start.strftime('%d %b %Y, %I:%M %p')} → "
        f"{planned_end.strftime('%I:%M %p')}\n"
        f"Route: {route_type} | {travel_mode} | {distance_km:.1f} km | {time_min:.0f} min\n"
        f"Avg Route AQI: {avg_aqi:.0f}\n"
    )
    if risk_score is not None:
        plain_body += f"Risk Score: {risk_score:.0f}/100 ({risk_category})\n"
        if risk_category in ("High", "Severe"):
            plain_body += (
                f"\nHEALTH WARNING: This route poses a {risk_category.lower()} health risk "
                f"based on your health profile. Consider taking precautions or choosing "
                f"a cleaner route.\n"
            )
    if recommendations:
        plain_body += "\nRecommendations:\n" + "\n".join(f"- {r}" for r in recommendations)
    plain_body += "\n\nOpen BreatheSafe to view or cancel this journey.\n\n© 2026 BreatheSafe"

    ok, _ = _send_email_sync(to_email, subject, html_body, plain_body)
    return ok


# ════════════════════════════════════════════════════════════════════════════════
# Route AQI Update / Monitoring Email
# (sent by scheduler when AQI changes significantly for a saved route)
# ════════════════════════════════════════════════════════════════════════════════

def build_route_aqi_update_email_html(
    user_name:        str,
    source:           str,
    destination:      str,
    planned_start:    datetime,
    planned_end:      datetime,
    current_aqi:      float,
    previous_aqi:     float,
    current_cat:      str,
    risk_score:       Optional[float],
    risk_category:    Optional[str],
    recommendations:  List[str],
    hours_until:      float,
) -> str:
    """
    HTML email for a scheduled AQI update on a saved route.
    Shows before→after AQI comparison and updated risk assessment.
    """
    t = _theme(risk_category)
    start_str = planned_start.strftime("%d %b %Y, %I:%M %p")

    # Human-readable countdown
    if hours_until < 1:
        countdown = f"{int(hours_until * 60)} minutes"
    elif hours_until < 24:
        h = int(hours_until)
        countdown = f"{h} hour{'s' if h != 1 else ''}"
    else:
        d = int(hours_until / 24)
        countdown = f"{d} day{'s' if d != 1 else ''}"

    # AQI change direction
    change = current_aqi - previous_aqi
    if change > 10:
        change_str  = f"▲ {change:+.0f}"
        change_col  = "#ef4444"
        change_note = "conditions have worsened"
    elif change < -10:
        change_str  = f"▼ {change:.0f}"
        change_col  = "#22c55e"
        change_note = "conditions have improved"
    else:
        change_str  = f"≈ {change:+.0f}"
        change_col  = "#94a3b8"
        change_note = "conditions are similar"

    # Risk score card
    if risk_score is not None and risk_category:
        risk_block = f"""
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="background:{t['banner']};border-radius:12px;
                        border:1px solid {t['border']};margin-bottom:24px;">
            <tr>
              <td style="padding:20px 24px;text-align:center;">
                <p style="margin:0 0 4px;font-size:11px;font-weight:600;
                           color:#94a3b8;text-transform:uppercase;letter-spacing:1px;">
                  Your Updated Risk Score
                </p>
                <p style="margin:0;font-size:44px;font-weight:800;
                           color:{t['accent']};line-height:1.1;">
                  {risk_score:.0f}<span style="font-size:18px;color:#94a3b8;
                  font-weight:400;">/100</span>
                </p>
                <p style="margin:6px 0 0;font-size:13px;
                           color:{t['accent']};font-weight:600;">
                  {risk_category} Risk &nbsp;·&nbsp; Current AQI: {current_aqi:.0f} ({current_cat})
                </p>
              </td>
            </tr>
          </table>"""
    else:
        risk_block = ""

    # Recommendations
    if recommendations:
        rec_items = "".join(
            f'<li style="margin:6px 0;color:#d1d5db;">{r}</li>'
            for r in recommendations[:5]
        )
        recs_block = f"""
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="background:#1e293b;border-radius:12px;
                        border:1px solid #334155;margin-bottom:28px;">
            <tr>
              <td style="padding:20px 24px;">
                <p style="margin:0 0 12px;font-size:11px;font-weight:600;color:#64748b;
                           text-transform:uppercase;letter-spacing:1px;">
                  Updated Recommendations
                </p>
                <ul style="margin:0;padding-left:18px;">{rec_items}</ul>
              </td>
            </tr>
          </table>"""
    else:
        recs_block = ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>BreatheSafe — AQI Update for Your Journey</title>
</head>
<body style="margin:0;padding:0;background:#030712;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#030712;padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;">

        <!-- ── Header ──────────────────────────────────────────── -->
        <tr>
          <td style="background:#0f172a;border:1px solid #1e293b;
                     border-radius:16px 16px 0 0;padding:28px 32px;text-align:center;">
            <p style="margin:0;font-size:22px;font-weight:700;
                       color:#38bdf8;letter-spacing:-0.5px;">
              🍃 BreatheSafe
            </p>
            <p style="margin:6px 0 0;font-size:13px;color:#64748b;">
              Personalised Air Quality Intelligence
            </p>
          </td>
        </tr>

        <!-- ── Alert banner ─────────────────────────────────────── -->
        <tr>
          <td style="background:{t['banner']};border-left:1px solid {t['border']};
                     border-right:1px solid {t['border']};
                     padding:20px 32px;text-align:center;">
            <p style="margin:0;font-size:24px;font-weight:800;color:{t['accent']};">
              ⚡ AQI Update for Your Journey
            </p>
            <p style="margin:8px 0 0;font-size:14px;color:#d1d5db;">
              Air quality {change_note} on your route
            </p>
          </td>
        </tr>

        <!-- ── Body ─────────────────────────────────────────────── -->
        <tr>
          <td style="background:#0f172a;border:1px solid #1e293b;
                     border-radius:0 0 16px 16px;padding:28px 32px;">

            <p style="margin:0 0 20px;font-size:15px;color:#e2e8f0;">
              Hi <strong style="color:#f8fafc;">{user_name}</strong>,
            </p>

            <!-- Countdown card -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#1e293b;border-radius:12px;
                          border:1px solid {t['border']};margin-bottom:24px;">
              <tr>
                <td style="padding:18px 24px;text-align:center;">
                  <p style="margin:0;font-size:13px;color:#94a3b8;">
                    Your journey departs in
                  </p>
                  <p style="margin:6px 0;font-size:28px;font-weight:800;
                             color:{t['accent']};">
                    {countdown}
                  </p>
                  <p style="margin:0;font-size:13px;color:#64748b;">
                    <span style="text-transform:capitalize;">{source}</span>
                    &nbsp;→&nbsp;
                    <span style="text-transform:capitalize;">{destination}</span>
                    &nbsp;·&nbsp; {start_str}
                  </p>
                </td>
              </tr>
            </table>

            <!-- Before → After AQI comparison -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#1e293b;border-radius:12px;
                          border:1px solid #334155;margin-bottom:24px;">
              <tr>
                <td style="padding:20px 24px;">
                  <p style="margin:0 0 16px;font-size:11px;font-weight:600;color:#64748b;
                             text-transform:uppercase;letter-spacing:1px;">
                    AQI Along Your Route
                  </p>
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td style="text-align:center;width:40%;">
                        <p style="margin:0;font-size:11px;color:#64748b;">
                          When Saved
                        </p>
                        <p style="margin:4px 0 0;font-size:32px;font-weight:800;
                                   color:#94a3b8;">
                          {previous_aqi:.0f}
                        </p>
                      </td>
                      <td style="text-align:center;width:20%;">
                        <p style="margin:0;font-size:22px;font-weight:800;
                                   color:{change_col};">
                          {change_str}
                        </p>
                      </td>
                      <td style="text-align:center;width:40%;">
                        <p style="margin:0;font-size:11px;color:#64748b;">
                          Right Now
                        </p>
                        <p style="margin:4px 0 0;font-size:32px;font-weight:800;
                                   color:{t['accent']};">
                          {current_aqi:.0f}
                        </p>
                        <p style="margin:2px 0 0;font-size:11px;
                                   color:{t['accent']};">{current_cat}</p>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>

            {risk_block}
            {recs_block}

            <p style="margin:0 0 8px;font-size:13px;color:#64748b;text-align:center;">
              Open the app to review or cancel your saved route.
            </p>
            <p style="margin:24px 0 0;font-size:12px;color:#475569;text-align:center;
                       border-top:1px solid #1e293b;padding-top:20px;">
              You're receiving this because air quality has changed on your saved route.
              <br/>We'll continue monitoring until your journey begins.
              <br/><br/>
              © 2026 BreatheSafe · Protecting your every breath
            </p>

          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_route_aqi_update_email(
    to_email:        str,
    user_name:       str,
    source:          str,
    destination:     str,
    planned_start:   datetime,
    planned_end:     datetime,
    current_aqi:     float,
    previous_aqi:    float,
    current_cat:     str,
    risk_score:      Optional[float],
    risk_category:   Optional[str],
    recommendations: List[str],
    hours_until:     float,
) -> bool:
    """Dispatch a route AQI monitoring update email (synchronous — safe for scheduler threads)."""
    if hours_until <= 6:
        urgency_prefix = "URGENT - "
    elif hours_until <= 24:
        urgency_prefix = "AQI Alert - "
    else:
        urgency_prefix = "AQI Update - "

    subject = (
        f"{urgency_prefix}BreatheSafe: {source} to {destination} "
        f"— AQI now {current_aqi:.0f} ({current_cat})"
    )

    html_body = build_route_aqi_update_email_html(
        user_name=user_name, source=source, destination=destination,
        planned_start=planned_start, planned_end=planned_end,
        current_aqi=current_aqi, previous_aqi=previous_aqi,
        current_cat=current_cat, risk_score=risk_score,
        risk_category=risk_category, recommendations=recommendations,
        hours_until=hours_until,
    )

    plain_body = (
        f"BreatheSafe — AQI Update for Your Journey\n\n"
        f"Hi {user_name},\n\n"
        f"Air quality has changed on your {source} to {destination} route.\n"
        f"Previous AQI: {previous_aqi:.0f} | Current AQI: {current_aqi:.0f} ({current_cat})\n"
        f"Departure: {planned_start.strftime('%d %b %Y, %I:%M %p')}\n"
    )
    if risk_score is not None:
        plain_body += f"Updated Risk Score: {risk_score:.0f}/100 ({risk_category})\n"
        if risk_category in ("High", "Severe"):
            plain_body += (
                f"\nWARNING: Current AQI poses a {risk_category.lower()} health risk "
                f"based on your health profile. Take precautions before travel.\n"
            )
    if recommendations:
        plain_body += "\nRecommendations:\n" + "\n".join(f"- {r}" for r in recommendations[:5])
    plain_body += "\n\nOpen BreatheSafe to manage your journey.\n\n© 2026 BreatheSafe"

    ok, _ = _send_email_sync(to_email, subject, html_body, plain_body)
    return ok


# ════════════════════════════════════════════════════════════════════════════════
# Legacy: Route risk email (kept for backward compat — send_route_saved_email
# is now the preferred entry point)
# ════════════════════════════════════════════════════════════════════════════════

def build_route_risk_email_html(
    user_name:     str,
    source:        str,
    destination:   str,
    route_type:    str,
    travel_mode:   str,
    distance_km:   float,
    time_min:      float,
    avg_aqi:       float,
    risk_score:    float,
    risk_category: str,
    planned_start: datetime,
    planned_end:   datetime,
    recommendations: List[str],
) -> str:
    """Legacy wrapper — delegates to the unified builder."""
    return build_route_save_email_html(
        user_name=user_name, source=source, destination=destination,
        route_type=route_type, travel_mode=travel_mode,
        distance_km=distance_km, time_min=time_min, avg_aqi=avg_aqi,
        planned_start=planned_start, planned_end=planned_end,
        risk_score=risk_score, risk_category=risk_category,
        recommendations=recommendations,
    )


def send_route_risk_email(
    to_email:      str,
    user_name:     str,
    source:        str,
    destination:   str,
    route_type:    str,
    travel_mode:   str,
    distance_km:   float,
    time_min:      float,
    avg_aqi:       float,
    risk_score:    float,
    risk_category: str,
    planned_start: datetime,
    planned_end:   datetime,
    recommendations: List[str],
) -> bool:
    """Legacy wrapper — delegates to send_route_saved_email."""
    return send_route_saved_email(
        to_email=to_email, user_name=user_name,
        source=source, destination=destination,
        route_type=route_type, travel_mode=travel_mode,
        distance_km=distance_km, time_min=time_min, avg_aqi=avg_aqi,
        planned_start=planned_start, planned_end=planned_end,
        risk_score=risk_score, risk_category=risk_category,
        recommendations=recommendations,
    )


# ════════════════════════════════════════════════════════════════════════════════
# SMTP infrastructure
# ════════════════════════════════════════════════════════════════════════════════

def _load_smtp_creds() -> dict:
    """
    Read SMTP credentials at call-time from every possible source.

    Priority (highest to lowest):
      1. pydantic Settings object  — already parsed .env + OS env at startup
      2. OS environment directly   — catches Render dashboard vars set after restart
      3. Manual .env file parse    — last resort if pydantic missed something
    """
    # ── Source 1: pydantic Settings (most reliable — already handles .env + env vars) ──
    try:
        from app.config import settings as _settings
        s_user     = (_settings.SMTP_USER     or "").strip()
        s_password = (_settings.SMTP_PASSWORD or "").strip()
        s_host     = (_settings.SMTP_HOST     or "smtp.gmail.com").strip()
        s_port     = int(_settings.SMTP_PORT  or 587)
        s_from     = (_settings.EMAIL_FROM    or "").strip()
    except Exception:
        s_user = s_password = s_host = s_from = ""
        s_port = 587

    # ── Source 2: OS environment (direct — bypasses pydantic cache) ────────────
    e_user     = os.environ.get("SMTP_USER",     "").strip()
    e_password = os.environ.get("SMTP_PASSWORD", "").strip()
    e_host     = os.environ.get("SMTP_HOST",     "").strip()
    e_port_raw = os.environ.get("SMTP_PORT",     "").strip()
    e_from     = os.environ.get("EMAIL_FROM",    "").strip()
    try:
        e_port = int(e_port_raw) if e_port_raw else 0
    except ValueError:
        e_port = 0

    # Merge: prefer whichever source has the value
    creds = {
        "SMTP_HOST":     e_host     or s_host     or "smtp.gmail.com",
        "SMTP_PORT":     e_port     or s_port     or 587,
        "SMTP_USER":     e_user     or s_user,
        "SMTP_PASSWORD": e_password or s_password,
        "EMAIL_FROM":    e_from     or s_from,
    }

    # ── Source 3: manual .env parse (last resort) ────────────────────────────
    if not creds["SMTP_USER"] or not creds["SMTP_PASSWORD"]:
        env_candidates = [
            Path("/app/.env"),
            Path(__file__).parent.parent.parent / ".env",
            Path(__file__).parent.parent.parent.parent / ".env",
        ]
        for env_path in env_candidates:
            if not env_path.exists():
                continue
            try:
                for raw in env_path.read_text(encoding="utf-8").splitlines():
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key in creds and not creds[key]:
                        if key == "SMTP_PORT":
                            try:
                                creds[key] = int(val)
                            except ValueError:
                                pass
                        else:
                            creds[key] = val
            except Exception as read_err:
                logger.debug("Could not read %s: %s", env_path, read_err)
            if creds["SMTP_USER"] and creds["SMTP_PASSWORD"]:
                logger.info("SMTP creds loaded from %s", env_path)
                break

    return creds


def get_email_debug_info() -> dict:
    """
    Return a safe diagnostic dict (no password value) showing where SMTP
    credentials were resolved from. Used by GET /auth/debug-email.
    """
    creds = _load_smtp_creds()
    return {
        "smtp_host":       creds["SMTP_HOST"],
        "smtp_port":       creds["SMTP_PORT"],
        "smtp_user":       creds["SMTP_USER"] or "MISSING",
        "smtp_password":   "set" if creds["SMTP_PASSWORD"] else "MISSING",
        "email_from":      creds["EMAIL_FROM"] or f"BreatheSafe <{creds['SMTP_USER']}>",
        "credentials_ok":  bool(creds["SMTP_USER"] and creds["SMTP_PASSWORD"]),
    }


def _send_email_sync(
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: str = "",
) -> tuple[bool, str]:
    """
    Synchronous email sender using stdlib smtplib + STARTTLS (Gmail port 587).
    Reads credentials fresh on every call so Render env var changes take effect
    without a restart.
    Returns (success: bool, error_detail: str).
    """
    logger.info("_send_email_sync called → to=%s subject=%s", to_email, subject)
    creds         = _load_smtp_creds()
    smtp_user     = creds["SMTP_USER"]
    smtp_password = creds["SMTP_PASSWORD"]
    smtp_host     = creds["SMTP_HOST"]
    smtp_port     = creds["SMTP_PORT"]
    email_from    = creds["EMAIL_FROM"] or f"BreatheSafe <{smtp_user}>"

    logger.info(
        "SMTP creds check — host=%s port=%s user=%s password=%s",
        smtp_host, smtp_port,
        smtp_user if smtp_user else "MISSING",
        "set" if smtp_password else "MISSING",
    )

    if not smtp_user or not smtp_password:
        detail = (
            f"SMTP credentials not loaded — "
            f"SMTP_USER={'set' if smtp_user else 'MISSING'}, "
            f"SMTP_PASSWORD={'set' if smtp_password else 'MISSING'}. "
            "Check your Render environment variables."
        )
        logger.error(detail)
        return False, detail

    logger.info(
        "Sending email to %s via %s:%s as %s",
        to_email, smtp_host, smtp_port, smtp_user,
    )

    try:
        message = MIMEMultipart("alternative")
        message["From"]    = email_from
        message["To"]      = to_email
        message["Subject"] = subject
        if plain_body:
            message.attach(MIMEText(plain_body, "plain", "utf-8"))
        message.attach(MIMEText(html_body, "html", "utf-8"))

        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, to_email, message.as_string())

        logger.info("Email sent successfully to %s", to_email)
        return True, ""

    except smtplib.SMTPAuthenticationError as exc:
        detail = (
            f"SMTPAuthenticationError — Gmail rejected the password. "
            f"Make sure you're using a 16-character App Password (not your Gmail login). "
            f"Detail: {exc}"
        )
        logger.error("Email FAILED to %s — %s", to_email, detail)
        return False, detail

    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        logger.error("Email FAILED to %s — %s", to_email, detail, exc_info=True)
        return False, detail


async def _send_email(
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: str = "",
) -> tuple[bool, str]:
    """
    Async wrapper around _send_email_sync — used by the test endpoint in
    notifications.py which runs in an async context.
    Offloads the blocking smtplib call to a thread-pool executor so the
    event loop is not blocked.
    """
    import asyncio
    from functools import partial
    loop = asyncio.get_running_loop()
    fn = partial(_send_email_sync, to_email, subject, html_body, plain_body)
    return await loop.run_in_executor(None, fn)
