"""Demo Showcase Mode routes (M18).

`POST /api/demo/reset` wipes and re-seeds the deterministic demo store so a
presentation is always reproducible. The endpoint is guarded by a header key
(`X-Demo-Reset-Key`) — the browser has not been given this key; only a CLI or
an operator clipboard with the server-side `DEMO_RESET_KEY` can reset.
"""

from __future__ import annotations

import os
from typing import Dict

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from ..deps import get_db
from scripts.seed_demo import DEMO_STORE_NAME, reset_and_seed

router = APIRouter(prefix="/demo", tags=["demo"])

DEFAULT_RESET_KEY = "storeye-demo-reset"


@router.post("/reset")
def reset_demo(
    db: Session = Depends(get_db),
    x_demo_reset_key: str = Header(default="", alias="X-Demo-Reset-Key"),
) -> Dict[str, object]:
    expected = os.environ.get("DEMO_RESET_KEY", DEFAULT_RESET_KEY)
    if not expected or x_demo_reset_key != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing X-Demo-Reset-Key header.",
        )
    counts = reset_and_seed(db)
    return {
        "ok": True,
        "store": DEMO_STORE_NAME,
        "reseeded": counts,
        "note": "Demo data is synthetic and clearly labelled demo within the UI.",
    }