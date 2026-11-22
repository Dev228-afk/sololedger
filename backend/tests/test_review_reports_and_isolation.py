from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.categorization.models import MerchantCorrection
from apps.imports.models import ImportStatus
from apps.transactions.models import CategorySource, ReviewStatus, Transaction
from tasks.import_tasks import process_import_job
from tests.conftest import auth_client


@pytest.mark.django_db(transaction=True)
def test_review_rules_refund_reports_formula_export_and_tenant_isolation(
    seeded_accounts_and_categories, temp_storage, monkeypatch
):
    acc_a, acc_b = seeded_accounts_and_categories
    client_a, csrf_a = auth_client(acc_a.id)
    client_b, csrf_b = auth_client(acc_b.id)
    monkeypatch.setattr("apps.imports.views.dispatch_import_job", lambda _j: True)

    evidence_dir = Path(__file__).resolve().parents[2] / "evidence"
    (evidence_dir / "imports").mkdir(parents=True, exist_ok=True)
    (evidence_dir / "security").mkdir(parents=True, exist_ok=True)

    # Unauth 401 & bad CSRF 403 checks
    unauth = client_a.__class__().get("/api/v1/transactions")
    assert unauth.status_code == 401

    smoke_bytes = (
        Path(__file__).resolve().parents[2] / "fixtures" / "import_edge_cases" / "smoke_5rows.csv"
    ).read_bytes()
    bad_csrf = client_a.post(
        "/api/v1/import-previews",
        {"file": SimpleUploadedFile("s.csv", smoke_bytes, content_type="text/csv")},
        HTTP_X_CSRF_TOKEN="wrong-csrf",
    )
    assert bad_csrf.status_code == 403

    # Account A imports smoke 5 rows
    prev_a = client_a.post(
        "/api/v1/import-previews",
        {"file": SimpleUploadedFile("smoke_5rows.csv", smoke_bytes, content_type="text/csv")},
        HTTP_X_CSRF_TOKEN=csrf_a,
    ).json()
    job_a = client_a.post(
        "/api/v1/imports",
        data=json.dumps({"uploadToken": prev_a["uploadToken"], "mapping": prev_a["suggestedMapping"]}),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=csrf_a,
        HTTP_IDEMPOTENCY_KEY="idem-acc-a-smoke",
    )
    job_a_id = job_a.json()["jobId"]
    process_import_job(job_a_id)

    # Cross-tenant isolation: Account B cannot read Account A import/transactions/rules -> 404
    cross_job = client_b.get(f"/api/v1/imports/{job_a_id}")
    assert cross_job.status_code == 404
    assert client_b.get("/api/v1/transactions").json()["totalCount"] == 0

    # Account A reviews NORTHWOOD MART #402 with rememberMerchant=True, VALLEY OUTPOST #19 with rememberMerchant=False
    review_q = client_a.get("/api/v1/transactions?reviewStatus=NEEDS_REVIEW").json()["items"]
    assert len(review_q) == 2
    nw = next(t for t in review_q if "NORTHWOOD" in t["merchant"])
    vo = next(t for t in review_q if "VALLEY OUTPOST" in t["merchant"])

    # Successful change + rememberMerchant=True
    rev_nw = client_a.patch(
        f"/api/v1/transactions/{nw['id']}/review",
        data=json.dumps(
            {
                "version": nw["version"],
                "decision": "CHANGE",
                "categoryCode": "OFFICE_SUPPLIES",
                "rememberMerchant": True,
            }
        ),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=csrf_a,
    )
    assert rev_nw.status_code == 200
    assert rev_nw.json()["transaction"]["version"] == 2
    assert MerchantCorrection.objects.filter(account=acc_a, merchant_key="NORTHWOOD MART").count() == 1

    # Stale version triggers 409 VERSION_CONFLICT without overwriting
    stale_rev = client_a.patch(
        f"/api/v1/transactions/{nw['id']}/review",
        data=json.dumps({"version": 1, "decision": "CHANGE", "categoryCode": "MEALS"}),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=csrf_a,
    )
    assert stale_rev.status_code == 409
    assert stale_rev.json()["error"]["code"] == "VERSION_CONFLICT"

    # Bulk review remaining NEEDS_REVIEW item resolves parent ImportJob to COMPLETED
    bulk_res = client_a.post(
        "/api/v1/reviews/bulk",
        data=json.dumps(
            {
                "items": [
                    {
                        "transactionId": vo["id"],
                        "version": vo["version"],
                        "decision": "ACCEPT",
                        "rememberMerchant": False,
                    }
                ]
            }
        ),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=csrf_a,
    )
    assert bulk_res.status_code == 200
    assert len(bulk_res.json()["accepted"]) == 1
    assert MerchantCorrection.objects.filter(account=acc_a, merchant_key="VALLEY OUTPOST #19").count() == 0

    job_after = client_a.get(f"/api/v1/imports/{job_a_id}").json()
    assert job_after["status"] == ImportStatus.COMPLETED
    assert job_after["needsReviewCount"] == 0

    # 2nd import for Account A remembers NORTHWOOD MART automatically as USER_RULE / APPROVED!
    second_csv = b"Date,Description,Amount,Currency\n2026-03-01,NORTHWOOD MART #999,-19.25,USD\n"
    prev_2 = client_a.post(
        "/api/v1/import-previews",
        {"file": SimpleUploadedFile("second_import.csv", second_csv, content_type="text/csv")},
        HTTP_X_CSRF_TOKEN=csrf_a,
    ).json()
    job_2_id = client_a.post(
        "/api/v1/imports",
        data=json.dumps({"uploadToken": prev_2["uploadToken"], "mapping": prev_2["suggestedMapping"]}),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=csrf_a,
    ).json()["jobId"]
    process_import_job(job_2_id)
    learned_txn = Transaction.objects.get(import_job_id=job_2_id)
    assert learned_txn.category.code == "OFFICE_SUPPLIES"
    assert learned_txn.category_source == CategorySource.USER_RULE
    assert learned_txn.review_status == ReviewStatus.APPROVED

    # Editing the rule to MARKETING only affects future imports (not already approved past transaction!)
    rule = client_a.get("/api/v1/merchant-rules").json()["items"][0]
    assert client_b.patch(f"/api/v1/merchant-rules/{rule['id']}", data=json.dumps({"version": 1, "active": False}), content_type="application/json", HTTP_X_CSRF_TOKEN=csrf_b).status_code == 404
    rule_upd = client_a.patch(
        f"/api/v1/merchant-rules/{rule['id']}",
        data=json.dumps({"version": rule["version"], "categoryCode": "MARKETING"}),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=csrf_a,
    )
    assert rule_upd.status_code == 200
    learned_txn.refresh_from_db()
    assert learned_txn.category.code == "OFFICE_SUPPLIES"

    # Refund net-negative + formula CSV export check on Account B
    refund_csv = (
        Path(__file__).resolve().parents[2] / "fixtures" / "import_edge_cases" / "refund_net_negative.csv"
    ).read_bytes()
    formula_csv = (
        Path(__file__).resolve().parents[2] / "fixtures" / "import_edge_cases" / "formula_injection.csv"
    ).read_bytes()
    for fname, blob in [("refund.csv", refund_csv), ("formula.csv", formula_csv)]:
        pr = client_b.post(
            "/api/v1/import-previews",
            {"file": SimpleUploadedFile(fname, blob, content_type="text/csv")},
            HTTP_X_CSRF_TOKEN=csrf_b,
        ).json()
        jid = client_b.post(
            "/api/v1/imports",
            data=json.dumps({"uploadToken": pr["uploadToken"], "mapping": pr["suggestedMapping"]}),
            content_type="application/json",
            HTTP_X_CSRF_TOKEN=csrf_b,
        ).json()["jobId"]
        process_import_job(jid)

    # Categorize refund txn to EQUIPMENT so -100 + +150 yields EQUIPMENT netSpend = "-50.00" (negative, unclamped!)
    eq_refund = Transaction.objects.get(account=acc_b, amount_minor=15000)
    client_b.patch(
        f"/api/v1/transactions/{eq_refund.id}/review",
        data=json.dumps({"version": eq_refund.version, "decision": "CHANGE", "categoryCode": "EQUIPMENT"}),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=csrf_b,
    )
    rep_b = client_b.get("/api/v1/reports/monthly?fromMonth=2026-02&toMonth=2026-02&currency=USD").json()
    eq_entry = next(c for c in rep_b["months"][0]["byCategory"] if c["code"] == "EQUIPMENT")
    assert eq_entry["netSpend"] == "-50.00"

    # Formula-safe CSV export keeps numeric signed amount uncorrupted while escaping dangerous text cells
    csv_res = client_b.get("/api/v1/exports/ledger.csv")
    assert csv_res.status_code == 200
    csv_text = b"".join(csv_res.streaming_content).decode("utf-8")
    assert "'=HYPERLINK" in csv_text
    assert "'+CMD" in csv_text
    assert "'-15.00" not in csv_text  # numeric column MUST remain numeric -15.00, NOT '-15.00!
    assert ",-15.00,USD," in csv_text

    # Persist contract & security evidence snapshots cleanly
    (evidence_dir / "imports" / "contract-samples.json").write_text(
        json.dumps(
            {
                "importCreated202": job_a.json(),
                "completedJobDetail": job_after,
                "conflict409": stale_rev.json(),
                "monthlyReportNegativeRefund": rep_b,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (evidence_dir / "security" / "isolation-check.json").write_text(
        json.dumps(
            {
                "unauth401Status": unauth.status_code,
                "csrf403Status": bad_csrf.status_code,
                "crossTenantImport404Status": cross_job.status_code,
                "crossTenantTransactionCount": 0,
                "formulaNeutralizedInExport": True,
                "numericAmountsPreservedInExport": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

