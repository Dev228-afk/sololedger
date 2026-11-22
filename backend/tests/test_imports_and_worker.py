from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.imports.models import ImportJob, ImportRow, ImportStatus
from apps.transactions.models import ReviewStatus, Transaction
from tasks.import_tasks import process_import_job, recover_stranded_imports
from tests.conftest import auth_client


@pytest.mark.django_db(transaction=True)
def test_vertical_slice_duplicate_idempotency_and_on_commit(
    seeded_accounts_and_categories, temp_storage, monkeypatch
):
    acc_a, _ = seeded_accounts_and_categories
    client, csrf = auth_client(acc_a.id)

    enqueued_ids: list[str] = []
    monkeypatch.setattr("apps.imports.views.dispatch_import_job", lambda jid: enqueued_ids.append(jid) or True)

    smoke_bytes = (
        Path(__file__).resolve().parents[2] / "fixtures" / "import_edge_cases" / "smoke_5rows.csv"
    ).read_bytes()

    preview_res = client.post(
        "/api/v1/import-previews",
        {"file": SimpleUploadedFile("smoke_5rows.csv", smoke_bytes, content_type="text/csv")},
        HTTP_X_CSRF_TOKEN=csrf,
    )
    assert preview_res.status_code == 201
    prev_data = preview_res.json()

    # 202 + Idempotency-Key deduplication
    create_res_1 = client.post(
        "/api/v1/imports",
        data=json.dumps({"uploadToken": prev_data["uploadToken"], "mapping": prev_data["suggestedMapping"]}),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY="idem-smoke-1",
    )
    assert create_res_1.status_code == 202
    job_id = create_res_1.json()["jobId"]
    assert enqueued_ids == [job_id]

    # Exact replay with same Idempotency-Key returns same job without dispatching twice
    create_res_2 = client.post(
        "/api/v1/imports",
        data=json.dumps({"uploadToken": prev_data["uploadToken"], "mapping": prev_data["suggestedMapping"]}),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY="idem-smoke-1",
    )
    assert create_res_2.status_code == 202
    assert create_res_2.json()["jobId"] == job_id
    assert len(enqueued_ids) == 1

    # Duplicate exact statement SHA-256 on a new uploadToken returns 409 DUPLICATE_IMPORT
    preview_dup = client.post(
        "/api/v1/import-previews",
        {"file": SimpleUploadedFile("smoke_dup.csv", smoke_bytes, content_type="text/csv")},
        HTTP_X_CSRF_TOKEN=csrf,
    )
    dup_res = client.post(
        "/api/v1/imports",
        data=json.dumps({"uploadToken": preview_dup.json()["uploadToken"], "mapping": prev_data["suggestedMapping"]}),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY="idem-smoke-2",
    )
    assert dup_res.status_code == 409
    assert dup_res.json()["error"]["code"] == "DUPLICATE_IMPORT"
    assert dup_res.json()["error"]["details"]["existingImportId"] == job_id

    # Execute Celery worker task + verify duplicate delivery idempotency
    result_1 = process_import_job(job_id)
    assert result_1["validRows"] == 5
    assert result_1["status"] == ImportStatus.AWAITING_REVIEW
    assert Transaction.objects.filter(account=acc_a).count() == 5

    # Duplicate Celery task delivery after completion skips without duplicating rows
    result_dup = process_import_job(job_id)
    assert result_dup["idempotentSkip"] is True
    assert Transaction.objects.filter(account=acc_a).count() == 5


