"""
BreatheSafe — APScheduler Background Jobs

Jobs:
  1. fetch_aqi_job          — stub (replaced by pipeline)
  2. check_alerts_job       — AQI threshold alerts every 30 min
  3. pipeline_hourly_job    — fetch latest data, insert into DB (every 60 min)
  4. pipeline_daily_job     — fetch yesterday, insert DB + update CSV (daily at 02:00 IST)
  5. cleanup_old_data_job   — purge aqi_data rows > 90 days (nightly at 03:00 IST)
  6. route_aqi_monitor_job  — smart AQI monitoring emails for saved routes (every 30 min)
"""

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings

logger = logging.getLogger(__name__)


# ── AQI Fetch Job (kept for compatibility — pipeline replaces actual fetch) ───
def fetch_aqi_job():
    logger.debug("AQI fetch stub triggered (pipeline handles real fetching)")


# ── Alert Check Job ────────────────────────────────────────────────────────────
def check_alerts_job():
    """
    For every active user with a health profile and home city:
      1. Get the latest AQI for their home city.
      2. If AQI > preferred_aqi_threshold and not notified in last 6 h → create notification.
      3. If a saved forecast predicts high AQI in next 24 h → create forecast alert.
    """
    from app.database import SessionLocal
    from sqlalchemy import func, desc

    db = SessionLocal()
    try:
        from app.models.user import User
        from app.models.health_profile import HealthProfile
        from app.models.city import City
        from app.models.aqi_data import AQIData
        from app.models.monitoring_station import MonitoringStation
        from app.models.prediction import Prediction
        from app.models.notification import NotificationTypeEnum
        from app.services.notifier import (
            create_notification, already_notified_recently,
            build_aqi_alert_message, build_forecast_alert_message,
        )
        from app.ml.predictor import aqi_category

        users = (
            db.query(User)
            .join(HealthProfile, User.id == HealthProfile.user_id)
            .filter(User.is_active == True)
            .all()
        )

        triggered = 0
        for user in users:
            profile = user.health_profile
            if not profile or not profile.home_city:
                continue

            city = (
                db.query(City)
                .filter(func.lower(City.name) == profile.home_city.lower())
                .first()
            )
            if not city:
                continue

            station = (
                db.query(MonitoringStation)
                .filter(MonitoringStation.city_id == city.id)
                .first()
            )
            if not station:
                continue

            latest = (
                db.query(AQIData)
                .filter(
                    AQIData.station_id == station.id,
                    AQIData.india_aqi  != None,
                )
                .order_by(desc(AQIData.datetime))
                .first()
            )
            if not latest:
                continue

            aqi    = float(latest.india_aqi)
            thresh = profile.preferred_aqi_threshold or 100

            # ── AQI threshold alert ───────────────────────────────────────────
            if aqi > thresh:
                if not already_notified_recently(
                    db, user.id, city.id,
                    NotificationTypeEnum.aqi_threshold, hours=6
                ):
                    msg = build_aqi_alert_message(
                        city.name, aqi, thresh, aqi_category(aqi)
                    )
                    create_notification(
                        db, user.id, city.id,
                        NotificationTypeEnum.aqi_threshold, msg, aqi
                    )
                    triggered += 1
                    logger.info("Alert → user=%d city=%s AQI=%.0f > threshold=%d",
                                user.id, city.name, aqi, thresh)

            # ── Forecast alert (next 24 h) ────────────────────────────────────
            next_day_pred = (
                db.query(Prediction)
                .filter(
                    Prediction.city_id      == city.id,
                    Prediction.horizon_days == 1,
                )
                .order_by(desc(Prediction.created_at))
                .first()
            )
            if next_day_pred and next_day_pred.predicted_india_aqi > thresh * 1.2:
                if not already_notified_recently(
                    db, user.id, city.id,
                    NotificationTypeEnum.forecast_alert, hours=12
                ):
                    cat = aqi_category(next_day_pred.predicted_india_aqi)
                    msg = build_forecast_alert_message(
                        city.name, next_day_pred.predicted_india_aqi, 1, cat
                    )
                    create_notification(
                        db, user.id, city.id,
                        NotificationTypeEnum.forecast_alert, msg,
                        next_day_pred.predicted_india_aqi,
                    )
                    triggered += 1

        if triggered:
            logger.info("✅ Alert job: %d notifications created at %s",
                        triggered, datetime.now().strftime("%H:%M"))
        else:
            logger.debug("Alert job: no new notifications")

    except Exception as e:
        logger.error("Alert job failed: %s", e)
    finally:
        db.close()


