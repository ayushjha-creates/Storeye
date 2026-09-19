"""Explicit camera health states (M27 Phase 17-21).

The frontend previously had to *derive* a camera's health from `running` +
`connection_ok` + `error`. That derivation is now a first-class, single source
of truth so every surface (grid, detail, API consumers) reports the SAME state.

States are deliberately narrow and honest — there is no "healthy" claim beyond
what the runtime can observe:

    RUNNING    runtime is processing frames (running + connection_ok)
    DEGRADED   running but no frame has arrived for a while (stalled source)
    STARTING   thread started but no successful frame yet (running only)
    ERROR      the worker recorded a capture/source error
    STOPPED    not running (never started, or stopped by the operator)
    DISABLED   the DB camera is inactive and therefore never started
"""

from __future__ import annotations

HEALTH_RUNNING = "RUNNING"
HEALTH_DEGRADED = "DEGRADED"
HEALTH_STARTING = "STARTING"
HEALTH_ERROR = "ERROR"
HEALTH_STOPPED = "STOPPED"
HEALTH_DISABLED = "DISABLED"

ALL_HEALTH_STATES = (
    HEALTH_RUNNING,
    HEALTH_DEGRADED,
    HEALTH_STARTING,
    HEALTH_ERROR,
    HEALTH_STOPPED,
    HEALTH_DISABLED,
)


def camera_health(
    *,
    running: bool,
    connection_ok: bool,
    error: str | None,
    active: bool = True,
    stalled: bool = False,
) -> str:
    """Derive the single canonical health state for one camera.

    `stalled` is only meaningful while connected+running: it means no frame has
    arrived for longer than the caller's staleness threshold. Callers that
    cannot measure it leave the default (False) rather than guessing.
    """
    if error:
        return HEALTH_ERROR
    if running and connection_ok and stalled:
        return HEALTH_DEGRADED
    if running and connection_ok:
        return HEALTH_RUNNING
    if running:
        return HEALTH_STARTING
    if not active:
        return HEALTH_DISABLED
    return HEALTH_STOPPED
