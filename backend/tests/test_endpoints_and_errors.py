from __future__ import annotations

import json
import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.auth import verify_signed_session_token
from apps.imports.csv_parser import CsvFormatError, infer_mapping_and_preview, stream_parse_csv
from apps.imports.models import ImportJob, ImportStatus
from apps.transactions.models import Transaction
from tasks.import_tasks import process_import_job
from tests.conftest import auth_client


@pytest.mark.django_db
def test_health_demo_session_categories_and_exception_paths(seeded_accounts_and_categories):
    acc_a, _ = seeded_accounts_and_categories
    client, csrf = auth_client(acc_a.id)

    # /health returns ok
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["dependencies"]["postgres"] == "ok"

    # /demo/accounts + GET /demo/session
    accs = client.get("/api/v1/demo/accounts")
    assert accs.status_code == 200
    assert len(accs.json()["items"]) == 2

    sess = client.get("/api/v1/demo/session")
    assert sess.status_code == 200
    assert sess.json()["account"]["id"] == str(acc_a.id)

    # Fresh unauthenticated session GET
    anon = client.__class__()
    assert anon.get("/api/v1/demo/session").json() == {"account": None, "csrfToken": None}

    # Invalid POST /demo/session 422 & 404
    assert anon.post("/api/v1/demo/session", data="{}", content_type="application/json").status_code == 422
    assert (
        anon.post(
            "/api/v1/demo/session",
            data=json.dumps({"accountId": str(uuid.uuid4())}),
            content_type="application/json",
        ).status_code
        == 404
    )

    # Signed token tamper rejections
    assert verify_signed_session_token(None) is None
    assert verify_signed_session_token("badtoken") is None
    assert verify_signed_session_token("abc.wrongsig") is None

    # Categories list
    cats = client.get("/api/v1/categories")
    assert cats.status_code == 200
    assert len(cats.json()["items"]) == 13


