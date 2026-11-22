from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

REVIEW_THRESHOLD = Decimal("0.700")

_TRAIL_NUM_RE = re.compile(r"\s+(?:#\d+|\d{3,}|TXN[-_]?\d+|INV[-_]?\d+)\b", re.IGNORECASE)
_CLEAN_RE = re.compile(r"[^\w\s&/+.-]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_merchant(description: str) -> str:
    """Normalize merchant string via NFKC Unicode normalization, whitespace folding, and safe punctuation cleanup."""
    nfkc = unicodedata.normalize("NFKC", description).upper().strip()
    without_refs = _TRAIL_NUM_RE.sub("", nfkc)
    cleaned = _CLEAN_RE.sub(" ", without_refs)
    folded = _WS_RE.sub(" ", cleaned).strip()
    return folded[:160] if folded else "UNKNOWN MERCHANT"


def validate_confidence(value: Decimal | str | float | None) -> Decimal | None:
    """Validate heuristic confidence in [0.000, 1.000] quantized to 3 decimal places."""
    if value is None:
        return None
    try:
        dec = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid confidence score") from exc
    if not dec.is_finite() or dec < Decimal("0") or dec > Decimal("1"):
        raise ValueError(f"Confidence out of bounds [0, 1]: {dec}")
    return dec.quantize(Decimal("0.001"))


def determine_review_status(
    confidence: Decimal | None,
    *,
    from_user_rule: bool = False,
    duplicate_candidate: bool = False,
) -> str:
    """
    Route transactions deterministically:
    - duplicate candidates always need review
    - approved user merchant rule -> APPROVED
    - confidence is None or confidence < 0.700 -> NEEDS_REVIEW
    - confidence >= 0.700 -> SUGGESTED
    """
    if duplicate_candidate:
        return "NEEDS_REVIEW"
    if from_user_rule:
        return "APPROVED"
    norm_conf = validate_confidence(confidence)
    if norm_conf is None or norm_conf < REVIEW_THRESHOLD:
        return "NEEDS_REVIEW"
    return "SUGGESTED"

