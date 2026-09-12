from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select, func

from ..core.database import get_session, Store, Camera, Product, VisualEvent
from ..core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    settings = get_settings()
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@router.get("/ready")
def readiness_check(session: Session = Depends(get_session)):
    settings = get_settings()
    db_exists = settings.DB_PATH.exists()
    store_count = session.exec(select(func.count(Store.id))).one()
    return {
        "ready": db_exists,
        "database": "ok" if db_exists else "missing",
        "stores": store_count,
    }


@router.get("/metrics")
def metrics(session: Session = Depends(get_session)):
    store_count = session.exec(select(func.count(Store.id))).one()
    camera_count = session.exec(select(func.count(Camera.id))).one()
    product_count = session.exec(select(func.count(Product.id))).one()
    event_count = session.exec(select(func.count(VisualEvent.id))).one()
    return {
        "stores": store_count,
        "cameras": camera_count,
        "products": product_count,
        "visual_events": event_count,
    }
