"""
BreatheSafe — FastAPI Application Entry Point
Multi-agent AQI forecasting, personalized health risk, and route optimization.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.database import engine, Base

# Import all models so SQLAlchemy registers them before create_all
import app.models  # noqa: F401


# ── Startup / Shutdown ────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup tasks before serving requests, cleanup on shutdown."""
    import threading
    from app.database import SessionLocal
    from sqlalchemy import text

    # Start background scheduler
    from app.scheduler import start_scheduler
    scheduler = start_scheduler()

    # Trigger an immediate pipeline run in a background thread if:
    #   a) DB is empty (fresh deployment), OR
    #   b) The most recent AQI data is more than 2 hours old (Render cold-start gap).
    # This ensures data is always current right after a container restart.
    def _initial_fetch():
        from datetime import datetime, timedelta
        try:
            db  = SessionLocal()
            count    = db.execute(text("SELECT COUNT(*) FROM aqi_data")).scalar()
            last_dt  = db.execute(text("SELECT MAX(datetime) FROM aqi_data")).scalar()
            db.close()

            now_ist  = datetime.utcnow() + timedelta(hours=5, minutes=30)
            stale    = (last_dt is None or
                        (now_ist - last_dt.replace(tzinfo=None)) > timedelta(hours=2))

            if count == 0 or stale:
                gap_desc = "no data" if count == 0 else f"last row={last_dt}"
                print(f"AQI data stale ({gap_desc}) — running catch-up pipeline...")
                from app.services.data_pipeline import run_pipeline
                run_pipeline(update_csv=False, verbose=True)
                print("Catch-up pipeline complete.")
            else:
                print(f"AQI data up to date ({count:,} rows, last={last_dt}) — skipping.")
        except Exception as e:
            print(f"Initial fetch failed (non-fatal): {e}")

    threading.Thread(target=_initial_fetch, daemon=True).start()

    # Log SMTP config so we can confirm credentials loaded in Render logs
    smtp_user = settings.SMTP_USER or "(not set)"
    smtp_ok   = "✓" if (settings.SMTP_USER and settings.SMTP_PASSWORD) else "✗ MISSING"
    print(f"BreatheSafe v{settings.APP_VERSION} started")
    print(f"SMTP: {smtp_user} via {settings.SMTP_HOST}:{settings.SMTP_PORT} [{smtp_ok}]")
    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    print("BreatheSafe shutdown complete")


# ── App Instance ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="BreatheSafe API",
    description="""
## BreatheSafe — AQI Intelligence Platform

Provides:
- 🌍 Real-time AQI monitoring for 100+ Indian cities
- 🔮 1/3/7-day AQI forecasting (Prophet + XGBoost)
- 🫁 Personalized health risk scoring (PAERI)
- 🗺️ Pollution-aware route optimization
- 💡 Explainable AI recommendations
- 🔔 Real-time threshold alerts
    """,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routers (registered as phases are built) ──────────────────────────────────
# Phase 2
from app.routers import auth, profile
app.include_router(auth.router,    prefix="/auth",    tags=["Authentication"])
app.include_router(profile.router, prefix="/profile", tags=["Health Profile"])

# Phase 3
from app.routers import aqi
app.include_router(aqi.router, prefix="/aqi", tags=["AQI Monitoring"])

# Phase 4
from app.routers import forecast
app.include_router(forecast.router, prefix="/forecast", tags=["AQI Forecasting"])

# Phase 5
from app.routers import risk
app.include_router(risk.router, prefix="/risk", tags=["Risk Assessment"])

# Phase 6
from app.routers import route
app.include_router(route.router, prefix="/route", tags=["Route Planning"])

# Phase 7
from app.routers import explain
app.include_router(explain.router, prefix="/explain", tags=["Explainability"])

# Phase 8
from app.routers import notifications
app.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])


# ── Health Check ──────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
def root():
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
def health_check():
    """Simple liveness probe for Docker / load balancers."""
    return {"status": "healthy"}
