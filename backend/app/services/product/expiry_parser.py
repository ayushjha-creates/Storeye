"""Expiry / batch / MRP text parser for Storeye.

This module converts the RAW TEXT produced by PaddleOCR into structured
product metadata (expiry date, manufacturing date, batch number, MRP).

It is deliberately DECOUPLED from OCR:
    - `backend/app/services/vision/ocr.py`  (IMAGE -> RAW TEXT)
    - `backend/app/services/product/expiry_parser.py`  (RAW TEXT -> STRUCTURED)

The parser takes a plain string or an OCRResult (so it also accepts
structured OCR directly) and NEVER requires an image or the PaddleOCR
model. That keeps it fast, deterministic and unit-testable.

CONSERVATIVE BY DESIGN
    - Every value is machine-extracted data. We never invent missing values:
      absent values stay None/empty.
    - A date is only treated as an expiry/manufacturing date when it follows a
      recognised label (EXP, USE BY, MFG, ...). An unlabelled date is ignored.
    - OCR noise on LABELS is tolerated only when the following value actually
      parses (e.g. "EYP 12/09/2026" -> expiry date); we do not use aggressive
      fuzzy matching.

STOREYE DATE CONVENTION
    Because Storeye is initially targeted at India, a 3-part date is read as
    DD/MM/YYYY by default. When both DD/MM/YYYY and MM/DD/YYYY are valid and
    differ, a warning is recorded but the DD/MM/YYYY reading is kept (explicit,
    documented).  A 2-part date whose second part is a 4-digit year (e.g.
    09/2027) is read as a MONTH/YEAR and represented as the first day of that
    month with `expiry_date_precision == "month"` (we do not invent a day).
    2-digit years are mapped to year + 2000 (products manufactured after 2000).
"""

from __future__ import annotations

import calendar
import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("storeye.product.expiry_parser")

_DATE_PRECISION_DAY = "day"
_DATE_PRECISION_MONTH = "month"

# ---------------------------------------------------------------------------
# Label vocabulary (case-insensitive). OCR-noise aliases are included but only
# ever accepted when the value that follows is a genuine parseable value, so
# they cannot turn unrelated text into valid expiry info.
# ---------------------------------------------------------------------------
_EXPIRY_LABELS: Dict[str, str] = {
    "EXP": "EXP",
    "EXP.": "EXP",
    "EXP:": "EXP",
    "EXPIRY": "EXP",
    "EXPIRY DATE": "EXP",
    "EXP DATE": "EXP",
    "EXP-DATE": "EXP",
    "USE BY": "EXP",
    "USEBY": "EXP",
    "USE BEFORE": "EXP",
    "CONSUME BEFORE": "EXP",
    "BB": "EXP",
    "B.B.": "EXP",
    "BEST BEFORE": "EXP",
    "BESTBEFORE": "EXP",
    "BEST BY": "EXP",
    "BESTBY": "EXP",
    # OCR noise -> only accepted when a valid date follows
    "EYP": "EXP",
    "EYPY": "EXP",
}

_MFG_LABELS: Dict[str, str] = {
    "MFG": "MFG",
    "MFD": "MFG",
    "MFC": "MFG",
    "MNF": "MFG",
    "MFG DATE": "MFG",
    "MFG DATE:": "MFG",
    "MANUFACTURING DATE": "MFG",
    "MANUFACTURED": "MFG",
    "MANUFACTURE": "MFG",
    "DATE OF MANUFACTURE": "MFG",
    "DOM": "MFG",
    # Indian packaging standards (PKD, PACKED, etc.)
    "PKD": "MFG",
    "PKD.": "MFG",
    "PKD:": "MFG",
    "PKD ON": "MFG",
    "PACKED": "MFG",
    "PACKED ON": "MFG",
    "PKG": "MFG",
    "PKG DATE": "MFG",
    "PACKING": "MFG",
    "PACKING DATE": "MFG",
}

