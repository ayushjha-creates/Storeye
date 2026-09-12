"""OCR + ExpiryParser evaluation for the Storeye OCR dataset.

Pipeline per verified (image <-> ground-truth row) pair:
    image
      -> OCRService.extract_text            (existing PaddleOCR pipeline)
      -> bbox crop per ground-truth row     (read-only crop)
      -> ExpiryParser.parse                 (existing expiry parser)
      -> compare predicted expiry date vs ground-truth expiry_text

IMPORTANT
---------
- Ground truth is read-only; nothing is modified or invented.
- Images are matched to CSV rows ONLY by exact filename. If the CSV names an
  image that does not exist (IMG_0000.jpg ... not present), that row is
  UNPAIRED and is NEVER evaluated.
- PaddleOCR is NOT fine-tuned. OCRService and ExpiryParser are not modified.

No image is renamed, nor is any correspondence manufactured.
"""

from __future__ import annotations

from .audit import audit_dataset, DatasetAudit
from .evaluate import run_evaluation, EvaluationReport

__all__ = ["audit_dataset", "DatasetAudit", "run_evaluation", "EvaluationReport"]