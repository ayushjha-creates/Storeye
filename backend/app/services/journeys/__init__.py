"""Anonymous customer journey analytics (M19).

Two layers live in this package:

* `reid` — a privacy-preserving, modular Re-ID subsystem that turns per-camera
  ByteTrack track ids into anonymous *Global Person IDs* using appearance
  similarity + time gap + camera transition graph + store scope. Embeddings
  are computed in-memory and NEVER persisted.
* `journey_service` — the PostgreSQL persistence/query layer for global person
  sessions, track associations, zone visits and camera transitions.

Design point: single-camera tracking (ByteTrack) is UNAFFECTED by Re-ID. Local
track ids stay camera-scoped and are always preserved. Re-ID only adds an
OPTIONAL anonymous global label on top; if Re-ID is disabled or unavailable,
tracking and observations continue exactly as before.
"""

from .reid.config import ReIDConfig
from .reid.providers import (
    PersonReIDModel,
    StubReIDProvider,
    TorchReIDProvider,
    OpenVINOReIDProvider,
    build_reid_provider,
)
from .reid.models import (
    Confidence,
    PersonEmbedding,
    PersonSighting,
    ReidMatch,
)
from .reid.matcher import cosine_similarity, confidence_from_score
from .reid.association import GlobalIdentityManager
from .journey_service import JourneyService

__all__ = [
    "ReIDConfig",
    "PersonReIDModel",
    "StubReIDProvider",
    "TorchReIDProvider",
    "OpenVINOReIDProvider",
    "build_reid_provider",
    "Confidence",
    "PersonEmbedding",
    "PersonSighting",
    "ReidMatch",
    "cosine_similarity",
    "confidence_from_score",
    "GlobalIdentityManager",
    "JourneyService",
]