_BATCH_LABELS: Dict[str, str] = {
    "BATCH": "BATCH",
    "BATCH NO": "BATCH",
    "BATCH NO.": "BATCH",
    "BATCH NUMBER": "BATCH",
    "LOT": "BATCH",
    "LOT NO": "BATCH",
    "LOT NO.": "BATCH",
    "LOT NUMBER": "BATCH",
    # OCR noise -> only accepted when a valid batch value follows
    "BATCHH": "BATCH",
    "BATCHCH": "BATCH",
    "LOTTO": "BATCH",
}

_MRP_LABELS: Dict[str, str] = {
    "MRP": "MRP",
    "MRP:": "MRP",
    "MAX RET PRICE": "MRP",
    "MAX RETAIL PRICE": "MRP",
    "MAXIMUM RETAIL PRICE": "MRP",
}

# prefer longest labels first so "MANUFACTURING DATE" beats "MFG"-style matches
_LABEL_VOCAB = {
    "expiry": _EXPIRY_LABELS,
    "mfg": _MFG_LABELS,
    "batch": _BATCH_LABELS,
    "mrp": _MRP_LABELS,
}


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------
@dataclass
class ParsedProductMetadata:
    """Structured, machine-extracted product metadata.

    Every field is Optional. Missing/unreliable values stay None — nothing is
    invented. The raw OCR text is preserved so later logic can audit how each
    value was obtained.
    """

    expiry_date: Optional[date] = None
    expiry_date_precision: str = _DATE_PRECISION_DAY  # "day" | "month"
    manufacturing_date: Optional[date] = None
    manufacturing_date_precision: str = _DATE_PRECISION_DAY
    batch_number: Optional[str] = None
    mrp: Optional[Decimal] = None
    raw_text: str = ""
    confidence: Optional[float] = None
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "expiry_date_precision": self.expiry_date_precision,
            "manufacturing_date": self.manufacturing_date.isoformat() if self.manufacturing_date else None,
            "manufacturing_date_precision": self.manufacturing_date_precision,
            "batch_number": self.batch_number,
            "mrp": float(self.mrp) if self.mrp is not None else None,
            "raw_text": self.raw_text,
            "confidence": self.confidence,
            "warnings": self.warnings,
        }

    def __bool__(self) -> bool:
        """True if at least one field was extracted."""
        return any(
            [
                self.expiry_date is not None,
                self.manufacturing_date is not None,
                self.batch_number is not None,
                self.mrp is not None,
            ]
        )


# ---------------------------------------------------------------------------
# Small regex helpers
# ---------------------------------------------------------------------------
_DATE_TOKEN_RE = re.compile(
    r"(?<!\d)(\d{1,2}|\d{4})\s*[./\- ]\s*(\d{1,4})(?:\s*[./\- ]\s*(\d{2,4}))?(?!\d)"
)
_MONEY_RE = re.compile(r"\d{1,7}(?:[.,]\d{1,2})?")
_BATCH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{1,}")

_MONTH_NAMES: Dict[str, int] = {
    "JAN": 1, "JANUARY": 1,
    "FEB": 2, "FEBRUARY": 2,
    "MAR": 3, "MARCH": 3,
    "APR": 4, "APRIL": 4,
    "MAY": 5,
    "JUN": 6, "JUNE": 6,
    "JUL": 7, "JULY": 7,
    "AUG": 8, "AUGUST": 8,
    "SEP": 9, "SEPT": 9, "SEPTEMBER": 9,
    "OCT": 10, "OCTOBER": 10,
    "NOV": 11, "NOVEMBER": 11,
    "DEC": 12, "DECEMBER": 12,
}

_TEXT_MONTH_3PART_RE = re.compile(
    r"^(\d{1,2})\s*[./\- ]\s*([A-Za-z]{3,9})\s*[./\- ]\s*(\d{2,4})$"
)
_TEXT_MONTH_3PART_REV_RE = re.compile(
    r"^([A-Za-z]{3,9})\s*[./\- ]\s*(\d{1,2})\s*[./\- ,]\s*(\d{2,4})$"
)
_TEXT_MONTH_2PART_RE = re.compile(
    r"^([A-Za-z]{3,9})\s*[./\- ]\s*(\d{2,4})$"
)

