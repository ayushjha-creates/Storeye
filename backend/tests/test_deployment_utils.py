"""M23 deployment-utility tests (no database).

Covers the shared PASS/WARN/ERROR report model, the model-asset validator and
the environment doctor's config/security/model logic. These are pure unit tests
(marked ``no_db``) and must never touch PostgreSQL or download anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings, get_settings
from app.deployment import doctor as doctor_mod
from app.deployment.model_check import (
    MIN_MODEL_BYTES,
    check_barcode,
    check_person_detector,
    check_reid,
    check_shelf_model,
    run_model_check,
)
from app.deployment.report import Check, CheckReport, Status

pytestmark = pytest.mark.no_db


def _write(path: Path, size: int = MIN_MODEL_BYTES * 2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"0" * size)
    return path


# ---------------------------------------------------------------------------
# report.py
# ---------------------------------------------------------------------------

def test_check_as_dict_roundtrip():
    check = Check(name="n", status=Status.WARN, detail="d", hint="h")
    assert check.as_dict() == {
        "name": "n",
        "status": "WARN",
        "detail": "d",
        "hint": "h",
    }


def test_report_overall_ready_with_only_passes():
    report = CheckReport(title="t")
    report.add("a", Status.PASS, "ok")
    report.add("b", Status.SKIP, "skipped")
    assert report.ok is True
    assert report.overall == "READY"
    assert report.exit_code == 0


def test_report_overall_degraded_with_warning():
    report = CheckReport(title="t")
    report.add("a", Status.PASS)
    report.add("b", Status.WARN, "meh")
    assert report.ok is True
    assert report.overall == "DEGRADED"
    assert report.exit_code == 0


def test_report_overall_not_ready_with_error():
    report = CheckReport(title="t")
    report.add("a", Status.ERROR, "boom")
    assert report.ok is False
    assert report.overall == "NOT READY"
    assert report.exit_code == 1
    assert report.as_dict()["counts"]["error"] == 1


# ---------------------------------------------------------------------------
# model_check.py
# ---------------------------------------------------------------------------

def test_person_detector_missing_is_error(tmp_path: Path):
    check = check_person_detector(tmp_path)
    assert check.status is Status.ERROR


def test_person_detector_present_is_pass(tmp_path: Path):
    _write(tmp_path / "models/yolo/yolo11n.pt")
    assert check_person_detector(tmp_path).status is Status.PASS


def test_tiny_model_file_is_rejected(tmp_path: Path):
    # A Git-LFS pointer / truncated download is smaller than the floor.
    _write(tmp_path / "models/shelf/shelf_model.pt", size=100)
    check = check_shelf_model(tmp_path)
    assert check.status is Status.ERROR
    assert "small" in check.detail


def test_check_reid_stub_is_pass():
    settings = Settings(REID_ENABLED=True, REID_PROVIDER="stub")
    assert check_reid(settings, deep=False).status is Status.PASS


def test_check_reid_disabled_is_skip():
    settings = Settings(REID_ENABLED=False, REID_PROVIDER="torch")
    assert check_reid(settings, deep=False).status is Status.SKIP


def test_check_reid_openvino_missing_weights_is_error():
    settings = Settings(REID_ENABLED=True, REID_PROVIDER="openvino")
    check = check_reid(settings, deep=False)
    assert check.status is Status.ERROR
    assert "model files missing" in check.detail


def test_check_barcode_fast_is_unverified_warning():
    check = check_barcode(deep=False)
    assert check.status in (Status.WARN, Status.PASS)


def test_run_model_check_missing_assets(tmp_path: Path):
    report = run_model_check(
        settings=Settings(REID_ENABLED=False),
        models_root=tmp_path,
        deep=False,
    )
    assert report.ok is False
    names = {c.name for c in report.errors}
    assert "AI person detector (YOLO11n)" in names
    assert "AI shelf/product model" in names


def test_run_model_check_with_staged_assets(tmp_path: Path):
    _write(tmp_path / "models/yolo/yolo11n.pt")
    _write(tmp_path / "models/shelf/shelf_model.pt")
    report = run_model_check(
        settings=Settings(REID_ENABLED=False),
        models_root=tmp_path,
        deep=False,
    )
    assert report.ok is True
    assert report.overall in ("READY", "DEGRADED")


# ---------------------------------------------------------------------------
# doctor.py
# ---------------------------------------------------------------------------

def test_check_configuration_ok():
    check, settings = doctor_mod.check_configuration()
    assert check.status is Status.PASS
    assert settings is not None


def test_doctor_invalid_configuration_is_error(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "not-a-real-env")
    get_settings.cache_clear()
    report = doctor_mod.run_doctor(probe_db=False, deep=False)
    assert report.ok is False
    assert any(c.name.startswith("Configuration") for c in report.errors)


def test_doctor_no_db_with_staged_models(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("REID_ENABLED", "false")
    get_settings.cache_clear()
    _write(tmp_path / "models/yolo/yolo11n.pt")
    _write(tmp_path / "models/shelf/shelf_model.pt")

    report = doctor_mod.run_doctor(
        probe_db=False, deep=False, models_root=tmp_path
    )
    assert report.ok is True
    assert any(c.name == "PostgreSQL / migrations" for c in report.checks)
    assert any(c.name.startswith("AI person detector") for c in report.checks)


def test_security_defaults_warn_in_production():
    settings = Settings(
        ENVIRONMENT="production",
        DEMO_MODE=True,
        DEMO_RESET_KEY="storeye-demo-reset",
        DEBUG=True,
    )
    check = doctor_mod.check_security_defaults(settings)
    assert check.status is Status.WARN


def test_security_defaults_pass_when_hardened():
    settings = Settings(
        ENVIRONMENT="production",
        DEMO_MODE=False,
        DEMO_RESET_KEY="unique-edge-key",
        DEBUG=False,
    )
    assert doctor_mod.check_security_defaults(settings).status is Status.PASS


def test_security_defaults_skip_in_development():
    assert (
        doctor_mod.check_security_defaults(Settings(ENVIRONMENT="development")).status
        is Status.SKIP
    )
