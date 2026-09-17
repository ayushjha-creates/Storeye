"""Core types for the anonymous Re-ID subsystem (M19).

These are pure, framework-free types shared by the matcher, the identity
manager and the embedding providers. No database, no torch, no openvino —
tests can import this module without importing heavy dependencies.

PRIVACY
-------
A `PersonEmbedding` exists only in memory, for the lifetime of an edge
runtime session. Embeddings are NEVER stored in PostgreSQL (proven by test
case N) and NEVER attached to observations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Tuple


class Confidence(str, Enum):
    """ID-association confidence.

    * HIGH   — appearance + time + transition all strongly agree.
    * MEDIUM — above the configurable acceptance threshold.
    * LOW    — weak candidate (below acceptance) reported for diagnostics.
    * UNKNOWN— a brand-new global session created from a single camera track
               (no cross-camera proof yet).
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class PersonEmbedding:
    """A real-valued, L2-normalized appearance embedding (in-memory only)."""

    values: Tuple[float, ...]
    provider: str = "stub"
    dimensions: int = 0

    def __init__(self, values: List[float], *, provider: str = "stub"):
        dims = len(values)
        object.__setattr__(self, "values", tuple(float(v) for v in values))
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "dimensions", dims)


@dataclass(frozen=True)
class PersonSighting:
    """One reidentification attempt for a single (camera, track) at a moment.

    `timestamp` is the (tz-aware UTC) frame time — association is
    timestamp-based, never frame-number based.
    """

    store_id: str
    camera_id: str
    track_id: int
    timestamp: datetime
    embedding: Optional[PersonEmbedding] = None
    # Normalized [0..1] foot-point (bottom-center) of the person bbox, used by
    # zone analytics. Pure metadata; never identity.
    foot_point: Optional[Tuple[float, float]] = None
    bbox_xyxy: Optional[Tuple[float, float, float, float]] = None


@dataclass(frozen=True)
class ReidMatch:
    """Result of associating a sighting to a Global Person ID."""

    global_person_id: str
    confidence: Confidence
    score: float
    created: bool

    def to_dict(self) -> dict:
        return {
            "global_person_id": self.global_person_id,
            "confidence": self.confidence.value,
            "score": round(self.score, 4),
            "created": self.created,
        }


@dataclass
class _IdentityRecord:
    """Live in-memory identity entry (lifecycle = one edge runtime session)."""

    global_person_id: str
    store_id: str
    embedding: Optional[PersonEmbedding]
    first_seen_at: datetime
    last_seen_at: datetime
    last_camera_id: str
    confidence: Confidence
    match_count: int = 0
    used_track_ids: set = field(default_factory=set)