from __future__ import annotations

import codecs
import csv
import datetime as dt
import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apps.transactions.money import MoneyParseError, parse_decimal_to_minor

SUPPORTED_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y")
BINARY_MAGIC_PREFIXES = (b"MZ", b"\x7fELF", b"PK\x03\x04", b"%PDF-", b"\x89PNG")
_SLASH_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


class CsvFormatError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ParsedRowResult:
    source_line_no: int
    raw_hash: str
    posted_date: dt.date | None
    description: str
    signed_amount_minor: int | None
    currency: str
    source_txn_id: str | None
    valid: bool
    error_code: str | None = None
    error_detail: str = ""


def validate_upload_bytes(raw_bytes: bytes) -> None:
    if not raw_bytes or not raw_bytes.strip():
        raise CsvFormatError("EMPTY_FILE", "Uploaded CSV file is empty.")
    head = raw_bytes[:32]
    for magic in BINARY_MAGIC_PREFIXES:
        if head.startswith(magic):
            raise CsvFormatError("UNSAFE_BINARY_CONTENT", "Binary file content disguised as CSV is not allowed.")
    if b"\x00" in raw_bytes[:4096]:
        raise CsvFormatError("BINARY_NULL_BYTES", "Uploaded file contains null bytes and is not valid UTF-8 CSV.")


def infer_mapping_and_preview(
    file_path: Path,
) -> tuple[list[str], list[dict[str, str]], dict[str, Any]]:
    raw = file_path.read_bytes()
    validate_upload_bytes(raw)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvFormatError("INVALID_ENCODING", "CSV must be UTF-8 or UTF-8 BOM encoded.") from exc

    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames or len([f for f in reader.fieldnames if f and f.strip()]) < 3:
        raise CsvFormatError("MISSING_HEADERS", "CSV must include a valid header row with date, description, and amount columns.")

    headers = [h.strip() for h in reader.fieldnames if h is not None]
    preview_rows: list[dict[str, str]] = []
    for idx, row in enumerate(reader):
        if idx >= 10:
            break
        clean_row = {str(k).strip(): (v or "").strip() for k, v in row.items() if k is not None}
        if any(clean_row.values()):
            preview_rows.append(clean_row)

    lower_map = {h.lower(): h for h in headers}

    def pick(*candidates: str) -> str | None:
        for cand in candidates:
            if cand in lower_map:
                return lower_map[cand]
        for h_low, orig in lower_map.items():
            if any(cand in h_low for cand in candidates):
                return orig
        return None

    date_col = pick("posted date", "transaction date", "date")
    desc_col = pick("merchant", "description", "payee", "memo")
    debit_col = pick("debit", "withdrawal", "outflow")
    credit_col = pick("credit", "deposit", "inflow")
    amount_col = pick("amount", "signed amount")
    curr_col = pick("currency", "curr")
    txn_id_col = pick("transaction id", "txn id", "reference", "external ref")

    # Infer unambiguous date format or detect slash ambiguity across sampled preview rows
    date_vals = [r.get(date_col or "", "") for r in preview_rows if r.get(date_col or "", "")]
    detected_date_format = "%Y-%m-%d"
    if date_vals and all(_SLASH_DATE_RE.match(v) for v in date_vals):
        first_parts = [int(_SLASH_DATE_RE.match(v).group(1)) for v in date_vals]
        second_parts = [int(_SLASH_DATE_RE.match(v).group(2)) for v in date_vals]
        if any(p > 12 for p in second_parts):
            detected_date_format = "%m/%d/%Y"
        elif any(p > 12 for p in first_parts):
            detected_date_format = "%d/%m/%Y"
        else:
            detected_date_format = "AMBIGUOUS_SLASH"

    if debit_col and credit_col:
        suggested: dict[str, Any] = {
            "postedDateColumn": date_col or headers[0],
            "descriptionColumn": desc_col or headers[1],
            "amountMode": "DEBIT_CREDIT",
            "debitColumn": debit_col,
            "creditColumn": credit_col,
            "amountColumn": None,
            "currencyColumn": curr_col,
            "fixedCurrency": "USD" if not curr_col else None,
            "transactionIdColumn": txn_id_col,
            "dateFormat": detected_date_format,
            "decimalSeparator": ".",
            "headerRow": 1,
        }
    else:
        suggested = {
            "postedDateColumn": date_col or headers[0],
            "descriptionColumn": desc_col or headers[1],
            "amountMode": "SIGNED_AMOUNT",
            "debitColumn": None,
            "creditColumn": None,
            "amountColumn": amount_col or headers[-1],
            "currencyColumn": curr_col,
            "fixedCurrency": "USD" if not curr_col else None,
            "transactionIdColumn": txn_id_col,
            "dateFormat": detected_date_format,
            "decimalSeparator": ".",
            "headerRow": 1,
        }

    return headers, preview_rows, suggested


