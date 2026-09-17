"""M23 environment doctor.

A single read-only command that answers "is this machine ready to run
Storeye?" by checking, in order:

    1. Python runtime           (version, virtualenv)
    2. Node / npm               (needed to build/serve the frontend)
    3. Configuration            (validated Settings — M22)
    4. PostgreSQL reachability  (no-op with --no-db)
    5. Database schema/migrations
    6. Model assets             (delegates to app.deployment.model_check)
    7. Writable runtime dirs    (logs/, backend/data/)
    8. Re-ID / camera config    (configured + sane)
    9. Backend HTTP health      (only when --api-url is given)
   10. Frontend reachability    (only when --frontend-url is given)

Invocation (from ``backend/``):

    ./.venv/bin/python -m app.deployment.doctor [--json] [--no-db] [--fast]

Exit code 0 = no ERROR checks; 1 otherwise. The command NEVER mutates business
data and NEVER downloads anything.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from app.core.config import Settings, get_settings
from app.core.startup import assess_runtime

from .model_check import PROJECT_ROOT, run_model_check
from .report import Check, CheckReport, Status, render

VALID_CAMERA_TYPES = {"usb", "file", "rtsp"}
MIN_PYTHON = (3, 9)


def check_python() -> Check:
    version = sys.version_info
    if version < MIN_PYTHON:
        return Check(
            name="Python runtime",
            status=Status.ERROR,
            detail=f"Python {version.major}.{version.minor} < required {MIN_PYTHON[0]}.{MIN_PYTHON[1]}",
            hint="Install Python 3.9+ and recreate backend/.venv.",
        )
    venv = os.environ.get("VIRTUAL_ENV") or sys.prefix
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    detail = f"Python {version.major}.{version.minor}.{version.micro} ({venv})"
    if not in_venv:
        return Check(
            name="Python runtime",
            status=Status.WARN,
            detail=f"{detail} — not a virtualenv",
            hint="Run scripts with backend/.venv (./scripts/setup.sh creates it).",
        )
    return Check(name="Python runtime", status=Status.PASS, detail=detail)


def check_node() -> Check:
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        missing = ", ".join(n for n, p in (("node", node), ("npm", npm)) if not p)
        return Check(
            name="Node / npm",
            status=Status.WARN,
            detail=f"missing: {missing}",
            hint="Install Node.js 20+ to build/run the frontend "
            "(not required if you only use a prebuilt frontend).",
        )
    return Check(
        name="Node / npm",
        status=Status.PASS,
        detail=f"node={node}, npm={npm}",
    )


def check_configuration() -> tuple[Check, Optional[Settings]]:
    try:
        settings = get_settings()
    except Exception as exc:
        return (
            Check(
                name="Configuration (.env / env vars)",
                status=Status.ERROR,
                detail=str(exc),
                hint="Fix values in backend/.env (see .env.example).",
            ),
            None,
        )
    return (
        Check(
            name="Configuration (.env / env vars)",
            status=Status.PASS,
            detail=f"ENVIRONMENT={settings.ENVIRONMENT}, DB={'set' if settings.DATABASE_URL else 'unset'}",
        ),
        settings,
    )


def check_security_defaults(settings: Settings) -> Check:
    """Flag unsafe demo defaults left on in a production deployment."""
    if settings.ENVIRONMENT != "production":
        return Check(
            name="Security defaults",
            status=Status.SKIP,
            detail=f"ENVIRONMENT={settings.ENVIRONMENT} (demo defaults allowed)",
        )
    problems = []
    if settings.DEMO_MODE:
        problems.append("DEMO_MODE=true")
    if settings.DEMO_RESET_KEY == "storeye-demo-reset":
        problems.append("DEMO_RESET_KEY is the public default")
    if settings.DEBUG:
        problems.append("DEBUG=true")
    if problems:
        return Check(
            name="Security defaults",
            status=Status.WARN,
            detail="production with demo defaults: " + ", ".join(problems),
            hint="Set DEMO_MODE=false, a unique DEMO_RESET_KEY, DEBUG=false. "
            "Note: there is still no backend auth (documented limitation).",
        )
    return Check(name="Security defaults", status=Status.PASS, detail="production hardened")


def check_database(settings: Settings, *, probe: bool) -> list[Check]:
    checks: list[Check] = []
    if not probe:
        return [Check(name="PostgreSQL / migrations", status=Status.SKIP, detail="--no-db")]

    report = assess_runtime(probe_database=True, skip_in_tests=False)

    if not settings.DATABASE_URL:
        checks.append(
            Check(
                name="PostgreSQL connectivity",
                status=Status.ERROR,
                detail="DATABASE_URL is not set",
                hint="Set DATABASE_URL in backend/.env (see .env.example).",
            )
        )
        return checks

    if report.database_reachable:
        checks.append(
            Check(name="PostgreSQL connectivity", status=Status.PASS, detail="reachable")
        )
    else:
        msg = report.messages[-1] if report.messages else "unreachable"
        checks.append(
            Check(
                name="PostgreSQL connectivity",
                status=Status.ERROR,
                detail=msg,
                hint="Start PostgreSQL (./scripts/storeye start) and check DATABASE_URL.",
            )
        )
        return checks

    if report.migration_current:
        checks.append(
            Check(
                name="Database migrations",
                status=Status.PASS,
                detail=f"at head {report.migration_db_revision}",
            )
        )
    else:
        checks.append(
            Check(
                name="Database migrations",
                status=Status.ERROR,
                detail=(
                    f"db={report.migration_db_revision!r} head={report.migration_head!r}"
                ),
                hint="Run ./scripts/migrate.sh (alembic upgrade head).",
            )
        )
    return checks


def check_directories() -> Check:
    targets = [PROJECT_ROOT / "logs", get_settings().DATA_DIR]
    failures = []
    for target in targets:
        try:
            target.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target, delete=True):
                pass
        except Exception as exc:
            failures.append(f"{target}: {exc}")
    if failures:
        return Check(
            name="Writable directories",
            status=Status.ERROR,
            detail="; ".join(failures),
            hint="Ensure the deploy user owns logs/ and backend/data/.",
        )
    joined = ", ".join(str(t) for t in targets)
    return Check(name="Writable directories", status=Status.PASS, detail=joined)


def check_cameras(settings: Settings, *, probe: bool) -> Check:
    if not probe:
        return Check(name="Camera configuration", status=Status.SKIP, detail="--no-db")
    if not settings.DATABASE_URL:
        return Check(name="Camera configuration", status=Status.SKIP, detail="no DATABASE_URL")

    from sqlalchemy import select

    from app.db.session import dispose_engine, get_session, init_engine
    from app.models.camera import Camera

    init_engine(settings.DATABASE_URL)
    session = get_session()
    try:
        cameras = list(session.execute(select(Camera)).scalars().all())
    except Exception as exc:
        return Check(
            name="Camera configuration",
            status=Status.WARN,
            detail=f"could not read cameras: {exc}",
        )
    finally:
        session.close()
        dispose_engine()

    if not cameras:
        return Check(
            name="Camera configuration",
            status=Status.WARN,
            detail="no cameras configured (demos can run without live cameras)",
            hint="See docs/camera_setup.md.",
        )
    problems = []
    for cam in cameras:
        ctype = (cam.camera_type or "").lower()
        if ctype not in VALID_CAMERA_TYPES:
            problems.append(f"{cam.name}: invalid type {cam.camera_type!r}")
            continue
        cfg = cam.config or {}
        # Demo/generated cameras declare a semantic `kind` and intentionally
        # carry no source path; only flag real source cameras that are unusable.
        has_source = any(
            cfg.get(key)
            for key in ("path", "video_path", "file", "source", "url", "device_index")
        )
        if not has_source and not cfg.get("kind"):
            problems.append(f"{cam.name}: {ctype} camera without a source")
        if ctype == "rtsp" and not cfg.get("url"):
            problems.append(f"{cam.name}: rtsp camera without a url")
    if problems:
        return Check(
            name="Camera configuration",
            status=Status.WARN,
            detail=f"{len(cameras)} camera(s); " + "; ".join(problems),
            hint="See docs/camera_setup.md for camera_type/config schema.",
        )
    return Check(
        name="Camera configuration",
        status=Status.PASS,
        detail=f"{len(cameras)} camera(s) well-formed",
    )


def _http_probe(url: str, name: str) -> Check:
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310 (local URL)
            code = getattr(resp, "status", 200)
        if 200 <= int(code) < 400:
            return Check(name=name, status=Status.PASS, detail=f"{url} -> {code}")
        return Check(name=name, status=Status.WARN, detail=f"{url} -> {code}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return Check(
            name=name,
            status=Status.WARN,
            detail=f"{url} unreachable ({exc.__class__.__name__})",
        )


def run_doctor(
    *,
    settings: Optional[Settings] = None,
    probe_db: bool = True,
    deep: bool = True,
    api_url: Optional[str] = None,
    frontend_url: Optional[str] = None,
    models_root: Optional[Path] = None,
) -> CheckReport:
    """Build the full doctor report. Side-effect-free except optional HTTP probes."""
    report = CheckReport(title="Storeye environment doctor")

    report.extend([check_python(), check_node()])

    config_check, resolved = check_configuration()
    report.extend([config_check])
    if resolved is None:
        return report
    settings = settings or resolved

    report.extend(check_database(settings, probe=probe_db))
    report.extend(
        run_model_check(settings=settings, models_root=models_root, deep=deep).checks
    )
    report.extend([check_directories(), check_cameras(settings, probe=probe_db)])
    report.extend([check_security_defaults(settings)])

    if api_url:
        report.extend([_http_probe(api_url.rstrip("/") + "/api/health", "Backend HTTP health")])
    if frontend_url:
        report.extend([_http_probe(frontend_url, "Frontend reachability")])

    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="doctor",
        description="Read-only Storeye deployment readiness check.",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--no-db", action="store_true", help="skip PostgreSQL checks")
    parser.add_argument(
        "--fast", action="store_true", help="skip deep model import checks"
    )
    parser.add_argument("--api-url", default=None, help="probe backend /api/health at this URL")
    parser.add_argument(
        "--frontend-url", default=None, help="probe the frontend at this URL"
    )
    args = parser.parse_args(argv)

    report = run_doctor(
        probe_db=not args.no_db,
        deep=not args.fast,
        api_url=args.api_url,
        frontend_url=args.frontend_url,
    )
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, default=str))
    else:
        render(report)
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
