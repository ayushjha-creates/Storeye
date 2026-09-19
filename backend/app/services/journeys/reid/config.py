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

    # -- Same-camera re-acquisition (M27 Phase 2-5) ---------------------
    # ByteTrack inevitably drops and re-creates local track ids for one
    # physical person (brief occlusion, motion blur, detector flicker). The
    # old rule refused ALL same-camera matches, so every re-created track
    # became a brand-new global id AND a brand-new journey. We now permit a
    # NARROW reconnect: a lost local track may re-attach to its global id
    # only when it is the only person currently on that camera, the absence
    # is short, and appearance is a strong match. Concurrent same-camera
    # tracks are still never merged (false merges remain unacceptable).
    same_camera_reacquisition: bool = True
    # Minimum absence (s) before reconnect is considered. Below this the
    # candidate is treated as a concurrent, still-visible track.
    same_camera_reacquisition_seconds: float = 2.0
    # Maximum absence (s) before a same-camera reconnect is refused (the
    # person has genuinely left; a later return within this window still
    # reconnects, beyond it starts a new session per rule F).
    same_camera_reacquisition_max_gap_seconds: float = 15.0
    # Stricter appearance bar for same-camera reconnect than cross-camera,
    # because there is no camera-transition evidence to corroborate it.
    same_camera_similarity_threshold: float = 0.85

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
        if self.same_camera_reacquisition_seconds < 0:
            raise ValueError("same_camera_reacquisition_seconds must be >= 0")
        if (
            self.same_camera_reacquisition_max_gap_seconds
            < self.same_camera_reacquisition_seconds
        ):
            raise ValueError(
                "same_camera_reacquisition_max_gap_seconds must be >= "
                "same_camera_reacquisition_seconds"
            )
        if not 0.0 < self.same_camera_similarity_threshold <= 1.0:
            raise ValueError(
                "same_camera_similarity_threshold must be in (0, 1], got "
                f"{self.same_camera_similarity_threshold!r}"
            )

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
            same_camera_reacquisition=bool(
                getattr(settings, "REID_SAME_CAMERA_REACQUISITION", True)
            ),
            same_camera_reacquisition_seconds=float(
                getattr(settings, "REID_SAME_CAMERA_REACQUISITION_SECONDS", 2.0)
            ),
            same_camera_reacquisition_max_gap_seconds=float(
                getattr(settings, "REID_SAME_CAMERA_REACQUISITION_MAX_GAP_SECONDS", 15.0)
            ),
            same_camera_similarity_threshold=float(
                getattr(settings, "REID_SAME_CAMERA_SIMILARITY_THRESHOLD", 0.85)
            ),
        )