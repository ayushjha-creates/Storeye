from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "EdgeRetail-IQ"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

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