@pytest.mark.django_db(transaction=True)
def test_imports_pagination_retry_bad_tokens_and_worker_failures(
    seeded_accounts_and_categories, temp_storage, monkeypatch
):
    acc_a, _ = seeded_accounts_and_categories
    client, csrf = auth_client(acc_a.id)
    monkeypatch.setattr("apps.imports.views.dispatch_import_job", lambda _j: True)

    # Create 2 different small imports to test cursor pagination + filters
    for idx in range(1, 3):
        blob = f"Date,Description,Amount,Currency\n2026-02-0{idx},DEMO CLOUD HOSTING #{idx}00,-{10 + idx}.00,USD\n".encode()
        prev = client.post(
            "/api/v1/import-previews",
            {"file": SimpleUploadedFile(f"stmt_{idx}.csv", blob, content_type="text/csv")},
            HTTP_X_CSRF_TOKEN=csrf,
        ).json()
        res = client.post(
            "/api/v1/imports",
            data=json.dumps({"uploadToken": prev["uploadToken"], "mapping": prev["suggestedMapping"]}),
            content_type="application/json",
            HTTP_X_CSRF_TOKEN=csrf,
        )
        assert res.status_code == 202
        process_import_job(res.json()["jobId"])

    # Pagination limit=1 + cursor + invalid params
    p1 = client.get("/api/v1/imports?limit=1")
    assert p1.status_code == 200
    assert len(p1.json()["items"]) == 1
    assert p1.json()["nextCursor"] is not None
    p2 = client.get(f"/api/v1/imports?limit=1&cursor={p1.json()['nextCursor']}")
    assert p2.status_code == 200
    assert len(p2.json()["items"]) == 1
    assert client.get("/api/v1/imports?limit=bad").status_code == 400
    assert client.get("/api/v1/imports?limit=99").status_code == 400
    assert client.get("/api/v1/imports?cursor=badcursor").status_code == 400

    # Invalid token / mapping failures on POST /imports
    assert client.post("/api/v1/imports", data="{}", content_type="application/json", HTTP_X_CSRF_TOKEN=csrf).status_code == 422
    assert (
        client.post(
            "/api/v1/imports",
            data=json.dumps({"uploadToken": "not-uuid", "mapping": {}}),
            content_type="application/json",
            HTTP_X_CSRF_TOKEN=csrf,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/imports",
            data=json.dumps({"uploadToken": str(uuid.uuid4()), "mapping": {}}),
            content_type="application/json",
            HTTP_X_CSRF_TOKEN=csrf,
        ).status_code
        == 422
    )

    # Worker missing upload file marks FAILED -> Retry transitions back to QUEUED -> Retry on non-FAILED returns 409
    blob3 = b"Date,Description,Amount,Currency\n2026-02-09,ACME OFFICE SUPPLIES,-15.00,USD\n"
    prev3 = client.post(
        "/api/v1/import-previews",
        {"file": SimpleUploadedFile("stmt_3.csv", blob3, content_type="text/csv")},
        HTTP_X_CSRF_TOKEN=csrf,
    ).json()
    res3 = client.post(
        "/api/v1/imports",
        data=json.dumps({"uploadToken": prev3["uploadToken"], "mapping": prev3["suggestedMapping"]}),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=csrf,
    )
    j3_id = res3.json()["jobId"]
    job3 = ImportJob.objects.get(id=j3_id)
    (temp_storage / job3.upload_key).unlink(missing_ok=True)
    fail_out = process_import_job(j3_id)
    assert fail_out["status"] == ImportStatus.FAILED
    assert fail_out["errorCode"] == "UPLOAD_OBJECT_MISSING"

    # Restore file and retry successfully
    (temp_storage / job3.upload_key).write_bytes(blob3)
    retry_ok = client.post(f"/api/v1/imports/{j3_id}/retry", data="{}", content_type="application/json", HTTP_X_CSRF_TOKEN=csrf)
    assert retry_ok.status_code == 202
    assert process_import_job(j3_id)["status"] == ImportStatus.COMPLETED
    # Retry on COMPLETED -> 409
    assert client.post(f"/api/v1/imports/{j3_id}/retry", data="{}", content_type="application/json", HTTP_X_CSRF_TOKEN=csrf).status_code == 409
    # Nonexistent / malformed UUIDs -> 404
    assert client.get("/api/v1/imports/not-a-uuid").status_code == 404
    assert client.post("/api/v1/imports/not-a-uuid/retry", data="{}", content_type="application/json", HTTP_X_CSRF_TOKEN=csrf).status_code == 404
    assert client.post("/api/v1/imports/not-a-uuid/cancel", data="{}", content_type="application/json", HTTP_X_CSRF_TOKEN=csrf).status_code == 404


