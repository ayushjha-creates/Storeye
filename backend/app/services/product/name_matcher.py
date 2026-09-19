"""Conservative OCR text -> product-catalog name resolution.

CAMERA OCR IS NOT BUSINESS TRUTH. This matcher only resolves a printed product
name that PaddleOCR read off a package to a product that the store ALREADY has
in its catalog. It never creates products, never changes inventory, and never
guesses: a line must match a known alias (the product name, its brand, or one of
its explicit `ai_classes`) with a high similarity score. Anything else stays
unmatched and is surfaced to the operator as unrecognized label text.

Matching is deterministic: aliases are normalized (case/punctuation folded),
noise lines (dates, MRP, EXP/MFG/BATCH labels) are skipped, and ties are broken
by product name then id so the same text always resolves to the same product.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable, List, Optional, Sequence, Union

# A line must score at least this high against a known alias to be accepted.
DEFAULT_MIN_SCORE = 0.86
# Aliases shorter than this (letters+digits, spaces ignored) are too generic.
MIN_ALIAS_LENGTH = 4

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_WS = re.compile(r"\s+")
_DATE_LIKE = re.compile(r"^(?:\d{1,4})(?: \d{1,4}){0,2}$")

# Words that mark a line as a label/caption rather than a product name.
_NOISE_WORDS = {
    "exp",
    "expiry",
    "eyp",
    "mfg",
    "mfd",
    "mfc",
    "mrp",
    "batch",
    "lot",
    "use",
    "best",
    "before",
    "date",
    "price",
    "inclusive",
    "tax",
    "net",
    "wt",
    "weight",
}


def normalize_name(text: str) -> str:
    """Fold case + punctuation and collapse whitespace for comparison."""
    lowered = (text or "").lower()
    folded = _NON_ALNUM.sub(" ", lowered)
    return _WS.sub(" ", folded).strip()


def _is_noise(normalized: str) -> bool:
    if not normalized:
        return True
    compact = normalized.replace(" ", "")
    if compact.isdigit():
        return True
    if _DATE_LIKE.fullmatch(normalized):
        return True
    return any(word in _NOISE_WORDS for word in normalized.split())


def _score(line: str, alias: str) -> float:
    """Similarity of a normalized OCR line to a normalized alias (0..1)."""
    if line == alias:
        return 1.0
    ratio = SequenceMatcher(None, line, alias).ratio()
    # Word-boundary containment: every alias word appears in the line, e.g.
    # "amul taaza milk 1l" contains "amul taaza milk".
    alias_words = alias.split()
    line_words = set(line.split())
    if alias_words and all(word in line_words for word in alias_words):
        coverage = len(alias) / max(len(line), 1)
        ratio = max(ratio, min(1.0, 0.6 + 0.4 * coverage))
    return ratio


@dataclass
class ProductNameEntry:
    """A catalog product plus the normalized aliases it may be printed as."""

    product_id: str
    name: str
    aliases: List[str] = field(default_factory=list)
    selling_price: Optional[str] = None


@dataclass
class NameMatch:
    product_id: str
    product_name: str
    matched_text: str
    matched_alias: str
    score: float
    selling_price: Optional[str] = None


class ProductNameMatcher:
    """Resolve OCR lines to catalog products conservatively."""

    def __init__(
        self,
        entries: Sequence[ProductNameEntry],
        *,
        min_score: float = DEFAULT_MIN_SCORE,
    ) -> None:
        self._entries = list(entries)
        self.min_score = min_score

    @classmethod
    def from_products(cls, products: Iterable[object]) -> "ProductNameMatcher":
        entries: List[ProductNameEntry] = []
        for product in products:
            raw_aliases = [getattr(product, "name", "") or ""]
            brand = getattr(product, "brand", None)
            if brand:
                raw_aliases.append(str(brand))
            for class_name in getattr(product, "ai_classes", None) or []:
                if isinstance(class_name, str) and class_name.strip():
                    raw_aliases.append(class_name)
            aliases = sorted({normalize_name(a) for a in raw_aliases if normalize_name(a)})
            price = getattr(product, "selling_price", None)
            entries.append(
                ProductNameEntry(
                    product_id=str(getattr(product, "id", "")),
                    name=str(getattr(product, "name", "") or ""),
                    aliases=aliases,
                    selling_price=str(price) if price is not None else None,
                )
            )
        # Deterministic ordering independent of DB row order.
        entries.sort(key=lambda e: (normalize_name(e.name), e.product_id))
        return cls(entries)

    @property
    def entries(self) -> List[ProductNameEntry]:
        return list(self._entries)

    def match_line(self, line: str) -> Optional[NameMatch]:
        """Match a single OCR line, or None."""
        return self.match_lines([line])

    def match_best(self, line_or_lines: Union[str, Iterable[str]]) -> Optional[NameMatch]:
        """Match a single line or multiple lines, returning best match."""
        if isinstance(line_or_lines, str):
            return self.match_lines([line_or_lines])
        return self.match_lines(line_or_lines)

    def match_lines(self, lines: Iterable[str]) -> Optional[NameMatch]:
        """Best conservative match across OCR lines, or None if nothing fits."""
        best: Optional[NameMatch] = None
        for raw in lines:
            normalized = normalize_name(str(raw))
            if _is_noise(normalized):
                continue
            for entry in self._entries:
                for alias in entry.aliases:
                    if len(alias.replace(" ", "")) < MIN_ALIAS_LENGTH:
                        continue
                    score = _score(normalized, alias)
                    if score < self.min_score:
                        continue
                    candidate = NameMatch(
                        product_id=entry.product_id,
                        product_name=entry.name,
                        matched_text=str(raw).strip(),
                        matched_alias=alias,
                        score=round(score, 4),
                        selling_price=entry.selling_price,
                    )
                    if best is None or _better(candidate, best):
                        best = candidate
        return best



def _better(candidate: NameMatch, current: NameMatch) -> bool:
    if candidate.score != current.score:
        return candidate.score > current.score
    return (candidate.product_name, candidate.product_id) < (
        current.product_name,
        current.product_id,
    )