_RELATIVE_EXPIRY_RE = re.compile(
    r"(?:BEST\s+BEFORE|USE\s+WITHIN|USE\s+BY|CONSUME\s+WITHIN|SHELF\s+LIFE|EXPIRY|EXP)\s*[:\-]?\s*(\d{1,3})\s*(MONTHS?|DAYS?|YEARS?)"
    r"|(\d{1,3})\s*(MONTHS?|DAYS?|YEARS?)\s+(?:FROM|OF)\s+(?:PKD|PKG|PACKAGING|PACKING|MANUFACTURE|MFD|MFG|DATE)",
    re.IGNORECASE,
)


def _clean_line(raw: str) -> str:
    """Basic cleaning: strip, collapse whitespace, unify colon spacing."""
    s = raw.strip()
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s)
    # "MRP:45" -> "MRP: 45" so separator handling is uniform
    s = re.sub(r":(?=\S)", ": ", s)
    return s


def _normalize_year(y: int) -> int:
    """Map a 2-digit year to 4-digit using the Storeye convention (year+2000)."""
    if 0 <= y <= 99:
        return 2000 + y
    return y


def _parse_date(token: str) -> Optional[Tuple[date, str, List[str]]]:
    """Turn a token into (date, precision, warnings) or None.

    3-part -> DD/MM/YYYY (Storeye/India default, day precision).
    2-part where 2nd part is a 4-digit year -> MM/YYYY (month precision).
    Also supports text months (e.g. 15-OCT-2025, 15 OCT 25, OCT 2025, OCT 15 2025).
    Anything ambiguous/unusable is rejected rather than guessed.
    """
    s = token.strip()
    # 1. Text month formats (e.g. 15-OCT-2025, 15 OCT 25, OCT 2025)
    m_txt3 = _TEXT_MONTH_3PART_RE.match(s)
    if m_txt3:
        d_val, mon_str, y_val = int(m_txt3.group(1)), m_txt3.group(2).upper(), int(m_txt3.group(3))
        if mon_str in _MONTH_NAMES and 1 <= d_val <= 31:
            y = _normalize_year(y_val)
            dt = _safe_date(d_val, _MONTH_NAMES[mon_str], y)
            if dt is not None:
                return dt, _DATE_PRECISION_DAY, []

    m_txt3_rev = _TEXT_MONTH_3PART_REV_RE.match(s)
    if m_txt3_rev:
        mon_str, d_val, y_val = m_txt3_rev.group(1).upper(), int(m_txt3_rev.group(2)), int(m_txt3_rev.group(3))
        if mon_str in _MONTH_NAMES and 1 <= d_val <= 31:
            y = _normalize_year(y_val)
            dt = _safe_date(d_val, _MONTH_NAMES[mon_str], y)
            if dt is not None:
                return dt, _DATE_PRECISION_DAY, []

    m_txt2 = _TEXT_MONTH_2PART_RE.match(s)
    if m_txt2:
        mon_str, y_val = m_txt2.group(1).upper(), int(m_txt2.group(2))
        if mon_str in _MONTH_NAMES:
            y = _normalize_year(y_val)
            dt = _safe_date(1, _MONTH_NAMES[mon_str], y)
            if dt is not None:
                return dt, _DATE_PRECISION_MONTH, [
                    f"'{s}' read as MONTH/YEAR -> represented as {dt.isoformat()}; "
                    "no specific day is assumed."
                ]

    # 2. Standard numeric date format
    m = _DATE_TOKEN_RE.fullmatch(s)
    if not m:
        return None

    warnings: List[str] = []
    a = int(m.group(1))
    b = int(m.group(2))
    c_raw = m.group(3)

    # ---- 3-part date -------------------------------------------------
    if c_raw is not None:
        year = _normalize_year(int(c_raw))
        if not (1900 <= year <= 2100):
            return None
        # DD/MM/YYYY (India convention). a must be a valid day, b a valid month.
        day, month = a, b
        if not (1 <= month <= 12):
            return None
        if not (1 <= day <= 31):
            return None
        # Ambiguity note: if the swapped reading (MM/DD) is ALSO valid and
        # produces a different date, flag it but keep the DD/MM reading.
        if 1 <= a <= 12 and 1 <= b <= 31:
            alt = _safe_date(b, a, year)
            primary = _safe_date(day, month, year)
            if alt is not None and alt != primary:
                warnings.append(
                    f"Ambiguous date '{token}' read as DD/MM/YYYY "
                    f"({primary.isoformat()}) per Storeye's India convention."
                )
        dt = _safe_date(day, month, year)
        if dt is None:
            return None
        return dt, _DATE_PRECISION_DAY, warnings

    # ---- 2-part date ---------------------------------------------------
    # Only interpret as MONTH/YEAR when the 2nd part is a 4-digit year OR
    # a 2-digit year in the 2020-2045 window (common on Indian FMCG, e.g. "05/26");
    # the first part must be a valid month (1-12). We represent it as the first
    # day of that month and mark month precision (we never invent a day).
    if b >= 1000 or (1 <= a <= 12 and 20 <= b <= 45):
        year = _normalize_year(b) if b < 1000 else b
        if not (1900 <= year <= 2100):
            return None
        month = a
        if not (1 <= month <= 12):
            return None
        return date(year, month, 1), _DATE_PRECISION_MONTH, [
            "'{0}' read as MONTH/YEAR -> represented as {1}; "
            "no specific day is assumed.".format(token, date(year, month, 1).isoformat())
        ]
    # 2-digit second part not in 20-45 (e.g. "12/09") is too ambiguous; do not guess.
    return None


