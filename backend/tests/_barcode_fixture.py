"""Shared test fixture helpers for Smart Batch Intake tests.

`code39_image` renders a deterministic, offline Code-39 barcode with OpenCV
in the same style used by a printed Indian retail pack (this line-growing
generator was validated against pyzbar/zbar).
"""

from __future__ import annotations

import numpy as np

# Code-39 pattern table (1 = wide element, 0 = narrow element).
_CODE39 = {
    "0": "000110100", "1": "100100001", "2": "001100001", "3": "101100000",
    "4": "000110001", "5": "100110000", "6": "001110000", "7": "000100101",
    "8": "100100100", "9": "001100100", "A": "100001001", "B": "001001001",
    "C": "101001000", "D": "000011001", "E": "100011000", "F": "001011000",
    "G": "000001101", "H": "100001100", "I": "001001100", "J": "000011100",
    "K": "100000011", "L": "001000011", "M": "101000010", "N": "000010011",
    "O": "100010010", "P": "001010010", "Q": "000000111", "R": "100000110",
    "S": "001000110", "T": "000010110", "U": "110000001", "V": "011000001",
    "W": "111000000", "X": "010010001", "Y": "110010000", "Z": "011010000",
    "-": "010000101", ".": "110000100", " ": "011000100", "$": "010101000",
    "/": "010100010", "+": "010001010", "%": "000101010", "*": "010010100",
}


def code39_image(value: str, scale: int = 6, height: int = 240, margin: int = 90) -> np.ndarray:
    """Render a Code-39 barcode as a BGR image (Offline-fixture helper)."""
    import cv2

    code = "*" + value.upper() + "*"
    bits: list[str] = []
    for i, ch in enumerate(code):
        if i > 0:
            bits.append("0")  # inter-character narrow space
        bits.extend(_CODE39[ch])
    widths = [3 if b == "1" else 1 for b in bits]

    total = sum(widths)
    img_w = total * scale + 2 * margin
    img = np.full((height + 2 * margin, img_w), 255, dtype=np.uint8)
    x = margin
    for i, (b, w) in enumerate(zip(bits, widths)):
        if i % 2 == 0:  # even elements are bars
            img[margin : height + margin, x : x + w * scale] = 0
        x += w * scale
    return img


def package_photo_bytes(
    *,
    barcode: str = "8901234567890",
    width: int = 1600,
    height: int = 1200,
    text_lines: tuple[str, ...] = (
        "MRP: 14.00",
        "MFG: 12/03/2026",
        "EXP: 15/12/2026",
        "BATCH: M24031",
    ),
) -> bytes:
    """Render a close-up package label + barcode and return JPEG bytes.

    Offline-only: pure OpenCV drawing + the Code-39 generator (no camera).
    """
    import cv2

    label = np.full((height, width, 3), 245, dtype=np.uint8)
    cv2.rectangle(label, (40, 40), (width - 40, height - 40), (200, 200, 200), 8)
    y = 220
    for line in text_lines:
        cv2.putText(
            label, line, (140, y), cv2.FONT_HERSHEY_SIMPLEX, 2.6, (10, 10, 10),
            6, cv2.LINE_AA,
        )
        y += 160
    # Barcode (Code-39) placed at the bottom of the label, scaled to fit.
    import cv2

    bc = cv2.cvtColor(code39_image(barcode, scale=2, height=150, margin=20), cv2.COLOR_GRAY2BGR)
    bc_h, bc_w = bc.shape[:2]
    y0 = height - bc_h - 160
    label[y0 : y0 + bc_h, 160 : 160 + bc_w] = bc
    ok, buf = cv2.imencode(".jpg", label)
    if not ok:
        raise RuntimeError("unable to encode fixture image")
    return buf.tobytes()