"""Re-ID configuration — every magic number lives here (M19).

All thresholds are configurable at runtime from process env vars (documented
in `.env.example`) so operators can tune association behaviour without code
changes. Nothing here loads a model or touches the database.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReIDConfig:
    """Association thresholds + provider knobs for anonymous Re-ID.

    Defaults are tuned to be CONSERVATIVE: a missed match (a second anonymous
    global id for the same person) is strictly preferable to a false merge of
    two different people. False merges corrupt journey analytics and are
    avoided first.
    """

    # Master switch. When False the Re-ID subsystem is fully disabled and the
    # edge pipeline behaves exactly as M13-M18 (local track ids only).
    enabled: bool = True

    # Provider name: "stub" | "torch" | "openvino" (see providers.py).
    provider: str = "torch"

    # Minimum COMBINED association score required to accept a match
    # (appearance similarity * time factor). Higher => fewer, safer merges.
    similarity_threshold: float = 0.72

    # Score at/above which a match is reported as HIGH confidence.
    high_confidence_score: float = 0.86

    # Maximum real-time gap (seconds) between the candidate identity's last
    # sighting and the probe before the candidate is excluded.
    max_time_gap_seconds: float = 120.0

    # An identity with no sighting within this window is expired/forgotten.
    # A re-sighting after expiry always starts a NEW global session.
    global_timeout_seconds: float = 1800.0

    # How often (seconds) an already-stable (camera, track) is re-embedded.
    # New tracks embed immediately; stable tracks reuse their embedding and
    # only refresh periodically (never per-frame).
    refresh_interval_seconds: float = 10.0

    def validate(self) -> None:
        for name in ("similarity_threshold", "high_confidence_score"):
            v = getattr(self, name)
            if not 0.0 < v <= 1.0:
                raise ValueError(f"{name} must be in (0, 1], got {v!r}")
        if self.max_time_gap_seconds < 0:
            raise ValueError("max_time_gap_seconds must be >= 0")
        if self.global_timeout_seconds <= 0:
            raise ValueError("global_timeout_seconds must be > 0")
        if self.refresh_interval_seconds < 0:
            raise ValueError("refresh_interval_seconds must be >= 0")

    @classmethod
    def from_settings(cls, settings) -> "ReIDConfig":
        """Build from Settings (env-driven) without forcing model imports."""
        return cls(
            enabled=bool(settings.REID_ENABLED),
            provider=str(settings.REID_PROVIDER),
            similarity_threshold=float(settings.REID_SIMILARITY_THRESHOLD),
            high_confidence_score=float(settings.REID_HIGH_CONFIDENCE_SCORE),
            max_time_gap_seconds=float(settings.REID_MAX_TIME_GAP_SECONDS),
            global_timeout_seconds=float(settings.GLOBAL_PERSON_TIMEOUT_SECONDS),
            refresh_interval_seconds=float(settings.REID_UPDATE_INTERVAL_SECONDS),
        )