def _safe_date(day: int, month: int, year: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _looks_like_date(token: str) -> bool:
    s = token.strip()
    return (
        _DATE_TOKEN_RE.fullmatch(s) is not None
        or _TEXT_MONTH_3PART_RE.match(s) is not None
        or _TEXT_MONTH_3PART_REV_RE.match(s) is not None
        or _TEXT_MONTH_2PART_RE.match(s) is not None
    )


def _extract_date_after_labels(line: str) -> Optional[Tuple[date, str, Optional[str]]]:
    """Return (date, precision, matched_label) from a line, or None."""
    # Scan for a label occurrence then take the following date-like token(s).
    for field, vocab in _LABEL_VOCAB.items():
        if field not in ("expiry", "mfg"):
            continue
        low = line.upper()
        for label, canonical in sorted(vocab.items(), key=lambda kv: -len(kv[0])):
            idx = low.find(label)
            if idx < 0:
                continue
            rest = line[idx + len(label):].lstrip(": \t.-")
            tokens = _split_tokens(rest)
            for w in (3, 2, 1):
                for i in range(len(tokens) - w + 1):
                    cand = " ".join(tokens[i : i + w]).strip(":,\u20b9()[]")
                    parsed = _parse_date(cand)
                    if parsed is not None:
                        return parsed[0], parsed[1], canonical
            return None
    return None


@dataclass
class _FieldMatch:
    canonical: str
    rest_tokens: List[str]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
class ExpiryParser:
    """Parses raw OCR text into ParsedProductMetadata."""

    def __init__(self, store_country: str = "IN") -> None:
        # Kept for documentation; the India (DD/MM/YYYY) convention is default.
        self.store_country = store_country

    # ------------------------------------------------------------------
    def parse(self, source: Union[str, Any]) -> ParsedProductMetadata:
        """Parse a raw string or an OCRResult into ParsedProductMetadata.

        Args:
            source: a plain string of OCR text, or an object exposing
                `texts()` (e.g. OCRResult) or an iterable of items with
                `.text`.

        Returns:
            ParsedProductMetadata (never None).
        """
        raw_text, confidence = self._extract_text_and_confidence(source)
        lines = [_clean_line(l) for l in raw_text.split("\n")]
        lines = [l for l in lines if l]

        result = ParsedProductMetadata(raw_text=raw_text, confidence=confidence)

        # First pass: label + value on the SAME line.
        # pending maps field -> (index of the bare-label line, match) whose
        # value spilled onto a following line.
        pending: Dict[str, tuple] = {}

        for i, line in enumerate(lines):
            handled = set()
            # try to satisfy any pending field whose value spilled to this line
            for fkey in ("expiry", "mfg", "batch", "mrp"):
                if fkey in pending and fkey not in handled:
                    base_i, _m = pending[fkey]
                    val = _resolve_value(fkey, line)
                    if val is not None:
                        _apply(result, fkey, val, line)
                        del pending[fkey]
                        handled.add(fkey)

            for fkey in ("expiry", "mfg", "batch", "mrp"):
                if fkey in handled:
                    continue
                m = _match_line(fkey, line)
                if m is None:
                    continue
                val = _resolve_value(fkey, m.rest_tokens)
                if val is not None:
                    _apply(result, fkey, val, line)
                elif len(m.rest_tokens) == 0 or not _looks_like_value(m.rest_tokens):
                    # label present but value empty -> maybe on next line
                    pending[fkey] = (i, m)

        # Second pass: resolve a bare-label line from the IMMEDIATELY following
        # line only (conservative), never from the label line itself or from
        # arbitrary far-away lines.
        for fkey, (base_i, _m) in list(pending.items()):
            if base_i + 1 < len(lines):
                val = _resolve_value(fkey, lines[base_i + 1])
                if val is not None:
                    _apply(result, fkey, val, lines[base_i + 1])

        # Relative expiry fallback: e.g. "BEST BEFORE 6 MONTHS FROM PACKAGING / PKD"
        if result.expiry_date is None and result.manufacturing_date is not None:
            _infer_relative_expiry(result, raw_text)

        return result

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_text_and_confidence(source: Union[str, Any]) -> Tuple[str, Optional[float]]:
        if isinstance(source, str):
            return source, None
        # OCRResult-like: expose texts() and items[]
        texts = getattr(source, "texts", None)
        if callable(texts):
            items = list(getattr(source, "items", []) or [])
            joined = "\n".join(texts())
            conf = _avg_confidence(items)
            return joined, conf
        # Generic iterable of items with .text
        if isinstance(source, (list, tuple)):
            joined = "\n".join(str(getattr(it, "text", it)) for it in source)
            conf = _avg_confidence([it for it in source if hasattr(it, "confidence")])
            return joined, conf
        return str(source), None


def _avg_confidence(items: List[Any]) -> Optional[float]:
    vals = [float(it.confidence) for it in items if hasattr(it, "confidence")]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 4)