# ── Route AQI Monitor Job ─────────────────────────────────────────────────────
def route_aqi_monitor_job():
    """
    Smart AQI monitoring for all saved routes departing within the next 7 days.

    Frequency logic (per route):
      > 7 days until departure  → skip entirely (too far out)
      3–7 days                  → check every 36 h (≈ 2 emails in the window)
      1–3 days                  → check every 18 h (≈ 2–3 emails)
      6–24 h                    → check every 4 h
      < 6 h (imminent travel)   → check every 2 h

    Sends an email if any of:
      • AQI changed by >15 points OR >15% since last notification
      • AQI category changed (e.g., Moderate → Poor)
      • AQI is Dangerous (>200) and departure is < 24 h away
    """
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        now        = datetime.now(timezone.utc)
        window_end = now + timedelta(days=7)

        from app.models.route import Route
        future_routes = (
            db.query(Route)
            .filter(
                Route.planned_start > now,
                Route.planned_start <= window_end,
            )
            .all()
        )

        if not future_routes:
            logger.debug("Route monitor: no upcoming routes in 7-day window")
            return

        processed = 0
        for route in future_routes:
            try:
                sent = _check_and_notify_route(db, route, now)
                if sent:
                    processed += 1
            except Exception as e:
                logger.error(
                    "Route monitor failed for route_id=%d: %s", route.id, e,
                    exc_info=True,
                )

        if processed:
            logger.info(
                "✅ Route monitor: sent %d AQI update email(s) at %s",
                processed, datetime.now().strftime("%H:%M"),
            )
        else:
            logger.debug("Route monitor: no emails triggered this cycle")

    except Exception as e:
        logger.error("route_aqi_monitor_job failed: %s", e, exc_info=True)
    finally:
        db.close()


