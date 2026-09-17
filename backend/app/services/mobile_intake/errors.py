"""Mobile intake error taxonomy (M25).

Everything in this layer treats the intake directory as UNTRUSTED input: files
that arrive via a phone are validated before they are ever handed to the M17
scan pipeline. Failure is always explicit and never faked — a rejected file
becomes a `FAILED` job with a machine-readable reason, never a made-up
product/OCR/expiry/batch/quantity/inventory.
"""

from __future__ import annotations


class MobileIntakeError(Exception):
    """Base error for the mobile intake bridge."""


class IntakeFileRejected(MobileIntakeError):
    """A file was refused by validation (unsupported/oversized/corrupt)."""

    def __init__(self, message: str, *, code: str = "REJECTED") -> None:
        super().__init__(message)
        self.code = code


class UnsupportedFileError(IntakeFileRejected):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="UNSUPPORTED_FILE")


class FileTooLargeError(IntakeFileRejected):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="TOO_LARGE")


class CorruptImageError(IntakeFileRejected):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="CORRUPT_IMAGE")


class IntakeJobNotFound(MobileIntakeError):
    """No intake job exists with the requested id."""


class IntakeDuplicateError(MobileIntakeError):
    """The file content matches an already handled intake job.

    Not an error for the caller of the UI — it is the deterministic
    idempotency contract: the same image copied twice is recognised as a
    duplicate and never double-received.
    """