def _match_line(fkey: str, line: str) -> Optional[_FieldMatch]:
    """Return a _FieldMatch if `line` contains a label for `fkey`."""
    vocab = _LABEL_VOCAB[fkey]
    low = line.upper()
    for label, canonical in sorted(vocab.items(), key=lambda kv: -len(kv[0])):
        idx = low.find(label)
        if idx < 0:
            continue
        rest = line[idx + len(label):]
        rest = rest.lstrip(": \t.-")
        tokens = _split_tokens(rest)
        return _FieldMatch(canonical=canonical, rest_tokens=tokens)
    return None


def _split_tokens(text: str) -> List[str]:
    text = re.sub(r"[,;]", " ", text)
    return [t for t in text.split() if t]


def _looks_like_value(tokens: List[str]) -> bool:
    for t in tokens:
        if _looks_like_date(t) or _BATCH_RE.fullmatch(t) or _MONEY_RE.fullmatch(t):
            return True
    return False


def _resolve_value(fkey: str, rest_tokens) -> Optional[Any]:
    """Attempt to resolve the value for a field from tokens.

    Accepts a list of tokens (same-line remainder) OR a raw line string
    (cross-line value-only fallback).
    """
    if isinstance(rest_tokens, str):
        tokens = _split_tokens(rest_tokens)
    else:
        tokens = list(rest_tokens)

    if not tokens:
        return None

    if fkey in ("expiry", "mfg"):
        for w in (3, 2, 1):
            for i in range(len(tokens) - w + 1):
                cand = " ".join(tokens[i : i + w]).strip(":,\u20b9()[]")
                parsed = _parse_date(cand)
                if parsed is not None:
                    return parsed
        return None

    if fkey == "batch":
        joined = " ".join(tokens)
        for t in tokens:
            cand = t.strip(":()[]")
            if _looks_like_date(cand):
                continue
            m = _BATCH_RE.fullmatch(cand)
            if m and _is_good_batch(cand):
                return cand
        # handle tokens joined by '-' or space, e.g. BATCH AL-12 34
        compact = re.sub(r"\s+", "", joined).strip(":()[]")
        m = _BATCH_RE.fullmatch(compact)
        if m and _is_good_batch(compact):
            return compact
        return None

    if fkey == "mrp":
        joined = " ".join(tokens)
        m = _MONEY_RE.search(joined)
        if not m:
            return None
        raw_num = m.group(0)
        try:
            num = Decimal(_normalize_decimal(raw_num))
        except InvalidOperation:
            return None
        if num and num > 0:
            return num
        return None
    return None