@pytest.mark.django_db(transaction=True)
def test_worker_crash_recovery_broker_outage_and_cooperative_cancel(
    seeded_accounts_and_categories, temp_storage, monkeypatch
):
    acc_a, _ = seeded_accounts_and_categories
    client, csrf = auth_client(acc_a.id)

    # Simulate Redis broker down during POST /imports -> enqueued_at stays None
    monkeypatch.setattr("tasks.import_tasks.process_import_job.delay", lambda *_a, **_k: (_ for _ in ()).throw(ConnectionError("Broker down")))

    smoke_bytes = (
        Path(__file__).resolve().parents[2] / "fixtures" / "import_edge_cases" / "smoke_5rows.csv"
    ).read_bytes()
    prev = client.post(
        "/api/v1/import-previews",
        {"file": SimpleUploadedFile("smoke_crash.csv", smoke_bytes, content_type="text/csv")},
        HTTP_X_CSRF_TOKEN=csrf,
    ).json()
    res = client.post(
        "/api/v1/imports",
        data=json.dumps({"uploadToken": prev["uploadToken"], "mapping": prev["suggestedMapping"]}),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY="idem-broker-outage",
    )
    assert res.status_code == 202
    job_id = res.json()["jobId"]
    job = ImportJob.objects.get(id=job_id)
    assert job.status == ImportStatus.QUEUED
    assert job.enqueued_at is None

    # Broker recovers -> recover_stranded_imports finds stranded QUEUED job
    ImportJob.objects.filter(id=job_id).update(created_at=timezone.now() - dt.timedelta(seconds=30))
    dispatched: list[str] = []
    monkeypatch.setattr("tasks.import_tasks.process_import_job.delay", lambda jid: dispatched.append(jid))
    recovered = recover_stranded_imports(min_age_seconds=10)
    assert recovered == 1
    assert dispatched == [job_id]
    job.refresh_from_db()
    assert job.enqueued_at is not None

    # Simulate worker crash mid-batch after DB commit before task ack
    with pytest.raises(RuntimeError, match="SIMULATED_WORKER_CRASH_AFTER_BATCH"):
        process_import_job(job_id, _fail_after_batch=1)
    assert ImportRow.objects.filter(import_job_id=job_id).count() == 5
    assert Transaction.objects.filter(import_job_id=job_id).count() == 5

    # Safe retry/redelivery completes idempotently with zero duplicate transactions
    res_retry = process_import_job(job_id)
    assert res_retry["validRows"] == 5
    assert Transaction.objects.filter(import_job_id=job_id).count() == 5

    # Cooperative cancel returns 409 once job reached AWAITING_REVIEW -> check cancel on queued job
    dup_csv = (
        Path(__file__).resolve().parents[2] / "fixtures" / "import_edge_cases" / "duplicate_legit_charges.csv"
    ).read_bytes()
    prev2 = client.post(
        "/api/v1/import-previews",
        {"file": SimpleUploadedFile("two_coffees.csv", dup_csv, content_type="text/csv")},
        HTTP_X_CSRF_TOKEN=csrf,
    ).json()
    res2 = client.post(
        "/api/v1/imports",
        data=json.dumps({"uploadToken": prev2["uploadToken"], "mapping": prev2["suggestedMapping"]}),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY="idem-two-coffees",
    )
    job2_id = res2.json()["jobId"]
    # Cancel before worker executes
    c_res = client.post(f"/api/v1/imports/{job2_id}/cancel", data="{}", content_type="application/json", HTTP_X_CSRF_TOKEN=csrf)
    assert c_res.status_code == 202
    assert c_res.json()["status"] == ImportStatus.CANCELED
    # Canceled job skips processing cleanly and 2nd cancel hits 409
    assert process_import_job(job2_id)["status"] == ImportStatus.CANCELED
    assert client.post(f"/api/v1/imports/{job2_id}/cancel", data="{}", content_type="application/json", HTTP_X_CSRF_TOKEN=csrf).status_code == 409


@pytest.mark.django_db(transaction=True)
def test_legitimate_same_day_duplicate_purchases_kept_vs_cross_import_flagged(
    seeded_accounts_and_categories, temp_storage, monkeypatch
):
    acc_a, _ = seeded_accounts_and_categories
    client, csrf = auth_client(acc_a.id)
    monkeypatch.setattr("apps.imports.views.dispatch_import_job", lambda _j: True)

    dup_csv = (
        Path(__file__).resolve().parents[2] / "fixtures" / "import_edge_cases" / "duplicate_legit_charges.csv"
    ).read_bytes()
    prev = client.post(
        "/api/v1/import-previews",
        {"file": SimpleUploadedFile("same_day_coffees.csv", dup_csv, content_type="text/csv")},
        HTTP_X_CSRF_TOKEN=csrf,
    ).json()
    job1_id = client.post(
        "/api/v1/imports",
        data=json.dumps({"uploadToken": prev["uploadToken"], "mapping": prev["suggestedMapping"]}),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=csrf,
    ).json()["jobId"]
    process_import_job(job1_id)
    # Both legitimate identical coffee charges in same statement persist!
    assert Transaction.objects.filter(import_job_id=job1_id).count() == 2

    # Different file sharing identical charge triggers cross-import duplicate_candidate -> NEEDS_REVIEW
    modified_dup = dup_csv + b"2026-02-19,DEMO CLOUD HOSTING,-25.00,USD\n"
    prev2 = client.post(
        "/api/v1/import-previews",
        {"file": SimpleUploadedFile("later_stmt.csv", modified_dup, content_type="text/csv")},
        HTTP_X_CSRF_TOKEN=csrf,
    ).json()
    job2_id = client.post(
        "/api/v1/imports",
        data=json.dumps({"uploadToken": prev2["uploadToken"], "mapping": prev2["suggestedMapping"]}),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN=csrf,
    ).json()["jobId"]
    process_import_job(job2_id)
    flagged = Transaction.objects.filter(import_job_id=job2_id, duplicate_candidate=True)
    assert flagged.count() == 2
    assert all(t.review_status == ReviewStatus.NEEDS_REVIEW for t in flagged)

