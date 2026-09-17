"""Mobile-to-Edge USB Intake Bridge (M25).

A phone acts only as a capture device; images move over USB into a laptop
intake folder. This package auto-detects the pushed files, validates them,
de-duplicates by content hash and feeds each new photo into the EXISTING M17
Smart Batch Intake pipeline as a read-only candidate. Human confirmation and
every inventory/batch write keep happening through the M17 confirmation flow
— nothing here mutates the database, and no OCR/expiry/batch/quantity value
is ever invented.
"""

from .errors import (
    CorruptImageError,
    FileTooLargeError,
    IntakeDuplicateError,
    IntakeFileRejected,
    IntakeJobNotFound,
    MobileIntakeError,
    UnsupportedFileError,
)
from .intake_models import IntakeJob, JobState, JobsStore
from .intake_service import MobileIntakeService

__all__ = [
    "CorruptImageError",
    "FileTooLargeError",
    "IntakeDuplicateError",
    "IntakeFileRejected",
    "IntakeJob",
    "IntakeJobNotFound",
    "JobState",
    "JobsStore",
    "MobileIntakeError",
    "MobileIntakeService",
    "UnsupportedFileError",
]