"""Exception handlers for the Storeye FastAPI API.

Maps domain-layer and database-layer errors onto a consistent JSON error
body and appropriate HTTP status codes:

    { "detail": [
        { "loc": [...], "msg": "...", "type": "..." }
      ] }

Domain exception => status / type mapping
------------------------------------------
StoreyeInventoryError/ValidationError           422  VALIDATION_ERROR
Domain EntityNotFoundError                      404  NOT_FOUND
Domain DuplicateBatchError                      409  CONFLICT
Observation ValidationError                     422  VALIDATION_ERROR
SQLAlchemy IntegrityError (unique/FK violation) 409  CONFLICT
Unexpected errors                                500  INTERNAL_ERROR
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from ..services.inventory.errors import (
    BatchMismatchError,
    DuplicateBatchError,
    EntityNotFoundError as InventoryNotFound,
    StoreyeInventoryError,
    ValidationError as InventoryValidation,
)
from ..services.observations.errors import (
    EntityNotFoundError as ObservationNotFound,
    StoreyeObservationError,
    ValidationError as ObservationValidation,
)
from ..services.alerts.errors import (
    EntityNotFoundError as AlertNotFound,
    StoreyeAlertError,
    ValidationError as AlertValidation,
)
from ..services.batch_intake.errors import (
    BarcodeUnavailableError,
    BatchIntakeError,
    ImageDecodeError,
    ImageQualityError,
    OcrUnavailableError,
    ScanValidationError,
)


def _payload(msg: str, etype: str, loc=None) -> dict:
    return {
        "detail": [
            {
                "loc": loc or ["body"],
                "msg": msg,
                "type": etype,
            }
        ]
    }


def _error(status: int, msg: str, etype: str, loc=None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=_payload(msg, etype, loc),
    )


def _register_handlers(app: FastAPI) -> None:
    # ---- 422: domain validation ----
    @app.exception_handler(InventoryValidation)
    async def _inventory_validation(_req: Request, exc: InventoryValidation):
        return _error(422, str(exc), "VALIDATION_ERROR")

    @app.exception_handler(ObservationValidation)
    async def _observation_validation(_req: Request, exc: ObservationValidation):
        return _error(422, str(exc), "VALIDATION_ERROR")

    @app.exception_handler(AlertValidation)
    async def _alert_validation(_req: Request, exc: AlertValidation):
        return _error(422, str(exc), "VALIDATION_ERROR")

    # ---- 404: domain not-found ----
    @app.exception_handler(InventoryNotFound)
    async def _inventory_not_found(_req: Request, exc: InventoryNotFound):
        return _error(404, str(exc), "NOT_FOUND")

    @app.exception_handler(ObservationNotFound)
    async def _observation_not_found(_req: Request, exc: ObservationNotFound):
        return _error(404, str(exc), "NOT_FOUND")

    @app.exception_handler(AlertNotFound)
    async def _alert_not_found(_req: Request, exc: AlertNotFound):
        return _error(404, str(exc), "NOT_FOUND")

    # ---- 422: batch-intake scan/validate errors ----
    @app.exception_handler(ImageDecodeError)
    async def _batch_image_decode(_req: Request, exc: ImageDecodeError):
        return _error(422, str(exc), "VALIDATION_ERROR")

    @app.exception_handler(ImageQualityError)
    async def _batch_image_quality(_req: Request, exc: ImageQualityError):
        return _error(422, str(exc), "VALIDATION_ERROR")

    @app.exception_handler(ScanValidationError)
    async def _batch_scan_validation(_req: Request, exc: ScanValidationError):
        return _error(422, str(exc), "VALIDATION_ERROR")

    # ---- 503: local AI component unavailable ----
    @app.exception_handler(OcrUnavailableError)
    async def _batch_ocr_unavailable(_req: Request, exc: OcrUnavailableError):
        return _error(503, str(exc), "SERVICE_UNAVAILABLE")

    @app.exception_handler(BarcodeUnavailableError)
    async def _batch_barcode_unavailable(_req: Request, exc: BarcodeUnavailableError):
        return _error(503, str(exc), "SERVICE_UNAVAILABLE")

    # ---- 409: domain conflict ----
    @app.exception_handler(DuplicateBatchError)
    async def _duplicate_batch(_req: Request, exc: DuplicateBatchError):
        return _error(409, str(exc), "CONFLICT")

    @app.exception_handler(BatchMismatchError)
    async def _batch_mismatch(_req: Request, exc: BatchMismatchError):
        return _error(409, str(exc), "CONFLICT")

    # ---- 409: database integrity (unique violation, FK violation) ----
    @app.exception_handler(IntegrityError)
    async def _integrity_error(_req: Request, exc: IntegrityError):
        return _error(409, "Database constraint violation.", "CONFLICT")

    # ---- 500: unexpected domain errors ----
    @app.exception_handler(StoreyeInventoryError)
    async def _inventory_generic(_req: Request, exc: StoreyeInventoryError):
        return _error(500, str(exc), "INTERNAL_ERROR")

    @app.exception_handler(StoreyeObservationError)
    async def _observation_generic(_req: Request, exc: StoreyeObservationError):
        return _error(500, str(exc), "INTERNAL_ERROR")

    @app.exception_handler(StoreyeAlertError)
    async def _alert_generic(_req: Request, exc: StoreyeAlertError):
        return _error(500, str(exc), "INTERNAL_ERROR")

    # ---- 500: unexpected batch-intake domain errors ----
    @app.exception_handler(BatchIntakeError)
    async def _batch_generic(_req: Request, exc: BatchIntakeError):
        return _error(500, str(exc), "INTERNAL_ERROR")
