from __future__ import annotations

import os
import re
from pathlib import Path
from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

# M22: configuration validation. Reject values that would let a misconfigured
# edge deployment start in an unsafe or ambiguous state (e.g. a SQLite business
# database, an out-of-range Re-ID threshold, an impossible severity).

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_VALID_ENVIRONMENTS = {"development", "test", "production"}
_VALID_REID_PROVIDERS = {"stub", "torch", "openvino"}
_VALID_SEVERITIES = {"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
_POSTGRES_URL_RE = re.compile(r"^postgresql(?:\+\w+)?://")


class Settings(BaseSettings):
    APP_NAME: str = "EdgeRetail-IQ"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

    # Deployment environment + startup strictness.
    # development/test => a missing/unreachable business DB is logged, not fatal.
    # production (or STRICT_STARTUP=true) => startup fails loudly on bad config,
    # an unreachable PostgreSQL, or a schema that is behind Alembic head.
    ENVIRONMENT: str = "development"
    STRICT_STARTUP: bool = False

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    # Camera defaults
    CAMERA_FRAME_SKIP: int = 5
    SHELF_CHECK_INTERVAL_SEC: float = 15.0

    # Temporal filter defaults
    GAP_PERSISTENCE_WINDOW_SEC: float = 30.0

    # Sync
    SYNC_AGGREGATION_INTERVAL_SEC: float = 60.0

    # Demo mode
    DEMO_MODE: bool = True
    # Guard for demo mutating endpoints (reset/activate). Override per deployment.
    DEMO_RESET_KEY: str = "storeye-demo-reset"

    # Retail intelligence defaults (override via env / constructor args).
    # A product is LOW_STOCK when available_quantity <= LOW_STOCK_THRESHOLD
    # (zero is included).
    LOW_STOCK_THRESHOLD: int = 10
    # A batch is EXPIRING_SOON when its expiry falls within this many days of
    # the reference date (and is not yet expired).
    EXPIRY_WARNING_DAYS: int = 30

    # PostgreSQL (Storeye business/data layer). Credentials via env only.
    # Example: postgresql+psycopg2://storeye@localhost:5433/storeye
    DATABASE_URL: str = ""

    # ------------------------------------------------------------------
    # Anonymous Re-ID (M19). Every threshold is env-configurable here so
    # operators can tune association behaviour without code changes.
    # ------------------------------------------------------------------
    # Master switch. When False the Re-ID subsystem is fully disabled and the
    # edge pipeline behaves exactly as before (local track ids only).
    REID_ENABLED: bool = True
    # Provider: "stub" (tests/demo) | "torch" (default, ResNet18 ImageNet) |
    # "openvino" (optional Intel OMZ 0287, needs openvino + weights).
    REID_PROVIDER: str = "torch"
    # Minimum combined association score to accept a match (minuscule merges
    # are worse than missed matches).
    REID_SIMILARITY_THRESHOLD: float = 0.72
    # Score at which an accepted match is reported as HIGH confidence.
    REID_HIGH_CONFIDENCE_SCORE: float = 0.86
    # Max real-time gap (s) between a candidate's last sighting and the probe.
    REID_MAX_TIME_GAP_SECONDS: float = 120.0
    # Identity forgotten after this many idle seconds (a re-sighting starts a
    # new anonymous session).
    GLOBAL_PERSON_TIMEOUT_SECONDS: float = 1800.0
    # How often (s) a stable (camera, track) is re-embedded. New tracks embed
    # immediately; stable tracks reuse their embedding in between.
    REID_UPDATE_INTERVAL_SECONDS: float = 10.0

    # ------------------------------------------------------------------
    # Store Intelligence (M20). Deterministic, rule-based insights that
    # consume EXISTING outputs (inventory, batches, shelf/product
    # intelligence, alerts, anonymous journeys). No new CV pipeline, no
    # generative/LLM evaluation, no mutations of operational data.
    # ------------------------------------------------------------------
    # Reused from M15/M17: LOW_STOCK_THRESHOLD, EXPIRY_WARNING_DAYS.
    # A product is LOW_STOCK (M20 rule) when quantity <= reorder_level.
    # EXPIRING_SOON_DAYS aliases EXPIRY_WARNING_DAYS for the insight rule.
    EXPIRING_SOON_DAYS: int = 30
    # Customer-flow insights (M19 zone analytics):
    # A zone is HIGH_TRAFFIC when visits over the window >= this floor.
    HIGH_TRAFFIC_MIN_VISITS: int = 50
    # ...or when visits exceed the per-zone average by this factor (only when
    # the absolute floor is also met — never label on tiny absolute numbers).
    HIGH_TRAFFIC_VISITS_FACTOR: float = 1.5
    # A zone is HIGH_DWELL when average dwell >= this floor (seconds) AND it
    # accumulated at least a few visits (never trust a single observation).
    HIGH_DWELL_MIN_SECONDS: int = 180
    HIGH_DWELL_MIN_VISITS: int = 5
    # Multi-camera journey anonymization-critical floor for traffic-only zones.
    # Sales-driven insight (HIGH_SELLING_LOW_STOCK) requires at least this many
    # billed units in the sales window before it is reported.
    HIGH_SELLING_MIN_UNITS: int = 20
    HIGH_SELLING_SALES_WINDOW_HOURS: int = 168
    # A camera with no observations in the last N minutes is reported offline.
    INSIGHT_CAMERA_STALE_MINUTES: int = 60
    # Insight evaluation windows (rolling, reference_date-anchored).
    INSIGHT_TRAFFIC_WINDOW_HOURS: int = 24
    INSIGHT_DWELL_WINDOW_HOURS: int = 24
    # Recommended re-evaluation cadence (the evaluator is API-triggered;
    # this setting tells operators/pollers how often to call it).
    INSIGHT_REFRESH_INTERVAL_SECONDS: int = 300
    # An OPEN/ACKNOWLEDGED insight whose expires_at falls in the past is
    # retired to EXPIRED on the next evaluation.
    INSIGHT_EXPIRY_TTL_HOURS: int = 48
    # Insights at/above this severity may create/refresh an M16 alert through
    # AlertService deduplication (never a second alert system).
    INSIGHT_TO_ALERT_SEVERITY: str = "HIGH"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # ------------------------------------------------------------------
    # Validation (M22)
    # ------------------------------------------------------------------
    @field_validator("ENVIRONMENT")
    @classmethod
    def _validate_environment(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in _VALID_ENVIRONMENTS:
            raise ValueError(
                f"ENVIRONMENT must be one of {sorted(_VALID_ENVIRONMENTS)}, got {v!r}"
            )
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v not in _VALID_LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(_VALID_LOG_LEVELS)}, got {v!r}")
        return v

    @field_validator("DATABASE_URL")
    @classmethod
    def _validate_database_url(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            return v  # unset is allowed in dev/test; startup decides if fatal
        if v.startswith("sqlite"):
            raise ValueError(
                "DATABASE_URL must point at PostgreSQL; SQLite is not a supported "
                "business database (legacy SQLite is diagnostics-only)."
            )
        if not _POSTGRES_URL_RE.match(v):
            raise ValueError(
                "DATABASE_URL must be a valid PostgreSQL URL, "
                "e.g. postgresql+psycopg2://user@host:5432/storeye"
            )
        return v

    @field_validator("REID_PROVIDER")
    @classmethod
    def _validate_reid_provider(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in _VALID_REID_PROVIDERS:
            raise ValueError(
                f"REID_PROVIDER must be one of {sorted(_VALID_REID_PROVIDERS)}, got {v!r}"
            )
        return v

    @field_validator("INSIGHT_TO_ALERT_SEVERITY")
    @classmethod
    def _validate_insight_severity(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v not in _VALID_SEVERITIES:
            raise ValueError(
                f"INSIGHT_TO_ALERT_SEVERITY must be one of {sorted(_VALID_SEVERITIES)}, got {v!r}"
            )
        return v

    @field_validator("REID_SIMILARITY_THRESHOLD", "REID_HIGH_CONFIDENCE_SCORE")
    @classmethod
    def _validate_unit_interval(cls, v: float, info) -> float:
        if not (0.0 <= float(v) <= 1.0):
            raise ValueError(f"{info.field_name} must be within [0, 1], got {v}")
        return float(v)

    @field_validator(
        "REID_MAX_TIME_GAP_SECONDS",
        "GLOBAL_PERSON_TIMEOUT_SECONDS",
        "REID_UPDATE_INTERVAL_SECONDS",
        "LOW_STOCK_THRESHOLD",
        "EXPIRY_WARNING_DAYS",
        "EXPIRING_SOON_DAYS",
        "HIGH_TRAFFIC_MIN_VISITS",
        "HIGH_DWELL_MIN_SECONDS",
        "HIGH_DWELL_MIN_VISITS",
        "HIGH_SELLING_MIN_UNITS",
        "HIGH_SELLING_SALES_WINDOW_HOURS",
        "INSIGHT_CAMERA_STALE_MINUTES",
        "INSIGHT_TRAFFIC_WINDOW_HOURS",
        "INSIGHT_DWELL_WINDOW_HOURS",
        "INSIGHT_REFRESH_INTERVAL_SECONDS",
        "INSIGHT_EXPIRY_TTL_HOURS",
    )
    @classmethod
    def _validate_non_negative(cls, v, info):
        if float(v) < 0:
            raise ValueError(f"{info.field_name} must be >= 0, got {v}")
        return v

    @field_validator("HIGH_TRAFFIC_VISITS_FACTOR")
    @classmethod
    def _validate_traffic_factor(cls, v: float) -> float:
        if float(v) <= 0:
            raise ValueError(f"HIGH_TRAFFIC_VISITS_FACTOR must be > 0, got {v}")
        return float(v)

    @model_validator(mode="after")
    def _validate_cross_fields(self) -> "Settings":
        if self.REID_HIGH_CONFIDENCE_SCORE < self.REID_SIMILARITY_THRESHOLD:
            raise ValueError(
                "REID_HIGH_CONFIDENCE_SCORE must be >= REID_SIMILARITY_THRESHOLD "
                f"({self.REID_HIGH_CONFIDENCE_SCORE} < {self.REID_SIMILARITY_THRESHOLD})"
            )
        if not self.CORS_ORIGINS:
            raise ValueError("CORS_ORIGINS must contain at least one origin")
        for origin in self.CORS_ORIGINS:
            if not origin.startswith(("http://", "https://")):
                raise ValueError(f"CORS origin must be an http(s) URL, got {origin!r}")
        return self

    @property
    def is_strict(self) -> bool:
        """True when startup must fail on a bad/missing business database."""
        return self.STRICT_STARTUP or self.ENVIRONMENT == "production"


    # ------------------------------------------------------------------
    # Paths are resolved dynamically so env changes are picked up
    # without restarting the interpreter (essential for tests).
    # ------------------------------------------------------------------
    @property
    def BASE_DIR(self) -> Path:
        return Path(__file__).resolve().parent.parent.parent

    @property
    def DATA_DIR(self) -> Path:
        env_dir = os.getenv("EDGERETAIL_DATA_DIR")
        if env_dir:
            return Path(env_dir)
        return self.BASE_DIR / "data"

    @property
    def DB_PATH(self) -> Path:
        env_db = os.getenv("EDGERETAIL_DB_PATH")
        if env_db:
            return Path(env_db)
        return self.DATA_DIR / "edgeretail.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
