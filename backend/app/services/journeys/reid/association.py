"""GlobalIdentityManager — in-memory association of local tracks to anonymous
Global Person IDs (M19).

This is the LIVE association engine used by the edge runtime. It is
deliberately stateless across restarts: all *persistent* facts (sessions,
associations, transitions, zone visits) are stored by the JourneyService in
PostgreSQL, which remains authoritative. The manager only holds the ephemeral
embedding index needed to answer "is this the same person I saw on another
camera?"

Thread-safety: the manager may be shared by several camera worker threads, so
every public mutation runs under an RLock.

Rules enforced here (false merges are worse than missed matches):
  1. Store isolation — identities are keyed by (store_id, global_id) and
     candidates from another store never match. (test case E)
  2. Time gap — a probe older than `max_time_gap_seconds` after the candidate
     is excluded. (D)
  3. Camera transition graph — a probe from a camera the candidate's last
     camera cannot legally reach is excluded. (C)
  4. Identity expiration — beyond `global_timeout_seconds` the identity is
     forgotten; a later re-sighting starts a NEW global session. (F)
  5. Same-camera protections — the same camera/track keeps its global id; the
     same numeric track id on DIFFERENT cameras is a different person. (K)
  6. Same-camera re-acquisition — a re-created local track on the same camera
     may reconnect to its prior global id when it is the ONLY person on that
     camera, the absence is short (`same_camera_reacquisition_*`) and the
     appearance is a strong match (`same_camera_similarity_threshold`).
     Concurrent same-camera tracks are still never merged.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from .config import ReIDConfig
from .models import Confidence, PersonEmbedding, PersonSighting, ReidMatch, _IdentityRecord
from .matcher import combined_score, confidence_from_score, cosine_similarity, meets_threshold
from .providers import PersonReIDModel, build_reid_provider

logger = logging.getLogger("storeye.journeys.reid.association")

TrackKey = Tuple[str, int]  # (camera_id, track_id)


class GlobalIdentityManager:
    """Thread-safe live association index for one store/scene."""

    def __init__(
        self,
        config: Optional[ReIDConfig] = None,
        provider: Optional[PersonReIDModel] = None,
        *,
        store_id: Optional[str] = None,
    ) -> None:
        from app.core.config import get_settings

        self.config = config or ReIDConfig.from_settings(get_settings())
        self.store_id = store_id
        self._provider = provider
        self._provider_factory = lambda: provider
        self._identities: Dict[Tuple[str, str], _IdentityRecord] = {}
        # local (camera, track) -> the global id currently assigned.
        self._track_map: Dict[TrackKey, str] = {}
        # camera transition graph: from_camera -> set of allowed next cameras.
        # Empty dict == default-open (any transition allowed).
        self._transitions: Dict[str, set] = {}
        self._lock = threading.RLock()
        self._pruned_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Public configuration
    # ------------------------------------------------------------------
    def register_camera(self, camera_id: str, next_cameras: Optional[Iterable[str]] = None) -> None:
        """Register a camera + the ids it can legally transition to."""
        with self._lock:
            if next_cameras is None:
                self._transitions.pop(camera_id, None)
            else:
                cleaned = {str(c) for c in next_cameras if str(c) and str(c) != str(camera_id)}
                self._transitions[str(camera_id)] = cleaned

    def set_provider(self, provider: Optional[PersonReIDModel]) -> None:
        with self._lock:
            self._provider = provider

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------
    @property
    def provider(self) -> Optional[PersonReIDModel]:
        return self._provider

    def reid_available(self) -> bool:
        """True when Re-ID can actually run (enabled + provider usable)."""
        if not self.config.enabled:
            return False
        if self._provider is None:
            return False
        try:
            return self._provider.available()
        except Exception:  # pragma: no cover - defensive
            return False

    def transition_graph(self) -> Dict[str, List[str]]:
        with self._lock:
            return {k: sorted(v) for k, v in self._transitions.items()}

    # ------------------------------------------------------------------
    # Association
    # ------------------------------------------------------------------
    def associate(self, sighting: PersonSighting) -> Optional[ReidMatch]:
        """Associate a sighting to a Global Person ID.

        Returns None when Re-ID is disabled/unavailable (single-camera
        tracking continues untouched). Otherwise always returns a match —
        either the best existing identity or a brand-new global session
        (created=True, confidence=UNKNOWN).
        """
        if not self.reid_available():
            return None
        if self.store_id is not None and sighting.store_id != self.store_id:
            raise ValueError(
                f"manager is scoped to store {self.store_id!r} but sighting is from "
                f"{sighting.store_id!r} — cross-store association is forbidden"
            )

        with self._lock:
            now = sighting.timestamp
            self._prune(now)

            key = (sighting.camera_id, sighting.track_id)
            existing = self._track_map.get(key)
            if existing is not None and (sighting.store_id, existing) in self._identities:
                rec = self._identities[(sighting.store_id, existing)]
                self._maybe_refresh(rec, sighting, now)
                return ReidMatch(existing, rec.confidence, 1.0, created=False)

            best = self._best_candidate(sighting, now)
            if best is not None:
                rec = self._identities[best]
                self._absorb(rec, sighting, now)
                self._track_map[key] = rec.global_person_id
                score = self._score_for(rec, sighting, now, best)
                return ReidMatch(rec.global_person_id, rec.confidence, score, created=False)

            gid = str(uuid.uuid4())
            self._identities[(sighting.store_id, gid)] = _IdentityRecord(
                global_person_id=gid,
                store_id=sighting.store_id,
                embedding=sighting.embedding,
                first_seen_at=now,
                last_seen_at=now,
                last_camera_id=sighting.camera_id,
                confidence=Confidence.UNKNOWN,
                match_count=0,
                used_track_ids={key},
            )
            self._track_map[key] = gid
            return ReidMatch(gid, Confidence.UNKNOWN, 1.0, created=True)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------
    def resolve(self, camera_id: str, track_id: int) -> Optional[str]:
        """Global id currently assigned to a local (camera, track)."""
        with self._lock:
            return self._track_map.get((camera_id, track_id))

    def resolution_confidence(self, camera_id: str, track_id: int) -> Optional[Confidence]:
        with self._lock:
            gid = self._track_map.get((camera_id, track_id))
            if gid is None:
                return None
            for (sid, _gid), rec in self._identities.items():
                if _gid == gid:
                    return rec.confidence
            return None

    def active_identity_count(self) -> int:
        with self._lock:
            return len(self._identities)

    def expire_all(self) -> int:
        """Forget every identity (used by tests/shutdown). Returns count."""
        with self._lock:
            n = len(self._identities)
            self._identities.clear()
            self._track_map.clear()
            return n

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.config.global_timeout_seconds)
        dead = [
            key
            for key, rec in self._identities.items()
            if rec.last_seen_at < cutoff
        ]
        for key in dead:
            rec = self._identities.pop(key)
            self._track_map = {
                k: v for k, v in self._track_map.items() if v != rec.global_person_id
            }
        if dead:
            logger.info("Pruned %s expired Re-ID identities", len(dead))

    def _maybe_refresh(self, rec: _IdentityRecord, sighting: PersonSighting, now: datetime) -> None:
        rec.last_seen_at = now
        rec.last_camera_id = sighting.camera_id
        rec.used_track_ids.add((sighting.camera_id, sighting.track_id))
        if sighting.embedding is not None and sighting.embedding.values:
            if rec.embedding is None or not rec.embedding.values:
                rec.embedding = sighting.embedding
            else:
                # Refresh on the configured cadence; stable tracks reuse the
                # embedding in between (no per-frame inference).
                last_emit = getattr(rec, "_last_embed_at", None)
                if last_emit is None or (now - last_emit).total_seconds() >= self.config.refresh_interval_seconds:
                    rec.embedding = sighting.embedding
                    rec._last_embed_at = now

    def _absorb(self, rec: _IdentityRecord, sighting: PersonSighting, now: datetime) -> None:
        """Accept a match: update recency, camera, confidence, embed."""
        gap = max(0.0, (now - rec.last_seen_at).total_seconds())
        appearance = cosine_similarity(sighting.embedding, rec.embedding) if sighting.embedding else 0.0
        score = combined_score(appearance, gap, self.config)
        rec.confidence = confidence_from_score(score, self.config)
        rec.last_seen_at = now
        rec.last_camera_id = sighting.camera_id
        rec.match_count += 1
        rec.used_track_ids.add((sighting.camera_id, sighting.track_id))
        if sighting.embedding is not None and sighting.embedding.values:
            rec.embedding = sighting.embedding

    def _score_for(self, rec, sighting, now, key) -> float:
        gap = max(0.0, (now - rec.last_seen_at).total_seconds())
        appearance = cosine_similarity(sighting.embedding, rec.embedding) if sighting.embedding else 0.0
        return combined_score(appearance, gap, self.config)

    def _best_candidate(self, sighting: PersonSighting, now: datetime) -> Optional[Tuple[str, str]]:
        """Return (store_id, global_person_id) of the best acceptable match.

        Returns None when no candidate clears the acceptance threshold.
        """
        if sighting.embedding is None or not sighting.embedding.values:
            return None
        best: Optional[Tuple[str, str]] = None
        best_score = 0.0
        for (sid, gid), rec in self._identities.items():
            if sid != sighting.store_id:
                continue  # store isolation (E)
            gap = max(0.0, (now - rec.last_seen_at).total_seconds())
            appearance = cosine_similarity(sighting.embedding, rec.embedding)
            if rec.last_camera_id == sighting.camera_id:
                # Same-camera re-acquisition (M27). Never merge concurrent
                # tracks; only reconnect a genuinely absent, lone track.
                if not self._same_camera_reacquisition_ok(
                    sighting, rec, now, gap, appearance
                ):
                    continue
            else:
                if rec.last_seen_at + timedelta(seconds=self.config.max_time_gap_seconds) < now:
                    continue  # time gap exceeded (D)
                if not self._transition_allowed(rec.last_camera_id, sighting.camera_id):
                    continue  # impossible camera transition (C)
            score = combined_score(appearance, gap, self.config)
            if not meets_threshold(score, self.config):
                continue
            if score > best_score:
                best = (sid, gid)
                best_score = score
        return best

    def _same_camera_reacquisition_ok(
        self,
        sighting: PersonSighting,
        rec: _IdentityRecord,
        now: datetime,
        gap: float,
        appearance: float,
    ) -> bool:
        """Gate a same-camera reconnect (never a concurrent-track merge).

        Returns True only when the candidate identity has been ABSENT from this
        camera for a short window, no other local track is currently active on
        that camera, and the appearance match is strong.
        """
        if not self.config.same_camera_reacquisition:
            return False
        if gap < self.config.same_camera_reacquisition_seconds:
            return False  # a concurrent track is still refreshing this identity
        if gap > self.config.same_camera_reacquisition_max_gap_seconds:
            return False  # genuinely left; start a new session
        if appearance < self.config.same_camera_similarity_threshold:
            return False  # no corroborating transition evidence -> demand a strong match
        if self._has_active_same_camera_identity(sighting, now):
            return False  # someone else is visible on this camera right now
        return True

    def _has_active_same_camera_identity(
        self, sighting: PersonSighting, now: datetime
    ) -> bool:
        """True when another track on this camera is currently being refreshed."""
        window = self.config.same_camera_reacquisition_seconds
        for (cam, track_id), gid in self._track_map.items():
            if cam != sighting.camera_id or track_id == sighting.track_id:
                continue
            rec = self._identities.get((sighting.store_id, gid))
            if rec is not None and (now - rec.last_seen_at).total_seconds() <= window:
                return True
        return False

    def _transition_allowed(self, from_camera: str, to_camera: str) -> bool:
        if from_camera == to_camera:
            return True
        allowed = self._transitions.get(from_camera)
        if allowed is None:
            return True  # default-open: camera not configured => any transition
        return to_camera in allowed