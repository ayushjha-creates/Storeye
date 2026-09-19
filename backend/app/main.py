import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import get_settings
from .core.logging import setup_logging, get_logger
from .core.database import init_db, close_db
from .core.startup import run_startup_checks
from .api.health import router as health_router
from .api.system import router as system_router
from .api.errors import _register_handlers
from .api.edge_api import router as edge_router
from .api.routers import (
    stores,
    users,
    cameras,
    zones,
    shelves,
    products,
    inventory,
    customers,
    sales,
    bills,
    notifications,
    observations,
    reconciliation,
    intelligence,
    alerts,
    batch_intake,
    demo,
    journeys,
    insights,
    mobile_intake,
    shelf_snapshots,
    auth,
    sms,
)

setup_logging()
logger = get_logger("edgeretail")


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)
        # M22 startup sequence: config -> PostgreSQL -> migrations -> app.
        # In strict (production) mode this raises before serving if the
        # business database is missing or behind Alembic head.
        run_startup_checks()
        # Legacy SQLite/SQLModel diagnostics stack (health/ready/metrics only;
        # never a business fallback).
        init_db()
        # M25: start the USB intake watcher (background thread). Skipped under
        # pytest so tests drive ingestion deterministically via scan_now().
        intake_manager = None
        if "pytest" not in sys.modules:
            try:
                from .services.mobile_intake.manager import get_intake_manager

                intake_manager = get_intake_manager()
                intake_manager.start()
                logger.info(
                    "Mobile intake watcher started at %s", intake_manager.watcher.intake_dir
                )
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to start mobile intake watcher")
        # M31: start the SMS outbox worker (background thread) when SMS is
        # enabled. Skipped under pytest so tests drain the queue deterministically
        # via SmsOutboxService.process_pending / SmsWorker.drain_once().
        if settings.SMS_ENABLED and "pytest" not in sys.modules:
            try:
                from .services.sms.manager import start_sms_worker

                start_sms_worker()
                logger.info("SMS outbox worker started")
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to start SMS outbox worker")
        logger.info("Application initialized")
        try:
            yield
        finally:
            if intake_manager is not None:
                try:
                    intake_manager.stop(timeout=5.0)
                except Exception:  # pragma: no cover - defensive
                    logger.exception("Error stopping mobile intake watcher")
            # M31: stop the SMS outbox worker cleanly.
            try:
                from .services.sms.manager import stop_sms_worker

                stop_sms_worker(timeout=5.0)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Error stopping SMS outbox worker")
            # Shut down the Edge runtime (camera workers) cleanly.
            try:
                from .edge import get_runtime

                get_runtime().shutdown(timeout=5.0)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Error shutting down edge runtime")
            close_db()
            logger.info("Shutdown complete")

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Privacy-first, offline-first Edge AI retail intelligence platform. "
            "AI observation is NOT business truth; inventory is mutated only "
            "through explicit domain operations."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Error handlers (maps domain/DB errors -> consistent HTTP error body).
    _register_handlers(app)

    # Health endpoints (legacy SQLite/SQLModel diagnostics — read-only).
    app.include_router(health_router, prefix="/api")

    # M22 system readiness/status (PostgreSQL + migrations + Re-ID + demo).
    app.include_router(system_router, prefix="/api")

    # Authentication (session-cookie, PostgreSQL-backed).
    app.include_router(auth.router, prefix="/api")

    # Business / data layer endpoints (PostgreSQL-backed).
    app.include_router(stores.router, prefix="/api")
    app.include_router(users.router, prefix="/api")
    app.include_router(cameras.router, prefix="/api")
    app.include_router(zones.router, prefix="/api")
    app.include_router(shelves.router, prefix="/api")
    app.include_router(products.router, prefix="/api")
    app.include_router(inventory.router, prefix="/api")
    app.include_router(customers.router, prefix="/api")
    app.include_router(sales.router, prefix="/api")
    app.include_router(bills.router, prefix="/api")
    app.include_router(notifications.router, prefix="/api")
    app.include_router(observations.router, prefix="/api")
    app.include_router(reconciliation.router, prefix="/api")
    app.include_router(intelligence.router, prefix="/api")
    app.include_router(alerts.router, prefix="/api")
    app.include_router(batch_intake.router, prefix="/api")
    app.include_router(journeys.router, prefix="/api")
    app.include_router(demo.router, prefix="/api")
    app.include_router(insights.router, prefix="/api")
    app.include_router(mobile_intake.router, prefix="/api")
    app.include_router(edge_router, prefix="/api")
    app.include_router(shelf_snapshots.router, prefix="/api")
    app.include_router(sms.router, prefix="/api")

    return app


app = create_app()
