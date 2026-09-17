"""M23 model-asset validation.

Verifies that every local AI asset Storeye needs is present and loadable
BEFORE the app serves traffic. This command NEVER downloads anything: it only
reports what exists on disk and, when asked (``--deep``), whether the runtime
libraries can import the model.

Repo layout note
----------------
The M23 spec suggested ``python -m backend.services.model_check``. This
repository uses the ``app.*`` package with ``scripts.*`` entry points, so the
check lives here and is invoked from ``backend/`` as:

    ./.venv/bin/python -m app.deployment.model_check [--json] [--deep]

Exit code 0 = no ERROR checks; 1 = at least one missing/broken asset.

Assets (see docs/model_assets.md):
* Person detector      models/yolo/yolo11n.pt          (Ultralytics YOLO11n)
* Shelf/product model  models/shelf/shelf_model.pt
* Re-ID weights        torch cache or models/reid/*    (per REID_PROVIDER)
* OCR models           PaddleOCR official models       (downloaded on BOOTSTRAP)
* Barcode backend      system libzbar via pyzbar
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Optional

from app.core.config import Settings, get_settings

from .report import Check, CheckReport, Status, render

# backend/app/deployment/model_check.py -> repo root is parents[3]
PROJECT_ROOT = Path(__file__).resolve().parents[3]

PERSON_DETECTOR_REL = Path("models/yolo/yolo11n.pt")
SHELF_MODEL_REL = Path("models/shelf/shelf_model.pt")

# A model file smaller than this is almost certainly a Git-LFS pointer or an
# interrupted download, never a real network.
MIN_MODEL_BYTES = 64 * 1024


def _file_check(name: str, path: Path, *, min_bytes: int = MIN_MODEL_BYTES) -> Check:
    if not path.exists():
        return Check(
            name=name,
            status=Status.ERROR,
            detail=f"missing: {path}",
            hint="Re-run `./scripts/setup.sh` (with internet) or restore the file; "
            "see docs/model_assets.md.",
        )
    if not path.is_file():
        return Check(name=name, status=Status.ERROR, detail=f"not a file: {path}")
    try:
        size = path.stat().st_size
    except OSError as exc:  # pragma: no cover - defensive
        return Check(name=name, status=Status.ERROR, detail=f"unreadable: {exc}")
    if size < min_bytes:
        return Check(
            name=name,
            status=Status.ERROR,
            detail=f"suspiciously small ({size} bytes): {path}",
            hint="This may be a Git-LFS pointer or a truncated download.",
        )
    return Check(name=name, status=Status.PASS, detail=f"{path} ({size // 1024} KiB)")


def check_person_detector(models_root: Path) -> Check:
    return _file_check("AI person detector (YOLO11n)", models_root / PERSON_DETECTOR_REL)


def check_shelf_model(models_root: Path) -> Check:
    return _file_check("AI shelf/product model", models_root / SHELF_MODEL_REL)


def check_reid(settings: Settings, *, deep: bool = True) -> Check:
    """Validate the configured Re-ID provider's local weights/deps."""
    provider_name = (settings.REID_PROVIDER or "").strip().lower()

    if not settings.REID_ENABLED:
        return Check(
            name="AI Re-ID provider",
            status=Status.SKIP,
            detail="REID_ENABLED=false (anonymous Re-ID disabled)",
        )

    if provider_name == "stub":
        return Check(
            name="AI Re-ID provider",
            status=Status.PASS,
            detail="stub provider (tests/demo; no weights required)",
        )

    if provider_name == "torch":
        from app.services.journeys.reid.providers import _default_torch_weights

        weights = _default_torch_weights()
        if not weights.is_file():
            return Check(
                name="AI Re-ID provider (torch)",
                status=Status.ERROR,
                detail=f"weights not found: {weights}",
                hint="Fetch once while online (or set REID_TORCH_WEIGHTS_PATH): "
                "python -c \"import torch; torch.hub.load_state_dict_from_url("
                "'https://download.pytorch.org/models/resnet18-f37072fd.pth', progress=True)\"",
            )
        if deep and not (
            _module_available("torch") and _module_available("torchvision")
        ):
            return Check(
                name="AI Re-ID provider (torch)",
                status=Status.ERROR,
                detail="torch/torchvision not importable",
                hint="pip install -r backend/requirements.txt",
            )
        return Check(
            name="AI Re-ID provider (torch)",
            status=Status.PASS,
            detail=f"weights: {weights}",
        )

    if provider_name == "openvino":
        from app.services.journeys.reid.providers import _default_ov_model

        model_path = _default_ov_model()
        binary = model_path.with_suffix(".bin")
        if not (model_path.is_file() and binary.is_file()):
            return Check(
                name="AI Re-ID provider (openvino)",
                status=Status.ERROR,
                detail=f"model files missing: {model_path} (+ .bin)",
                hint="Optional provider: stage person-reidentification-retail-0287 "
                ".xml/.bin under models/reid/ and set REID_OV_MODEL_PATH.",
            )
        if not _module_available("openvino"):
            return Check(
                name="AI Re-ID provider (openvino)",
                status=Status.ERROR,
                detail="openvino package not installed",
                hint="pip install openvino (optional dependency).",
            )
        return Check(
            name="AI Re-ID provider (openvino)",
            status=Status.PASS,
            detail=str(model_path),
        )

    return Check(
        name="AI Re-ID provider",
        status=Status.ERROR,
        detail=f"unknown REID_PROVIDER {provider_name!r}",
    )


