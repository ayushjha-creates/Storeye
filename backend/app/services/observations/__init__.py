"""Storeye observation layer.

Records what Storeye's AI systems observe. Observations are NEVER business
truth: recording them never changes inventory and never creates batches.

    ObservationService     -> record/query observations
    product_observation     -> shelf/product detection adapter (PRODUCT)
    person_observation      -> person tracker adapter (PERSON)
    text_observation        -> OCR adapter (TEXT)
    expiry_observation      -> expiry parser adapter (EXPIRY_METADATA)
"""

from .observation_service import ObservationService
from .adapters import (
    from_shelf_detection,
    from_person_detection,
    from_tracked_person,
    from_ocr_result,
    from_parsed_metadata,
)
from .errors import StoreyeObservationError, ValidationError, EntityNotFoundError

__all__ = [
    "ObservationService",
    "from_shelf_detection",
    "from_person_detection",
    "from_tracked_person",
    "from_ocr_result",
    "from_parsed_metadata",
    "StoreyeObservationError",
    "ValidationError",
    "EntityNotFoundError",
]