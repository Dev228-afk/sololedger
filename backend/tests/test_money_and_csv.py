from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.imports.csv_parser import (
    CsvFormatError,
    infer_mapping_and_preview,
    stream_parse_csv,
    validate_mapping_schema,
)
from apps.transactions.money import (
    MoneyParseError,
    minor_to_decimal_str,
    parse_decimal_to_minor,
    sanitize_csv_cell,
)
from tests.conftest import auth_client


def test_money_decimal_conversion_and_formula_escape():
    assert parse_decimal_to_minor("-42.85") == -4285
    assert parse_decimal_to_minor("+$1,250.50") == 125050
    assert parse_decimal_to_minor("(19.99)") == -1999
    assert parse_decimal_to_minor(Decimal("0.00")) == 0
    assert minor_to_decimal_str(-4285) == "-42.85"
    assert minor_to_decimal_str(150000) == "1500.00"

    with pytest.raises(MoneyParseError, match="UNSUPPORTED_CURRENCY"):
        parse_decimal_to_minor("10.00", currency="EUR")
    with pytest.raises(MoneyParseError, match="EXCESS_DECIMAL_PRECISION"):
        parse_decimal_to_minor("10.123")
    with pytest.raises(MoneyParseError, match="INVALID_AMOUNT"):
        parse_decimal_to_minor("NaN")

    assert sanitize_csv_cell('=HYPERLINK("http://x","a")').startswith("'=")
    assert sanitize_csv_cell("+CMD").startswith("'+")
    assert sanitize_csv_cell("-2+3").startswith("'-")
    assert sanitize_csv_cell("@SUM").startswith("'@")
    assert sanitize_csv_cell("\tbad").startswith("'\t")
    assert sanitize_csv_cell("NORMAL TEXT") == "NORMAL TEXT"


def test_csv_edge_fixtures_bom_crlf_multiline_ambiguous_invalid_and_fake_exe(tmp_path):
    fixtures = Path(__file__).resolve().parents[2] / "fixtures" / "import_edge_cases"

    # UTF-8 BOM + CRLF
    headers, rows, mapping = infer_mapping_and_preview(fixtures / "utf8_bom_crlf.csv")
    assert headers == ["Posted Date", "Merchant", "Debit", "Credit", "Transaction ID"]
    assert len(rows) == 2
    assert mapping["amountMode"] == "DEBIT_CREDIT"
    parsed_bom = stream_parse_csv(fixtures / "utf8_bom_crlf.csv", mapping)
    assert all(r.valid for r in parsed_bom)
    assert parsed_bom[0].signed_amount_minor == -1850
    assert "ÉCLAIR" in parsed_bom[0].description
    assert "ACADEMY PRO" in parsed_bom[1].description

    # Quoted multiline commas
    _, _, multi_map = infer_mapping_and_preview(fixtures / "multiline_quotes.csv")
    parsed_multi = stream_parse_csv(fixtures / "multiline_quotes.csv", multi_map)
    assert len(parsed_multi) == 2
    assert parsed_multi[0].signed_amount_minor == -5410

    # Ambiguous US/EU slash dates
    _, _, amb_map = infer_mapping_and_preview(fixtures / "ambiguous_dates.csv")
    assert amb_map["dateFormat"] == "AMBIGUOUS_SLASH"
    assert "dateFormat" in validate_mapping_schema(amb_map)
    amb_map["dateFormat"] = "%m/%d/%Y"
    assert validate_mapping_schema(amb_map) == {}

    # Quarantined invalid rows (debit+credit filled, bad date, blank desc, EUR, blank amount) + 1 valid row
    _, _, inv_map = infer_mapping_and_preview(fixtures / "invalid_rows.csv")
    parsed_inv = stream_parse_csv(fixtures / "invalid_rows.csv", inv_map)
    codes = [r.error_code for r in parsed_inv]
    assert codes == [
        "AMBIGUOUS_DIRECTION",
        "INVALID_DATE",
        "BLANK_DESCRIPTION",
        "UNSUPPORTED_CURRENCY",
        "BLANK_AMOUNT",
        None,
    ]
    assert parsed_inv[-1].valid is True and parsed_inv[-1].signed_amount_minor == -1250

    # Fake EXE binary content
    with pytest.raises(CsvFormatError, match="Binary file"):
        infer_mapping_and_preview(fixtures / "fake_exe.csv")

    # Missing headers / null bytes / non-UTF8
    bad_empty = tmp_path / "empty.csv"
    bad_empty.write_text("   \n", encoding="utf-8")
    with pytest.raises(CsvFormatError, match="empty"):
        infer_mapping_and_preview(bad_empty)

    bad_headers = tmp_path / "onecol.csv"
    bad_headers.write_text("OnlyOneColumn\nhello\n", encoding="utf-8")
    with pytest.raises(CsvFormatError, match="header row"):
        infer_mapping_and_preview(bad_headers)


@pytest.mark.django_db
def test_import_preview_endpoint_upload_guards(seeded_accounts_and_categories, temp_storage, settings):
    acc_a, _ = seeded_accounts_and_categories
    client, csrf = auth_client(acc_a.id)

    # Missing file -> 400
    res_missing = client.post("/api/v1/import-previews", {}, HTTP_X_CSRF_TOKEN=csrf)
    assert res_missing.status_code == 400

    # Unsupported media type -> 415
    bad_ext = SimpleUploadedFile("payload.pdf", b"%PDF-1.4", content_type="application/pdf")
    res_415 = client.post("/api/v1/import-previews", {"file": bad_ext}, HTTP_X_CSRF_TOKEN=csrf)
    assert res_415.status_code == 415

    # Fake EXE pretending .csv -> 422
    fake_csv = SimpleUploadedFile("fake.csv", b"MZ\x90\x00binary", content_type="text/csv")
    res_422 = client.post("/api/v1/import-previews", {"file": fake_csv}, HTTP_X_CSRF_TOKEN=csrf)
    assert res_422.status_code == 422

    # Over size limit -> 413
    settings.MAX_UPLOAD_BYTES = 30
    big_csv = SimpleUploadedFile(
        "big.csv",
        b"Date,Description,Amount,Currency\n2026-02-01,DEMO CLOUD HOSTING,-25.00,USD\n",
        content_type="text/csv",
    )
    res_413 = client.post("/api/v1/import-previews", {"file": big_csv}, HTTP_X_CSRF_TOKEN=csrf)
    assert res_413.status_code == 413