def _check_and_notify_route(db, route, now: datetime) -> bool:
    """
    Evaluate one saved route and send a monitoring email if conditions warrant it.
    Returns True if an email was dispatched.
    """
    from sqlalchemy import desc, func
    from app.models.user import User
    from app.models.health_profile import HealthProfile
    from app.models.city import City
    from app.models.monitoring_station import MonitoringStation
    from app.models.aqi_data import AQIData
    from app.models.notification import Notification, NotificationTypeEnum
    from app.services.paeri import calculate_paeri
    from app.services.notifier import (
        route_notified_recently, create_route_notification,
        send_route_aqi_update_email,
    )
    from app.ml.predictor import aqi_category

    hours_until = (route.planned_start - now).total_seconds() / 3600

    # ── Determine cooldown based on travel proximity ─────────────────────────
    if hours_until > 168:       # > 7 days
        return False
    elif hours_until > 72:      # 3–7 days  → ~2 emails total
        cooldown_hours = 36.0
    elif hours_until > 24:      # 1–3 days  → ~2–3 emails total
        cooldown_hours = 18.0
    elif hours_until > 6:       # 6–24 h    → every 4 h
        cooldown_hours = 4.0
    else:                       # < 6 h     → every 2 h
        cooldown_hours = 2.0

    # ── Check cooldown ────────────────────────────────────────────────────────
    if route_notified_recently(db, route.id, route.user_id, hours=cooldown_hours):
        return False

    # ── Get current AQI near source ───────────────────────────────────────────
    nearest_city = _nearest_city_for_coords(db, route.source_lat, route.source_lon)
    if not nearest_city:
        return False

    station = (
        db.query(MonitoringStation)
        .filter(MonitoringStation.city_id == nearest_city.id)
        .first()
    )
    if not station:
        return False

    latest_aqi_row = (
        db.query(AQIData)
        .filter(AQIData.station_id == station.id, AQIData.india_aqi != None)
        .order_by(desc(AQIData.datetime))
        .first()
    )
    if not latest_aqi_row:
        return False

    current_aqi = float(latest_aqi_row.india_aqi)
    current_cat = aqi_category(current_aqi)

    # ── Retrieve previous AQI (from last route notification) ─────────────────
    last_notif = (
        db.query(Notification)
        .filter(
            Notification.route_id == route.id,
            Notification.notification_type.in_([
                NotificationTypeEnum.route_saved,
                NotificationTypeEnum.route_monitor,
            ]),
        )
        .order_by(desc(Notification.sent_at))
        .first()
    )
    previous_aqi = (
        float(last_notif.aqi_value)
        if last_notif and last_notif.aqi_value is not None
        else (route.avg_aqi_exposure or current_aqi)
    )
    previous_cat = aqi_category(previous_aqi)

    # ── Decide whether to notify ──────────────────────────────────────────────
    aqi_change     = abs(current_aqi - previous_aqi)
    aqi_change_pct = aqi_change / max(previous_aqi, 1) * 100

    should_notify = False
    if hours_until <= 24 and current_aqi > 200:
        # Always alert when departure is < 24 h and air quality is Poor or worse
        should_notify = True
    elif current_cat != previous_cat:
        # AQI category changed — always worth telling the user
        should_notify = True
    elif aqi_change >= 20 or aqi_change_pct >= 15:
        # Meaningful absolute or percentage change
        should_notify = True

    if not should_notify:
        return False

    # ── Load user + health profile ────────────────────────────────────────────
    user = db.query(User).filter(User.id == route.user_id).first()
    if not user:
        return False

    risk_score    = None
    risk_category = None
    recommendations: list = []

    profile = user.health_profile
    if profile:
        try:
            duration_hours = max(
                0.25,
                min(
                    12.0,
                    (route.planned_end - route.planned_start).total_seconds() / 3600
                ),
            )
            activity = str(profile.default_activity_level or "light")
            paeri    = calculate_paeri(
                aqi            = current_aqi,
                profile        = profile,
                exposure_hours = duration_hours,
                activity_level = activity,
            )
            risk_score    = paeri.risk_score
            risk_category = paeri.risk_category
            recommendations = paeri.recommendations
        except Exception as e:
            logger.warning("PAERI failed for route %d: %s", route.id, e)

    # ── Create in-app notification ────────────────────────────────────────────
    src  = route.source_name or "origin"
    dst  = route.dest_name   or "destination"
    risk_info = f" | Risk: {risk_category}" if risk_category else ""
    create_route_notification(
        db                = db,
        user_id           = route.user_id,
        route_id          = route.id,
        city_id           = nearest_city.id,
        notification_type = NotificationTypeEnum.route_monitor,
        message           = (
            f"AQI Update for {src} → {dst}: "
            f"current AQI {current_aqi:.0f} ({current_cat}){risk_info}. "
            f"{hours_until:.0f}h until departure."
        ),
        aqi_value         = current_aqi,
    )

    # ── Dispatch email (sync — safe to call directly from APScheduler thread) ─
    try:
        sent = send_route_aqi_update_email(
            to_email        = user.email,
            user_name       = user.name,
            source          = src,
            destination     = dst,
            planned_start   = route.planned_start,
            planned_end     = route.planned_end,
            current_aqi     = current_aqi,
            previous_aqi    = previous_aqi,
            current_cat     = current_cat,
            risk_score      = risk_score,
            risk_category   = risk_category,
            recommendations = recommendations,
            hours_until     = hours_until,
        )
        if sent:
            logger.info(
                "Route monitor email sent → user=%d route=%d AQI=%.0f "
                "(was %.0f) %.0fh until departure",
                user.id, route.id, current_aqi, previous_aqi, hours_until,
            )
        else:
            logger.warning(
                "Route monitor email failed (see SMTP logs) route=%d", route.id
            )
        return sent
    except Exception as e:
        logger.error(
            "Route monitor email FAILED for route %d: %s", route.id, e,
            exc_info=True,
        )
        return False


def _nearest_city_for_coords(db, lat: float, lon: float):
    """Return the nearest City object to the given coordinates."""
    import math
    from app.models.city import City

    cities = db.query(City).filter(
        City.latitude != None, City.longitude != None
    ).all()
    if not cities:
        return None

    def _dist(c):
        dlat = math.radians(lat - c.latitude)
        dlon = math.radians(lon - c.longitude)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat)) * math.cos(math.radians(c.latitude))
             * math.sin(dlon / 2) ** 2)
        return 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return min(cities, key=_dist)


