"""Initial schema — all BreatheSafe tables

Revision ID: 001
Revises:
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ── users ─────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id",            sa.Integer(),     primary_key=True),
        sa.Column("name",          sa.String(100),   nullable=False),
        sa.Column("email",         sa.String(255),   nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255),   nullable=False),
        sa.Column("is_active",     sa.Boolean(),     server_default="true"),
        sa.Column("created_at",    sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("updated_at",    sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── health_profiles ───────────────────────────────────────────────────────
    op.create_table(
        "health_profiles",
        sa.Column("id",                     sa.Integer(),    primary_key=True),
        sa.Column("user_id",                sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("age",                    sa.Integer(),    nullable=True),
        sa.Column("gender",                 sa.String(20),   nullable=True),
        sa.Column("respiratory_disease",    sa.Boolean(),    server_default="false"),
        sa.Column("heart_disease",          sa.Boolean(),    server_default="false"),
        sa.Column("diabetes",               sa.Boolean(),    server_default="false"),
        sa.Column("kidney_disease",         sa.Boolean(),    server_default="false"),
        sa.Column("is_smoker",              sa.Boolean(),    server_default="false"),
        sa.Column("is_pregnant",            sa.Boolean(),    server_default="false"),
        sa.Column("sensitivity_level",      sa.String(20),   server_default="moderate"),
        sa.Column("preferred_aqi_threshold",sa.Integer(),    server_default="100"),
        sa.Column("exposure_hours_per_day", sa.Float(),      server_default="2.0"),
        sa.Column("default_activity_level", sa.String(20),   server_default="light"),
        sa.Column("home_city",              sa.String(100),  nullable=True),
        sa.Column("created_at",             sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("updated_at",             sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_health_profiles_user_id", "health_profiles", ["user_id"])

    # ── cities ────────────────────────────────────────────────────────────────
    op.create_table(
        "cities",
        sa.Column("id",        sa.Integer(),    primary_key=True),
        sa.Column("name",      sa.String(100),  nullable=False, unique=True),
        sa.Column("state",     sa.String(100),  nullable=False),
        sa.Column("latitude",  sa.Float(),      nullable=False),
        sa.Column("longitude", sa.Float(),      nullable=False),
        sa.Column("country",   sa.String(50),   server_default="India"),
        sa.Column("is_active", sa.Boolean(),    server_default="true"),
    )
    op.create_index("ix_cities_name", "cities", ["name"], unique=True)

    # ── monitoring_stations ───────────────────────────────────────────────────
    op.create_table(
        "monitoring_stations",
        sa.Column("id",           sa.Integer(),   primary_key=True),
        sa.Column("station_id",   sa.String(100), nullable=False, unique=True),
        sa.Column("station_name", sa.String(200), nullable=True),
        sa.Column("city_id",      sa.Integer(),
                  sa.ForeignKey("cities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("latitude",     sa.Float(),     nullable=True),
        sa.Column("longitude",    sa.Float(),     nullable=True),
        sa.Column("data_source",  sa.String(20),  server_default="csv"),
        sa.Column("is_active",    sa.Boolean(),   server_default="true"),
        sa.Column("created_at",   sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_monitoring_stations_station_id",
                    "monitoring_stations", ["station_id"], unique=True)
    op.create_index("ix_monitoring_stations_city_id",
                    "monitoring_stations", ["city_id"])

    # ── aqi_data ──────────────────────────────────────────────────────────────
    op.create_table(
        "aqi_data",
        sa.Column("id",                  sa.Integer(),  primary_key=True),
        sa.Column("station_id",          sa.Integer(),
                  sa.ForeignKey("monitoring_stations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("datetime",            sa.DateTime(), nullable=False),

        # Pollutants
        sa.Column("pm2_5_ugm3",          sa.Float(), nullable=True),
        sa.Column("pm10_ugm3",           sa.Float(), nullable=True),
        sa.Column("co_ugm3",             sa.Float(), nullable=True),
        sa.Column("no2_ugm3",            sa.Float(), nullable=True),
        sa.Column("so2_ugm3",            sa.Float(), nullable=True),
        sa.Column("o3_ugm3",             sa.Float(), nullable=True),
        sa.Column("dust_ugm3",           sa.Float(), nullable=True),
        sa.Column("aod",                 sa.Float(), nullable=True),

        # AQI indices
        sa.Column("us_aqi",              sa.Float(),    nullable=True),
        sa.Column("india_aqi",           sa.Float(),    nullable=True),
        sa.Column("india_aqi_category",  sa.String(30), nullable=True),
        sa.Column("pm25_category_india", sa.String(30), nullable=True),

        # Weather — temperature & wind nullable (filled by enrichment script)
        sa.Column("temperature_c",       sa.Float(), nullable=True),
        sa.Column("wind_speed_kmh",      sa.Float(), nullable=True),
        sa.Column("wind_gusts_kmh",      sa.Float(), nullable=True),
        sa.Column("humidity_percent",    sa.Float(), nullable=True),
        sa.Column("dew_point_c",         sa.Float(), nullable=True),
        sa.Column("pressure_msl_hpa",    sa.Float(), nullable=True),
        sa.Column("cloud_cover_percent", sa.Float(), nullable=True),
        sa.Column("precipitation_mm",    sa.Float(), nullable=True),
        sa.Column("is_raining",          sa.Boolean(), nullable=True),
        sa.Column("heavy_rain",          sa.Boolean(), nullable=True),

        # Temporal / contextual
        sa.Column("month",               sa.Integer(),  nullable=True),
        sa.Column("day_name",            sa.String(10), nullable=True),
        sa.Column("is_weekend",          sa.Boolean(),  nullable=True),
        sa.Column("season",              sa.String(20), nullable=True),
        sa.Column("time_of_day",         sa.String(20), nullable=True),
        sa.Column("festival_period",     sa.Boolean(),  nullable=True),
        sa.Column("crop_burning_season", sa.Boolean(),  nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_aqi_data_station_id",  "aqi_data", ["station_id"])
    op.create_index("ix_aqi_data_datetime",    "aqi_data", ["datetime"])
    op.create_index("ix_aqi_data_india_aqi",   "aqi_data", ["india_aqi"])
    op.create_index("ix_aqi_data_station_datetime",
                    "aqi_data", ["station_id", "datetime"])

    # ── predictions ───────────────────────────────────────────────────────────
    op.create_table(
        "predictions",
        sa.Column("id",                  sa.Integer(), primary_key=True),
        sa.Column("city_id",             sa.Integer(),
                  sa.ForeignKey("cities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("predicted_for_date",  sa.DateTime(), nullable=False),
        sa.Column("predicted_india_aqi", sa.Float(),    nullable=False),
        sa.Column("confidence_lower",    sa.Float(),    nullable=True),
        sa.Column("confidence_upper",    sa.Float(),    nullable=True),
        sa.Column("predicted_category",  sa.String(30), nullable=True),
        sa.Column("horizon_days",        sa.Integer(),  server_default="1"),
        sa.Column("model_version",       sa.String(50), nullable=True),
        sa.Column("mae",                 sa.Float(),    nullable=True),
        sa.Column("rmse",                sa.Float(),    nullable=True),
        sa.Column("created_at",          sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_predictions_city_id",   "predictions", ["city_id"])
    op.create_index("ix_predictions_date",      "predictions", ["predicted_for_date"])
    op.create_index("ix_predictions_city_date", "predictions",
                    ["city_id", "predicted_for_date"])

    # ── risk_logs ─────────────────────────────────────────────────────────────
    op.create_table(
        "risk_logs",
        sa.Column("id",            sa.Integer(), primary_key=True),
        sa.Column("user_id",       sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("city_id",       sa.Integer(),
                  sa.ForeignKey("cities.id"), nullable=True),
        sa.Column("risk_score",    sa.Float(),    nullable=False),
        sa.Column("risk_category", sa.String(20), nullable=False),
        sa.Column("aqi_used",      sa.Float(),    nullable=False),
        sa.Column("exposure_hours",sa.Float(),    nullable=True),
        sa.Column("activity_level",sa.String(20), nullable=True),
        sa.Column("age_used",      sa.Integer(),  nullable=True),
        sa.Column("factors_json",  postgresql.JSON(), nullable=True),
        sa.Column("explanation",   sa.String(500),    nullable=True),
        sa.Column("timestamp",     sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_risk_logs_user_id",  "risk_logs", ["user_id"])
    op.create_index("ix_risk_logs_timestamp","risk_logs", ["timestamp"])

    # ── notifications ─────────────────────────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column("id",                sa.Integer(),  primary_key=True),
        sa.Column("user_id",           sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("city_id",           sa.Integer(),
                  sa.ForeignKey("cities.id"), nullable=True),
        sa.Column("notification_type", sa.String(30), nullable=False),
        sa.Column("message",           sa.String(500),nullable=False),
        sa.Column("aqi_value",         sa.Float(),    nullable=True),
        sa.Column("is_read",           sa.Boolean(),  server_default="false"),
        sa.Column("sent_via_email",    sa.Boolean(),  server_default="false"),
        sa.Column("sent_at",           sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("read_at",           sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_sent_at", "notifications", ["sent_at"])

    # ── routes ────────────────────────────────────────────────────────────────
    op.create_table(
        "routes",
        sa.Column("id",                     sa.Integer(), primary_key=True),
        sa.Column("user_id",                sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_name",            sa.String(200), nullable=True),
        sa.Column("source_lat",             sa.Float(),     nullable=False),
        sa.Column("source_lon",             sa.Float(),     nullable=False),
        sa.Column("dest_name",              sa.String(200), nullable=True),
        sa.Column("dest_lat",               sa.Float(),     nullable=False),
        sa.Column("dest_lon",               sa.Float(),     nullable=False),
        sa.Column("route_type",             sa.String(20),  nullable=False),
        sa.Column("travel_mode",            sa.String(20),  server_default="driving"),
        sa.Column("distance_km",            sa.Float(),     nullable=True),
        sa.Column("time_min",               sa.Float(),     nullable=True),
        sa.Column("avg_aqi_exposure",       sa.Float(),     nullable=True),
        sa.Column("exposure_reduction_pct", sa.Float(),     nullable=True),
        sa.Column("route_geometry_json",    postgresql.JSON(), nullable=True),
        sa.Column("explanation",            sa.String(300), nullable=True),
        sa.Column("created_at",             sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_routes_user_id", "routes", ["user_id"])


def downgrade() -> None:
    op.drop_table("routes")
    op.drop_table("notifications")
    op.drop_table("risk_logs")
    op.drop_table("predictions")
    op.drop_table("aqi_data")
    op.drop_table("monitoring_stations")
    op.drop_table("cities")
    op.drop_table("health_profiles")
    op.drop_table("users")