def check_paddleocr(*, deep: bool = True, home: Optional[Path] = None) -> Check:
    """PaddleOCR downloads official models on first use (bootstrap only)."""
    if not _module_available("paddleocr") or not _module_available("paddle"):
        return Check(
            name="AI OCR (PaddleOCR)",
            status=Status.ERROR,
            detail="paddleocr/paddlepaddle not importable",
            hint="pip install -r backend/requirements.txt",
        )
    cache = (home or Path.home()) / ".paddlex" / "official_models"
    cached = cache.is_dir() and any(p for p in cache.iterdir())
    if cached:
        return Check(
            name="AI OCR (PaddleOCR)",
            status=Status.PASS,
            detail=f"official models cached under {cache}",
        )
    return Check(
        name="AI OCR (PaddleOCR)",
        status=Status.WARN,
        detail="PaddleOCR model cache not found; first use will download (bootstrap)",
        hint="Run OCR once while online during setup, or copy ~/.paddlex between "
        "machines for offline edge installs. See docs/model_assets.md.",
    )


def check_barcode(*, deep: bool = True) -> Check:
    """Barcode decoding needs pyzbar + the system libzbar shared library."""
    if not _module_available("pyzbar"):
        return Check(
            name="AI barcode backend (pyzbar + libzbar)",
            status=Status.ERROR,
            detail="pyzbar not installed",
            hint="pip install -r backend/requirements.txt",
        )
    if not deep:
        return Check(
            name="AI barcode backend (pyzbar + libzbar)",
            status=Status.WARN,
            detail="pyzbar present; system libzbar not verified (run with --deep)",
        )
    from app.services.batch_intake.barcode_decoder import (
        _resolve_libzbar,
        make_barcode_decoder,
    )

    lib = _resolve_libzbar()
    decoder = make_barcode_decoder()
    if decoder is None:
        return Check(
            name="AI barcode backend (pyzbar + libzbar)",
            status=Status.ERROR,
            detail="libzbar shared library not found",
            hint="macOS: brew install zbar | Debian/Ubuntu: sudo apt-get install libzbar0",
        )
    return Check(
        name="AI barcode backend (pyzbar + libzbar)",
        status=Status.PASS,
        detail=f"libzbar: {lib or 'resolved'}",
    )


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):  # pragma: no cover - defensive
        return False


def run_model_check(
    *,
    settings: Optional[Settings] = None,
    models_root: Optional[Path] = None,
    deep: bool = True,
) -> CheckReport:
    """Return a model-asset report. Pure read-only; never downloads."""
    report = CheckReport(title="Storeye model assets")
    root = Path(models_root) if models_root else PROJECT_ROOT
    try:
        settings = settings or get_settings()
    except Exception as exc:
        report.add(
            "Configuration",
            Status.ERROR,
            detail=f"invalid configuration: {exc}",
        )
        return report

    report.extend(
        [
            check_person_detector(root),
            check_shelf_model(root),
            check_reid(settings, deep=deep),
            check_paddleocr(deep=deep),
            check_barcode(deep=deep),
        ]
    )
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="model_check",
        description="Validate local Storeye AI model assets (read-only; no downloads).",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument(
        "--deep",
        action="store_true",
        help="also verify runtime libraries can import/initialise the models",
    )
    args = parser.parse_args(argv)

    report = run_model_check(deep=args.deep)
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, default=str))
    else:
        render(report)
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