# ── Pipeline: hourly DB insert ────────────────────────────────────────────────
def pipeline_hourly_job():
    """
    Runs every hour.
    Fetches data from MAX(datetime)+1h up to current hour for all 29 cities.
    Inserts new rows into PostgreSQL only (no CSV write).
    """
    logger.info("Pipeline (hourly) starting...")
    try:
        from app.services.data_pipeline import run_pipeline
        result = run_pipeline(update_csv=False, verbose=True)
        logger.info(
            "Pipeline (hourly) done | inserted=%d fetched=%d | %s -> %s",
            result["rows_inserted"], result["rows_fetched"],
            result["start_dt"], result["end_dt"],
        )
    except Exception as e:
        logger.error("Pipeline (hourly) FAILED: %s", e, exc_info=True)


# ── Data Retention: purge rows older than 90 days ────────────────────────────
def cleanup_old_data_job():
    """
    Runs nightly at 03:00 IST.
    Deletes aqi_data rows older than 90 days so the table stays small.
    """
    from app.database import SessionLocal
    from sqlalchemy import text

    logger.info("Data retention cleanup starting (purge > 90 days)...")
    db = SessionLocal()
    try:
        result = db.execute(
            text("DELETE FROM aqi_data WHERE datetime < NOW() - INTERVAL '90 days'")
        )
        db.commit()
        deleted = result.rowcount
        logger.info("Data retention: deleted %d rows older than 90 days", deleted)
    except Exception as e:
        db.rollback()
        logger.error("Data retention cleanup FAILED: %s", e)
    finally:
        db.close()


# ── Pipeline: daily CSV + DB update ──────────────────────────────────────────
def pipeline_daily_job():
    """
    Runs every day at 02:00 IST.
    Same fetch as hourly but also updates the master CSV file.
    """
    logger.info("Pipeline (daily) starting — will also update CSV...")
    try:
        from app.services.data_pipeline import run_pipeline
        result = run_pipeline(update_csv=True, verbose=True)
        logger.info(
            "Pipeline (daily) done | inserted=%d csv_added=%d | %s -> %s",
            result["rows_inserted"], result["csv_rows_added"],
            result["start_dt"], result["end_dt"],
        )
    except Exception as e:
        logger.error("Pipeline (daily) FAILED: %s", e, exc_info=True)


# ── Scheduler bootstrap ───────────────────────────────────────────────────────
def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    scheduler.add_job(
        fetch_aqi_job,
        trigger=IntervalTrigger(minutes=settings.AQI_FETCH_INTERVAL_MINUTES),
        id="fetch_aqi",
        name="Fetch AQI Data (stub)",
        replace_existing=True,
    )

    scheduler.add_job(
        check_alerts_job,
        trigger=IntervalTrigger(minutes=settings.ALERT_CHECK_INTERVAL_MINUTES),
        id="check_alerts",
        name="Check Alert Thresholds",
        replace_existing=True,
    )

    # ── Route AQI monitor — runs every 30 min ────────────────────────────────
    scheduler.add_job(
        route_aqi_monitor_job,
        trigger=IntervalTrigger(minutes=30),
        id="route_aqi_monitor",
        name="Smart Route AQI Monitor",
        replace_existing=True,
        max_instances=1,    # never overlap
        coalesce=True,      # skip missed firings if server was down
    )

    # ── Data pipeline jobs ────────────────────────────────────────────────────
    scheduler.add_job(
        pipeline_hourly_job,
        trigger=IntervalTrigger(minutes=60),
        id="pipeline_hourly",
        name="Hourly Data Pipeline (DB insert)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        pipeline_daily_job,
        trigger=CronTrigger(hour=2, minute=0, timezone="Asia/Kolkata"),
        id="pipeline_daily",
        name="Daily Data Pipeline (DB + CSV)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # ── Data retention: delete aqi_data rows > 90 days at 03:00 IST ──────────
    scheduler.add_job(
        cleanup_old_data_job,
        trigger=CronTrigger(hour=3, minute=0, timezone="Asia/Kolkata"),
        id="cleanup_old_data",
        name="Data Retention Cleanup (delete > 90 days)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started — "
        "AQI alerts every %d min | "
        "Route AQI monitor every 30 min | "
        "Data pipeline: hourly (DB) + daily 02:00 IST (DB+CSV)",
        settings.ALERT_CHECK_INTERVAL_MINUTES,
    )
    return scheduler
