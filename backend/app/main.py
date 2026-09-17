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
        logger.info("Application initialized")
        try:
            yield
        finally:
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
    app.include_router(edge_router, prefix="/api")

    return app


app = create_app()