def validate_mapping_schema(mapping: dict[str, Any]) -> dict[str, list[str]]:
    errors: dict[str, list[str]] = {}
    if not mapping.get("postedDateColumn"):
        errors["postedDateColumn"] = ["Select the posted date column."]
    if not mapping.get("descriptionColumn"):
        errors["descriptionColumn"] = ["Select the description/merchant column."]
    mode = mapping.get("amountMode")
    if mode not in {"DEBIT_CREDIT", "SIGNED_AMOUNT"}:
        errors["amountMode"] = ["amountMode must be DEBIT_CREDIT or SIGNED_AMOUNT."]
    elif mode == "DEBIT_CREDIT":
        if not mapping.get("debitColumn") or not mapping.get("creditColumn"):
            errors["debitColumn"] = ["DEBIT_CREDIT mode requires both debitColumn and creditColumn."]
    else:
        if not mapping.get("amountColumn"):
            errors["amountColumn"] = ["SIGNED_AMOUNT mode requires amountColumn."]

    date_fmt = mapping.get("dateFormat")
    if date_fmt not in SUPPORTED_DATE_FORMATS:
        errors["dateFormat"] = ["Select an explicit date format (%Y-%m-%d, %m/%d/%Y, or %d/%m/%Y)."]
    return errors


def _parse_date(raw: str, fmt: str) -> dt.date | None:
    cleaned = raw.strip()
    if not cleaned:
        return None
    try:
        return dt.datetime.strptime(cleaned, fmt).date()
    except ValueError:
        return None