def _normalize_decimal(raw: str) -> str:
    # "45.00" stays; "45,00" -> "45.00"
    if "," in raw and "." not in raw:
        return raw.replace(",", ".")
    return raw


def _is_good_batch(cand: str) -> bool:
    # Conservative: a batch must not be purely numeric (avoids grabbing MRP,
    # quantities, years, pin-codes). Requiring at least one letter is a safe
    # default for Storeye fixtures (ABC123, A1234, XY123).
    has_letter = any(ch.isalpha() for ch in cand)
    if has_letter and len(cand) >= 3:
        if not _looks_like_date(cand) and not _MONEY_RE.fullmatch(cand):
            return True
    return False


def _apply(result: ParsedProductMetadata, fkey: str, val: Any, line: str) -> None:
    if fkey == "expiry":
        dt, precision, warns = val  # type: ignore[misc]
        if result.expiry_date is None:
            result.expiry_date = dt
            result.expiry_date_precision = precision
            result.warnings.extend(warns)
        else:
            result.warnings.append(f"Duplicate expiry date on line '{line}'; kept first.")
    elif fkey == "mfg":
        dt, precision, warns = val  # type: ignore[misc]
        if result.manufacturing_date is None:
            result.manufacturing_date = dt
            result.manufacturing_date_precision = precision
            result.warnings.extend(warns)
        else:
            result.warnings.append(f"Duplicate manufacturing date on line '{line}'; kept first.")
    elif fkey == "batch":
        if result.batch_number is None:
            result.batch_number = str(val)
        else:
            result.warnings.append(f"Duplicate batch number on line '{line}'; kept first.")
    elif fkey == "mrp":
        if result.mrp is None:
            result.mrp = Decimal(val)
        else:
            result.warnings.append(f"Duplicate MRP on line '{line}'; kept first.")


def _add_months(d: date, months: int) -> date:
    year = d.year + (d.month + months - 1) // 12
    month = (d.month + months - 1) % 12 + 1
    max_days = calendar.monthrange(year, month)[1]
    day = min(d.day, max_days)
    return date(year, month, day)


def _infer_relative_expiry(result: ParsedProductMetadata, raw_text: str) -> None:
    if result.manufacturing_date is None:
        return
    m = _RELATIVE_EXPIRY_RE.search(raw_text)
    if not m:
        return
    if m.group(1) and m.group(2):
        count_str, unit_str = m.group(1), m.group(2)
    elif m.group(3) and m.group(4):
        count_str, unit_str = m.group(3), m.group(4)
    else:
        return

    try:
        count = int(count_str)
    except ValueError:
        return

    unit = unit_str.upper()
    if unit.startswith("MONTH"):
        expiry = _add_months(result.manufacturing_date, count)
        precision = _DATE_PRECISION_MONTH
    elif unit.startswith("DAY"):
        expiry = result.manufacturing_date + timedelta(days=count)
        precision = _DATE_PRECISION_DAY
    elif unit.startswith("YEAR"):
        expiry = _add_months(result.manufacturing_date, count * 12)
        precision = _DATE_PRECISION_MONTH
    else:
        return

    result.expiry_date = expiry
    result.expiry_date_precision = precision
    result.warnings.append(
        f"Expiry calculated as {count} {unit.lower()} from manufacturing date "
        f"({result.manufacturing_date.isoformat()})."
    )


def parse(source: Union[str, Any]) -> ParsedProductMetadata:
    """Convenience one-shot entry point."""
    return ExpiryParser().parse(source)