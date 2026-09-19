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
_VALID_SAMESITE = {"lax", "strict", "none"}
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
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]

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

    # ------------------------------------------------------------------
    # Authentication & sessions (local/offline deployment).
    # ------------------------------------------------------------------
    # Name of the HttpOnly session cookie issued on login.
    AUTH_COOKIE_NAME: str = "storeye_session"
    # Secure flag: keep False for local HTTP development (http://localhost).
    # Set True when the frontend/backend are served over HTTPS.
    AUTH_COOKIE_SECURE: bool = False
    # SameSite policy. "lax" is appropriate for a local edge web app; "strict"
    # further limits cookie sends on cross-site navigation.
    AUTH_COOKIE_SAMESITE: str = "lax"
    # How long a session stays valid (and how long the cookie lives).
    AUTH_SESSION_TTL_HOURS: float = 12.0
    # Minimum accepted password length.
    AUTH_PASSWORD_MIN_LENGTH: int = 8
    # Login-attempt throttle: at most this many failed attempts per identity
    # within the throttling window before the endpoint refuses (in-memory).
    AUTH_LOGIN_MAX_ATTEMPTS: int = 8
    AUTH_LOGIN_THROTTLE_SECONDS: int = 900
    # Custom header the browser must send on every request; used to reject
    # cross-site (CSRF) state-changing requests to cookie-authenticated routes.
    AUTH_CSRF_HEADER: str = "X-Storeye-CSRF"
    # Expected value for the CSRF header (the frontend client sends it on all
    # non-GET requests; a cross-origin form cannot).
    AUTH_CSRF_VALUE: str = "1"

    # ------------------------------------------------------------------
    # Mobile-to-Edge USB Intake (M25).
    # ------------------------------------------------------------------
    # Directory a phone is copied into over USB. Empty => `<data>/intake`.
    STOREYE_INTAKE_DIR: str = ""
    # Hard ceiling for pushed photos (bytes); aligns with the M17 reading cap.
    INTAKE_MAX_MB: int = 15
    # How long a file's size must stay unchanged before it is read (a phone
    # copies in chunks; a still-growing file must never be processed).
    INTAKE_STABILITY_SECONDS: float = 2.0
    # Watcher poll cadence.
    INTAKE_WATCH_INTERVAL_SECONDS: float = 1.0
    # Processed/failed intake files older than this are swept away; active
    # (review-pending) photos are never removed.
    INTAKE_RETENTION_DAYS: int = 7

    # ------------------------------------------------------------------
    # Browser demo-footage ingestion (camera demo section).
    # ------------------------------------------------------------------
    # Hard ceiling for a CCTV/phone video dropped from the browser into the
    # Cameras page demo (bytes). 200 MB is generous for a few-minute MP4.
    DEMO_VIDEO_MAX_MB: int = 200

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
    # Same-camera re-acquisition (M27 Phase 2-5): re-attach a re-created local
    # track to its prior global identity when it is the only person on the
    # camera and the short absence is bridged by a strong appearance match.
    # Concurrent same-camera tracks are never merged.
    REID_SAME_CAMERA_REACQUISITION: bool = True
    REID_SAME_CAMERA_REACQUISITION_SECONDS: float = 2.0
    REID_SAME_CAMERA_REACQUISITION_MAX_GAP_SECONDS: float = 15.0
    REID_SAME_CAMERA_SIMILARITY_THRESHOLD: float = 0.85

    # ------------------------------------------------------------------
    # Edge runtime (M27 Phase 17-21). Maximum number of cameras that may run
    # concurrently on this local Edge node (0 => unlimited). A start beyond
    # capacity is refused with a clear error instead of overloading the box.
    # ------------------------------------------------------------------
    EDGE_MAX_CAMERAS: int = 8

    # ------------------------------------------------------------------
    # M29 — Real-time person pipeline + minimal analytics storage. The edge
    # runtime keeps a HOT in-memory person-state cache (Layer A) so it can
    # resolve track->global-person and zone state at live frame rates WITHOUT
    # per-frame database writes, and only the minimal JOURNEY ANALYTICS touch
    # PostgreSQL (retention-bounded below). No names/faces/raw frames anywhere.
    # ------------------------------------------------------------------
    # How long a hot cache entry survives while a person is unseen (seconds).
    # After this the cached state is evicted; the durable PostgreSQL analytics
    # are governed by PERSON_ANALYTICS_RETENTION_DAYS.
    PERSON_CACHE_TTL_SECONDS: int = 86400  # 24h
    # Soft capacity bound for the hot cache (LRU eviction). 0 = unlimited.
    PERSON_CACHE_MAX_ENTRIES: int = 2048
    # Durable journey/session/zone analytics are purged after this many days
    # (see scripts/purge_analytics.py). Never touches inventory/batches/bills.
    PERSON_ANALYTICS_RETENTION_DAYS: int = 30
    # A local track must be seen this many CONSECUTIVE frames before expensive
    # person work (Re-ID association, cache promotion, zone/durable events)
    # runs. Default 5 filters single-frame detector noise (motion flicker,
    # low-res cameras) that previously minted one ghost "visitor" per blip.
    # A per-camera stable_track_min_frames > 1 wins over this global floor.
    PERSON_STABLE_TRACK_MIN_FRAMES: int = 5
    # PER-FRAME PERSON observation rows (the M13/M14 camera dashboards depend on
    # these) are throttled by the per-camera min gap AND purged after this many
    # hours. Set False for cache-only person analytics (recommended on very long
    # running, high-traffic deployments).
    PERSON_OBSERVATION_PERSISTENCE: bool = True
    PERSON_OBSERVATION_RETENTION_HOURS: int = 24
    # Global AI-processing cap (frames/sec) applied per camera unless the camera
    # config overrides it. 0 = uncapped. Capture is NOT throttled — the live
    # stream stays fluid and the AI simply processes the latest frame on time.
    AI_TARGET_FPS: float = 0.0
    # M30 periodic shelf-occupancy monitoring.
    # On-disk shelf snapshot images are swept (with their DB rows) after this
    # many days. 0 = keep forever (not recommended).
    SHELF_SNAPSHOT_RETENTION_DAYS: int = 7
    # M30 hot read mirror: the latest snapshot rows are ALSO cached in memory
    # (Layer-A, one shared cache per runtime) so the monitor card + history are
    # served without a DB round-trip. PostgreSQL stays authoritative — a cache
    # miss falls back to SQL. These tune that mirror.
    SHELF_SNAPSHOT_CACHE_TTL_SECONDS: int = 86400  # 24h
    SHELF_SNAPSHOT_CACHE_MAX_ENTRIES: int = 4096
    SHELF_SNAPSHOT_CACHE_PER_REGION_HISTORY: int = 24

    # ------------------------------------------------------------------
    # SMS bill receipts (M31). When SMS_ENABLED, creating a bill for a
    # customer WITH a phone number automatically queues a receipt in the
    # `sms_messages` outbox; a background worker drains it through the
    # provider (MSG91 by default) with backoff. Billing NEVER blocks on the
    # network — enqueueing is atomic with the bill write; a gateway failure
    # only retries/FAILs the outbox row. Targeted sender ID is optional.
    # ------------------------------------------------------------------
    SMS_ENABLED: bool = False
    SMS_PROVIDER: str = "msg91"
    MSG91_AUTH_KEY: str = ""
    MSG91_SENDER_ID: str = ""
    MSG91_ROUTE: int = 4  # MSG91 route 4 = transactional
    MSG91_COUNTRY_CODE: str = "91"
    # Overridable for tests to point at a fake MSG91 endpoint (never a real
    # number). Trailing slash optional; the legacy `api/sendhttp.php` path is
    # appended at request time.
    MSG91_BASE_URL: str = "https://control.msg91.com"
    # Background worker poll cadence.
    SMS_POLL_SECONDS: float = 5.0
    # Max delivery attempts per message (1 = single try, no retry).
    SMS_MAX_ATTEMPTS: int = 5
    # Multiplicative backoff base: attempt N waits base * 2**(N-1) seconds.
    SMS_RETRY_BACKOFF_SECONDS: float = 60.0
    # A SENDING row untouched for longer than this is considered a crashed
    # claim and re-claimed by the worker.
    SMS_STALE_CLAIM_SECONDS: float = 30.0
    # Per-request gateway timeout.
    SMS_TIMEOUT_SECONDS: float = 10.0

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

    @field_validator("AUTH_COOKIE_SAMESITE")
    @classmethod
    def _validate_samesite(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in _VALID_SAMESITE:
            raise ValueError(
                f"AUTH_COOKIE_SAMESITE must be one of {sorted(_VALID_SAMESITE)}, got {v!r}"
            )
        return v

    @field_validator("AUTH_PASSWORD_MIN_LENGTH")
    @classmethod
    def _validate_min_password_length(cls, v: int) -> int:
        if int(v) < 8:
            raise ValueError("AUTH_PASSWORD_MIN_LENGTH must be >= 8")
        return int(v)

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
        "INTAKE_MAX_MB",
        "INTAKE_RETENTION_DAYS",
        "SHELF_SNAPSHOT_RETENTION_DAYS",
        "SHELF_SNAPSHOT_CACHE_TTL_SECONDS",
        "SHELF_SNAPSHOT_CACHE_MAX_ENTRIES",
        "SHELF_SNAPSHOT_CACHE_PER_REGION_HISTORY",
        "MSG91_ROUTE",
        "SMS_MAX_ATTEMPTS",
        "SMS_RETRY_BACKOFF_SECONDS",
        "SMS_STALE_CLAIM_SECONDS",
    )
    @classmethod
    def _validate_non_negative(cls, v, info):
        if float(v) < 0:
            raise ValueError(f"{info.field_name} must be >= 0, got {v}")
        return v

    @field_validator("EDGE_MAX_CAMERAS")
    @classmethod
    def _validate_edge_capacity(cls, v: int) -> int:
        if int(v) < 0:
            raise ValueError("EDGE_MAX_CAMERAS must be >= 0 (0 = unlimited)")
        return int(v)

    @field_validator("INTAKE_STABILITY_SECONDS", "INTAKE_WATCH_INTERVAL_SECONDS")
    @classmethod
    def _validate_positive_seconds(cls, v: float, info) -> float:
        if float(v) <= 0:
            raise ValueError(f"{info.field_name} must be > 0, got {v}")
        return float(v)

    @field_validator("SMS_POLL_SECONDS", "SMS_TIMEOUT_SECONDS")
    @classmethod
    def _validate_positive_sms_seconds(cls, v: float, info) -> float:
        if float(v) <= 0:
            raise ValueError(f"{info.field_name} must be > 0, got {v}")
        return float(v)

    @field_validator("SMS_PROVIDER")
    @classmethod
    def _validate_sms_provider(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v != "msg91":
            raise ValueError(f"SMS_PROVIDER must be 'msg91', got {v!r}")
        return v

    @field_validator("MSG91_SENDER_ID")
    @classmethod
    def _validate_msg91_sender_id(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            return v
        if len(v) != 6 or not v.isalnum():
            raise ValueError(
                "MSG91_SENDER_ID must be exactly 6 alphanumeric characters "
                "(MSG91 requirement), got {v!r}"
            )
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

    @property
    def INTAKE_ROOT(self) -> Path:
        """Root directory of the USB intake bridge (default `<data>/intake`)."""
        env_dir = os.getenv("STOREYE_INTAKE_DIR") or self.STOREYE_INTAKE_DIR
        if env_dir:
            return Path(env_dir).expanduser()
        return self.DATA_DIR / "intake"

    @property
    def SHELF_SNAPSHOT_DIR(self) -> Path:
        """Root directory for periodic shelf-snapshot images (M30).

        Snapshots live on disk ONLY — the `shelf_snapshots` table stores
        relative paths. Default `<data>/shelf_snapshots`.
        """
        env_dir = os.getenv("STOREYE_SHELF_SNAPSHOT_DIR")
        if env_dir:
            return Path(env_dir).expanduser()
        return self.DATA_DIR / "shelf_snapshots"

    @property
    def DEMO_VIDEO_DIR(self) -> Path:
        """Directory for browser-uploaded demo CCTV footage (Cameras page).

        Files are organized per store (`<data>/demo_videos/<store>/`); the
        `cameras` table config.source points at the absolute path. Default
        `<data>/demo_videos`.
        """
        env_dir = os.getenv("STOREYE_DEMO_VIDEO_DIR")
        if env_dir:
            return Path(env_dir).expanduser()
        return self.DATA_DIR / "demo_videos"


@lru_cache
def get_settings() -> Settings:
    return Settings()