def stream_parse_csv(file_path: Path, mapping: dict[str, Any]) -> list[ParsedRowResult]:
    """Stream CSV file in bounded text mode using explicit column mapping rules."""
    results: list[ParsedRowResult] = []
    date_col = str(mapping["postedDateColumn"])
    desc_col = str(mapping["descriptionColumn"])
    mode = str(mapping["amountMode"])
    debit_col = mapping.get("debitColumn")
    credit_col = mapping.get("creditColumn")
    amount_col = mapping.get("amountColumn")
    curr_col = mapping.get("currencyColumn")
    fixed_currency = str(mapping.get("fixedCurrency") or "USD").upper()
    txn_id_col = mapping.get("transactionIdColumn")
    date_fmt = str(mapping["dateFormat"])
    decimal_sep = str(mapping.get("decimalSeparator") or ".")

    with file_path.open("rb") as fb:
        text_stream = codecs.getreader("utf-8-sig")(fb)
        reader = csv.DictReader(text_stream)
        if not reader.fieldnames:
            raise CsvFormatError("MISSING_HEADERS", "CSV file is missing a header row.")
        headers_set = {h.strip() for h in reader.fieldnames if h is not None}
        required_cols = [date_col, desc_col]
        if mode == "DEBIT_CREDIT":
            required_cols.extend([str(debit_col), str(credit_col)])
        else:
            required_cols.append(str(amount_col))
        for col in required_cols:
            if col not in headers_set:
                raise CsvFormatError("COLUMN_NOT_FOUND", f"Mapped column '{col}' is missing from CSV headers.")

        line_no = 1
        for raw_row in reader:
            line_no += 1
            row = {str(k).strip(): (v or "").strip() for k, v in raw_row.items() if k is not None}
            if not any(row.values()):
                continue

            canonical_line = "|".join(f"{k}={row[k]}" for k in sorted(row.keys()))
            raw_hash = hashlib.sha256(canonical_line.encode("utf-8")).hexdigest()
            desc = " ".join(row.get(desc_col, "").split())[:300]
            posted_raw = row.get(date_col, "")
            posted_date = _parse_date(posted_raw, date_fmt)
            currency = (row.get(str(curr_col), "") if curr_col else fixed_currency).upper() or "USD"
            source_txn_id = row.get(str(txn_id_col), "").strip()[:128] or None if txn_id_col else None

            if not desc:
                results.append(
                    ParsedRowResult(
                        source_line_no=line_no,
                        raw_hash=raw_hash,
                        posted_date=posted_date,
                        description="",
                        signed_amount_minor=None,
                        currency=currency,
                        source_txn_id=source_txn_id,
                        valid=False,
                        error_code="BLANK_DESCRIPTION",
                        error_detail="Merchant/description is blank.",
                    )
                )
                continue

            if posted_date is None:
                results.append(
                    ParsedRowResult(
                        source_line_no=line_no,
                        raw_hash=raw_hash,
                        posted_date=None,
                        description=desc,
                        signed_amount_minor=None,
                        currency=currency,
                        source_txn_id=source_txn_id,
                        valid=False,
                        error_code="INVALID_DATE",
                        error_detail=f"Date '{posted_raw}' does not match format {date_fmt}.",
                    )
                )
                continue

            if currency != "USD":
                results.append(
                    ParsedRowResult(
                        source_line_no=line_no,
                        raw_hash=raw_hash,
                        posted_date=posted_date,
                        description=desc,
                        signed_amount_minor=None,
                        currency=currency[:12],
                        source_txn_id=source_txn_id,
                        valid=False,
                        error_code="UNSUPPORTED_CURRENCY",
                        error_detail=f"Currency '{currency}' rejected; MVP accepts USD only.",
                    )
                )
                continue

            try:
                if mode == "DEBIT_CREDIT":
                    debit_raw = row.get(str(debit_col), "").strip()
                    credit_raw = row.get(str(credit_col), "").strip()
                    if decimal_sep == ",":
                        debit_raw = debit_raw.replace(".", "").replace(",", ".")
                        credit_raw = credit_raw.replace(".", "").replace(",", ".")
                    if debit_raw and credit_raw:
                        results.append(
                            ParsedRowResult(
                                source_line_no=line_no,
                                raw_hash=raw_hash,
                                posted_date=posted_date,
                                description=desc,
                                signed_amount_minor=None,
                                currency="USD",
                                source_txn_id=source_txn_id,
                                valid=False,
                                error_code="AMBIGUOUS_DIRECTION",
                                error_detail="Both Debit and Credit columns are populated.",
                            )
                        )
                        continue
                    if not debit_raw and not credit_raw:
                        results.append(
                            ParsedRowResult(
                                source_line_no=line_no,
                                raw_hash=raw_hash,
                                posted_date=posted_date,
                                description=desc,
                                signed_amount_minor=None,
                                currency="USD",
                                source_txn_id=source_txn_id,
                                valid=False,
                                error_code="BLANK_AMOUNT",
                                error_detail="Neither Debit nor Credit has an amount.",
                            )
                        )
                        continue
                    if debit_raw:
                        parsed_minor = parse_decimal_to_minor(debit_raw, currency="USD")
                        if parsed_minor < 0:
                            raise MoneyParseError("NEGATIVE_DEBIT_COLUMN")
                        signed_minor = -parsed_minor
                    else:
                        parsed_minor = parse_decimal_to_minor(credit_raw, currency="USD")
                        if parsed_minor < 0:
                            raise MoneyParseError("NEGATIVE_CREDIT_COLUMN")
                        signed_minor = parsed_minor
                else:
                    amt_raw = row.get(str(amount_col), "").strip()
                    if decimal_sep == ",":
                        amt_raw = amt_raw.replace(".", "").replace(",", ".")
                    if not amt_raw:
                        raise MoneyParseError("BLANK_AMOUNT")
                    signed_minor = parse_decimal_to_minor(amt_raw, currency="USD")
            except MoneyParseError as exc:
                results.append(
                    ParsedRowResult(
                        source_line_no=line_no,
                        raw_hash=raw_hash,
                        posted_date=posted_date,
                        description=desc,
                        signed_amount_minor=None,
                        currency="USD",
                        source_txn_id=source_txn_id,
                        valid=False,
                        error_code=str(exc),
                        error_detail=f"Amount rejected ({exc}).",
                    )
                )
                continue

            results.append(
                ParsedRowResult(
                    source_line_no=line_no,
                    raw_hash=raw_hash,
                    posted_date=posted_date,
                    description=desc,
                    signed_amount_minor=signed_minor,
                    currency="USD",
                    source_txn_id=source_txn_id,
                    valid=True,
                )
            )
    return results