@pytest.mark.django_db(transaction=True)
def test_transactions_filters_bulk_conflicts_rules_and_reports_validation(
    seeded_accounts_and_categories, temp_storage, monkeypatch
):
    acc_a, _ = seeded_accounts_and_categories
    client, csrf = auth_client(acc_a.id)
    monkeypatch.setattr("apps.imports.views.dispatch_import_job", lambda _j: True)

    blob = (
        b"Date,Description,Amount,Currency\n"
        b"2026-01-10,DEMO CLOUD HOSTING,-20.00,USD\n"
        b"2026-02-10,NORTHWOOD MART #10,-35.00,USD\n"
        b"2026-02-15,VALLEY OUTPOST #22,-45.00,USD\n"
    )
    prev = client.post(
        "/api/v1/import-previews",
        {"file": SimpleUploadedFile("filters.csv", blob, content_type="text/csv")},
        HTTP_X_CSRF_TOKEN=csrf,
    ).json()
    jid = client.post(
        "/api/v1/imports",
        data=json.dumps({"uploadToken": prev["uploadToken"], "mapping": prev["suggestedMapping"]}),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=csrf,
    ).json()["jobId"]
    process_import_job(jid)

    # Transaction query filters & cursor pagination
    assert client.get("/api/v1/transactions?category=SOFTWARE&from=2026-01-01&to=2026-02-01&q=DEMO").json()["totalCount"] == 1
    page1 = client.get("/api/v1/transactions?limit=1")
    assert page1.status_code == 200 and page1.json()["nextCursor"]
    page2 = client.get(f"/api/v1/transactions?limit=1&cursor={page1.json()['nextCursor']}")
    assert page2.status_code == 200 and len(page2.json()["items"]) == 1

    # Invalid filter params -> 400
    for bad_qs in ("limit=0", "limit=bad", "reviewStatus=NOPE", "from=bad", "to=bad", "cursor=bad"):
        assert client.get(f"/api/v1/transactions?{bad_qs}").status_code == 400

    # Review invalid inputs & bulk mixed accept + conflict
    txns = client.get("/api/v1/transactions").json()["items"]
    t_first = txns[0]
    assert client.patch("/api/v1/transactions/not-uuid/review", data="{}", content_type="application/json", HTTP_X_CSRF_TOKEN=csrf).status_code == 404
    assert client.patch(f"/api/v1/transactions/{t_first['id']}/review", data=json.dumps({"version": 0, "decision": "ACCEPT"}), content_type="application/json", HTTP_X_CSRF_TOKEN=csrf).status_code == 422
    assert client.patch(f"/api/v1/transactions/{t_first['id']}/review", data=json.dumps({"version": 1, "decision": "CHANGE"}), content_type="application/json", HTTP_X_CSRF_TOKEN=csrf).status_code == 422
    assert client.patch(f"/api/v1/transactions/{t_first['id']}/review", data=json.dumps({"version": 1, "decision": "CHANGE", "categoryCode": "NOPE"}), content_type="application/json", HTTP_X_CSRF_TOKEN=csrf).status_code == 422

    # Create rule cleanly then test merchant-rules pagination & 409 / 422 / 404
    client.patch(
        f"/api/v1/transactions/{t_first['id']}/review",
        data=json.dumps({"version": t_first["version"], "decision": "CHANGE", "categoryCode": "EQUIPMENT", "rememberMerchant": True}),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=csrf,
    )
    # Bulk review with one valid + one stale conflict
    bulk = client.post(
        "/api/v1/reviews/bulk",
        data=json.dumps(
            {
                "items": [
                    {"transactionId": t_first["id"], "version": 1, "decision": "ACCEPT"},
                    {"transactionId": txns[1]["id"], "version": txns[1]["version"], "decision": "ACCEPT"},
                    "bad-entry",
                ]
            }
        ),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=csrf,
    )
    assert bulk.status_code == 200
    assert len(bulk.json()["accepted"]) == 1
    assert len(bulk.json()["conflicts"]) == 2
    assert client.post("/api/v1/reviews/bulk", data=json.dumps({"items": []}), content_type="application/json", HTTP_X_CSRF_TOKEN=csrf).status_code == 422

    rules = client.get("/api/v1/merchant-rules?limit=10").json()["items"]
    rule_id = rules[0]["id"]
    assert client.get("/api/v1/merchant-rules?limit=bad").status_code == 400
    assert client.get("/api/v1/merchant-rules?cursor=bad").status_code == 400
    assert client.patch("/api/v1/merchant-rules/bad-id", data="{}", content_type="application/json", HTTP_X_CSRF_TOKEN=csrf).status_code == 404
    assert client.patch(f"/api/v1/merchant-rules/{rule_id}", data=json.dumps({"version": 0}), content_type="application/json", HTTP_X_CSRF_TOKEN=csrf).status_code == 422
    assert client.patch(f"/api/v1/merchant-rules/{rule_id}", data=json.dumps({"version": 99}), content_type="application/json", HTTP_X_CSRF_TOKEN=csrf).status_code == 409
    assert client.patch(f"/api/v1/merchant-rules/{rule_id}", data=json.dumps({"version": 1, "priority": 2000}), content_type="application/json", HTTP_X_CSRF_TOKEN=csrf).status_code == 422
    assert client.patch(f"/api/v1/merchant-rules/{rule_id}", data=json.dumps({"version": 1, "active": False, "priority": 50}), content_type="application/json", HTTP_X_CSRF_TOKEN=csrf).status_code == 200

    # Monthly reports invalid currency / month / >24 months
    assert client.get("/api/v1/reports/monthly?currency=EUR").status_code == 422
    assert client.get("/api/v1/reports/monthly?fromMonth=2026-13").status_code == 400
    assert client.get("/api/v1/reports/monthly?fromMonth=2020-01&toMonth=2026-01").status_code == 422
    assert Transaction.objects.filter(account=acc_a).count() == 3


