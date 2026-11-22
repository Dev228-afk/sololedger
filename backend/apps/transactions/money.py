from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT_SCALE = Decimal("100")
QUANT_2DP = Decimal("0.01")


class MoneyParseError(ValueError):
    """Raised when an input money string is invalid or violates precision/currency rules."""


def parse_decimal_to_minor(raw: str | Decimal, *, currency: str = "USD") -> int:
    """Parse an exact decimal string/Decimal into signed integer minor units (USD cents)."""
    if currency.upper() != "USD":
        raise MoneyParseError("UNSUPPORTED_CURRENCY")
    if isinstance(raw, Decimal):
        dec = raw
    else:
        cleaned = raw.strip().replace(",", "").replace("$", "")
        if not cleaned or cleaned in {"+", "-", "."}:
            raise MoneyParseError("INVALID_AMOUNT")
        # Support accounting parentheses like "(42.85)" -> "-42.85"
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = f"-{cleaned[1:-1].strip()}"
        try:
            dec = Decimal(cleaned)
        except InvalidOperation as exc:
            raise MoneyParseError("INVALID_AMOUNT") from exc

    if not dec.is_finite():
        raise MoneyParseError("INVALID_AMOUNT")

    scaled = dec * CENT_SCALE
    if scaled != scaled.to_integral_value(rounding=ROUND_HALF_UP):
        raise MoneyParseError("EXCESS_DECIMAL_PRECISION")
    return int(scaled)


def minor_to_decimal_str(amount_minor: int) -> str:
    """Format signed integer minor units as exact two-decimal string (e.g. '-42.85')."""
    dec = (Decimal(amount_minor) / CENT_SCALE).quantize(QUANT_2DP)
    return f"{dec:.2f}"


def sanitize_csv_cell(value: str) -> str:
    """Neutralize spreadsheet formula injection on text cells without altering numeric columns."""
    if value and value[0] in {"=", "+", "-", "@", "\t", "\r"}:
        return f"'{value}"
    return value
