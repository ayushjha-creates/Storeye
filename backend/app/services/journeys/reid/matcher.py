"""Similarity math + confidence mapping for Re-ID association (M19).

The combined score fuses multiple independent signals so a single coincidental
feature cannot produce a match:

    combined = appearance_similarity * time_factor

where `time_factor` decays smoothly to a floor as the real-time gap between
the probe and the candidate approaches the configured maximum. The camera
transition graph gates candidates BEFORE scoring (an impossible transition is
excluded outright, not merely penalized) and the store scope is enforced by
the identity manager's key space.
"""

from __future__ import annotations

import math
from typing import Optional

from .config import ReIDConfig
from .models import Confidence, PersonEmbedding

_EPS = 1e-9
# Floor applied to the time factor so a strong appearance match is not
# completely wiped out by a few seconds of gap. 0.45 keeps time dominant
# enough to reject stale candidates while preserving stable re-appearance.
_TIME_FLOOR = 0.45


def cosine_similarity(a: PersonEmbedding, b: PersonEmbedding) -> float:
    """Cosine similarity between two embeddings (both are L2-normalized)."""
    if a is None or b is None:
        return 0.0
    if a.dimensions != b.dimensions or a.dimensions == 0:
        return 0.0
    return sum(x * y for x, y in zip(a.values, b.values))


def time_factor(elapsed_seconds: float, max_gap_seconds: float) -> float:
    """1.0 at t=0 declining linearly to _TIME_FLOOR at t=max_gap."""
    if max_gap_seconds <= 0:
        return _TIME_FLOOR
    if elapsed_seconds <= 0:
        return 1.0
    ratio = elapsed_seconds / max_gap_seconds
    if ratio >= 1.0:
        return _TIME_FLOOR
    return 1.0 - (1.0 - _TIME_FLOOR) * ratio


def combined_score(
    appearance: float,
    elapsed_seconds: float,
    config: ReIDConfig,
) -> float:
    """Fuse appearance similarity and recency into one [0,1] association score."""
    return appearance * time_factor(elapsed_seconds, config.max_time_gap_seconds)


def confidence_from_score(score: float, config: ReIDConfig) -> Confidence:
    """Map a combined score to an association confidence bucket."""
    if score >= config.high_confidence_score:
        return Confidence.HIGH
    if score >= config.similarity_threshold:
        return Confidence.MEDIUM
    if score > 0.0:
        return Confidence.LOW
    return Confidence.UNKNOWN


def _geq(a: float, b: float) -> bool:
    return a - _EPS >= b


def meets_threshold(score: float, config: ReIDConfig) -> bool:
    return _geq(score, config.similarity_threshold)