def test_csv_null_bytes_comma_decimal_and_missing_column(tmp_path):
    null_file = tmp_path / "null.csv"
    null_file.write_bytes(b"Date,Desc,Amount\n\x00bad")
    with pytest.raises(CsvFormatError, match="null bytes"):
        infer_mapping_and_preview(null_file)

    comma_file = tmp_path / "eu_comma.csv"
    comma_file.write_text('Date,Description,Amount,Currency\n2026-02-01,ACME OFFICE SUPPLIES,"-42,85",USD\n', encoding="utf-8")
    _, _, mapping = infer_mapping_and_preview(comma_file)
    mapping["decimalSeparator"] = ","
    parsed = stream_parse_csv(comma_file, mapping)
    assert parsed[0].valid and parsed[0].signed_amount_minor == -4285

    dc_file = tmp_path / "dc_bad.csv"
    dc_file.write_text(
        'Posted Date,Merchant,Debit,Credit\n'
        '2026-02-01,TEST SHOP,"-10,00",\n'
        '2026-02-02,TEST SHOP,,"-5,00"\n'
        '2026-02-03,TEST SHOP,"12,50",\n',
        encoding="utf-8",
    )
    _, _, dc_map = infer_mapping_and_preview(dc_file)
    dc_map["decimalSeparator"] = ","
    parsed_dc = stream_parse_csv(dc_file, dc_map)
    assert parsed_dc[0].error_code == "NEGATIVE_DEBIT_COLUMN"
    assert parsed_dc[1].error_code == "NEGATIVE_CREDIT_COLUMN"
    assert parsed_dc[2].valid and parsed_dc[2].signed_amount_minor == -1250

    missing_col_map = dict(mapping, amountColumn="Nonexistent")
    with pytest.raises(CsvFormatError, match="missing from CSV headers"):
        stream_parse_csv(comma_file, missing_col_map)


@pytest.mark.django_db
def test_exception_handler_drf_paths_and_worker_cancel(seeded_accounts_and_categories, temp_storage):
    from django.core.exceptions import ValidationError as DjangoValidationError
    from rest_framework.exceptions import ValidationError as DrfValidationError

    from apps.accounts.exceptions import sololedger_exception_handler

    acc_a, _ = seeded_accounts_and_categories
    client, csrf = auth_client(acc_a.id)
    assert client.delete("/api/v1/demo/accounts").status_code == 405

    class DummyReq:
        request_id = "req_test_exc"

    res_drf = sololedger_exception_handler(DrfValidationError({"fieldA": ["bad"]}), {"request": DummyReq()})
    assert res_drf is not None and res_drf.status_code == 422
    res_dj = sololedger_exception_handler(DjangoValidationError("django bad"), {"request": DummyReq()})
    assert res_dj is not None and res_dj.status_code == 422

    # Worker skips cleanly if job UUID doesn't exist or file has malformed headers mid-worker
    assert process_import_job(str(uuid.uuid4()))["status"] == "MISSING"
    bad_csv_path = temp_storage / "bad_worker.csv"
    bad_csv_path.write_text("NoHeadersHere", encoding="utf-8")
    bad_job = ImportJob.objects.create(
        account=acc_a,
        upload_key="bad_worker.csv",
        file_sha256="f" * 64,
        original_filename="bad.csv",
        mapping_json={
            "postedDateColumn": "Date",
            "descriptionColumn": "Desc",
            "amountMode": "SIGNED_AMOUNT",
            "amountColumn": "Amt",
            "dateFormat": "%Y-%m-%d",
        },
    )
    out = process_import_job(str(bad_job.id))
    assert out["status"] == ImportStatus.FAILED
    assert out["errorCode"] == "COLUMN_NOT_FOUND"

