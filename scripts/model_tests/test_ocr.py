#!/usr/bin/env python3
"""Milestone 4 test: PaddleOCR text extraction.

Usage (from project root):
    python scripts/model_tests/test_ocr.py
    python scripts/model_tests/test_ocr.py path/to/image.jpg

Output image is saved to:
    runs/model_tests/ocr/test_ocr_annotated.jpg
The original input image is never overwritten.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from app.services.vision.ocr import OCRService


def main() -> int:
    parser = argparse.ArgumentParser(description="Storeye PaddleOCR text extraction test")
    default_img = "data/tests/ocr/test_expiry.jpg"
    parser.add_argument(
        "image", nargs="?", default=default_img,
        help=f"Path to an image with printed text (default: {default_img})",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output directory (default: runs/model_tests/ocr)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent.parent
    img_path = Path(args.image)
    if not img_path.is_absolute():
        img_path = root / img_path

    if not img_path.exists():
        print(f"[ERROR] OCR test image not found: {img_path}")
        print("        Place an image with printed text at data/tests/ocr/test_expiry.jpg")
        return 1

    # --- 1. Report versions ---------------------------------------------------
    try:
        import paddle
        print(f"[INFO] PaddlePaddle version: {paddle.__version__}")
    except ImportError:
        print("[ERROR] PaddlePaddle not installed. Run: pip install paddlepaddle")
        return 1

    try:
        import paddleocr
        print(f"[INFO] PaddleOCR version: {paddleocr.__version__}")
    except ImportError:
        print("[ERROR] PaddleOCR not installed. Run: pip install paddleocr")
        return 1

    # --- 2. Load OCR service ----------------------------------------------------
    try:
        service = OCRService()
    except RuntimeError as exc:
        print(f"[ERROR] OCR init failed: {exc}")
        return 1
    print("[INFO] OCR service initialised")

    # --- 3. Load image -----------------------------------------------------------
    import cv2
    import time

    frame = cv2.imread(str(img_path))
    if frame is None:
        print(f"[ERROR] Could not read image: {img_path}")
        return 1
    print(f"[INFO] Input: {img_path.resolve()}")
    print(f"        shape={frame.shape[1]}x{frame.shape[0]}")

    # --- 4. Run OCR --------------------------------------------------------------
    t0 = time.perf_counter()
    result = service.extract_text(frame)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    print(f"\n[INFO] Inference time: {elapsed_ms:.0f} ms")
    print(f"[INFO] OCR detections: {len(result)}")

    for i, it in enumerate(result.items, 1):
        bb = [round(v, 1) for v in it.bbox_xyxy]
        print(f"\n[{i}] text='{it.text}'")
        print(f"    confidence={it.confidence:.3f}")
        print(f"    bbox={bb}")

    if len(result) == 0:
        print("[WARN] No text detected. Use a cleaner/sharp image "
              "with larger printed text.")

    # --- 5. Save annotated output ---------------------------------------------------
    out_dir = root / (args.output or "runs/model_tests/ocr")
    out_dir.mkdir(parents=True, exist_ok=True)
    annotated = service.annotate(frame, result)
    out_path = out_dir / "test_ocr_annotated.jpg"
    cv2.imwrite(str(out_path), annotated)
    print(f"\n[INFO] Annotated output saved to: {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())