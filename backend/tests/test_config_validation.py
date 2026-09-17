"""M22 — configuration validation tests (no database required).

Every invalid deployment setting must be rejected at Settings construction so a
misconfigured edge node fails loudly instead of starting in an ambiguous state
(e.g. a SQLite business database or an out-of-range Re-ID threshold).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings

pytestmark = pytest.mark.no_db


def make(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_valid_configuration_is_accepted():
    s = make(
        DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye",
        REID_SIMILARITY_THRESHOLD=0.5,
        REID_HIGH_CONFIDENCE_SCORE=0.9,
        REID_PROVIDER="torch",
        LOG_LEVEL="info",
    )
    assert s.REID_PROVIDER == "torch"
    assert s.LOG_LEVEL == "INFO"
    assert s.ENVIRONMENT == "development"
    assert s.is_strict is False


def test_sqlite_business_url_is_rejected():
    with pytest.raises(ValidationError, match="PostgreSQL"):
        make(DATABASE_URL="sqlite:///./edgeretail.db")


def test_malformed_database_url_is_rejected():
    with pytest.raises(ValidationError, match="PostgreSQL URL"):
        make(DATABASE_URL="mysql://user@localhost/storeye")


def test_empty_database_url_is_allowed_for_dev():
    assert make(DATABASE_URL="").DATABASE_URL == ""


def test_reid_threshold_out_of_range_is_rejected():
    with pytest.raises(ValidationError, match="REID_SIMILARITY_THRESHOLD"):
        make(REID_SIMILARITY_THRESHOLD=1.4)


def test_reid_high_confidence_below_similarity_is_rejected():
    with pytest.raises(ValidationError, match="REID_HIGH_CONFIDENCE_SCORE"):
        make(REID_SIMILARITY_THRESHOLD=0.8, REID_HIGH_CONFIDENCE_SCORE=0.7)


def test_negative_timeout_is_rejected():
    with pytest.raises(ValidationError, match="GLOBAL_PERSON_TIMEOUT_SECONDS"):
        make(GLOBAL_PERSON_TIMEOUT_SECONDS=-1)


def test_negative_reid_gap_is_rejected():
    with pytest.raises(ValidationError, match="REID_MAX_TIME_GAP_SECONDS"):
        make(REID_MAX_TIME_GAP_SECONDS=-5)


def test_unknown_reid_provider_is_rejected():
    with pytest.raises(ValidationError, match="REID_PROVIDER"):
        make(REID_PROVIDER="magic-cloud-reid")


def test_invalid_insight_severity_is_rejected():
    with pytest.raises(ValidationError, match="INSIGHT_TO_ALERT_SEVERITY"):
        make(INSIGHT_TO_ALERT_SEVERITY="SUPER_HIGH")


def test_invalid_log_level_is_rejected():
    with pytest.raises(ValidationError, match="LOG_LEVEL"):
        make(LOG_LEVEL="verbose")


def test_invalid_environment_is_rejected():
    with pytest.raises(ValidationError, match="ENVIRONMENT"):
        make(ENVIRONMENT="staging-banana")


def test_empty_cors_origins_is_rejected():
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        make(CORS_ORIGINS=[])


def test_non_http_cors_origin_is_rejected():
    with pytest.raises(ValidationError, match="CORS origin"):
        make(CORS_ORIGINS=["ftp://nope"])


def test_production_environment_is_strict():
    assert make(ENVIRONMENT="production").is_strict is True


def test_strict_startup_flag_forces_strict():
    assert make(STRICT_STARTUP=True).is_strict is True
