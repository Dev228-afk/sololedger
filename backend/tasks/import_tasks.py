from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.categorization.models import Category, MerchantCorrection
from apps.imports.csv_parser import CsvFormatError, ParsedRowResult, stream_parse_csv
from apps.imports.models import ImportJob, ImportRow, ImportRowStatus, ImportStatus
from apps.transactions.models import (
    ClassificationSuggestion,
    ReviewStatus,
    Transaction,
)
from classification.confidence import normalize_merchant
from classification.langchain_adapter import LangChainCategorizerAdapter

logger = logging.getLogger("sololedger.tasks")


def dispatch_import_job(job_id: str) -> bool:
    """Best-effort dispatch executed ONLY inside transaction.on_commit. Returns False if broker unavailable."""
    try:
        process_import_job.delay(job_id)
        ImportJob.objects.filter(id=job_id).update(enqueued_at=timezone.now())
        return True
    except Exception as exc:
        logger.warning("celery.dispatch_deferred job_id=%s err=%s", job_id, type(exc).__name__)
        return False


def _detect_cross_import_duplicate(
    *,
    account_id,
    import_job_id,
    posted_date: dt.date,
    normalized_merchant: str,
    amount_minor: int,
    external_ref: str | None,
) -> bool:
    if external_ref:
        if (
            Transaction.objects.filter(account_id=account_id, external_ref=external_ref)
            .exclude(import_job_id=import_job_id)
            .exists()
        ):
            return True
    return (
        Transaction.objects.filter(
            account_id=account_id,
            posted_date=posted_date,
            normalized_merchant=normalized_merchant,
            amount_minor=amount_minor,
        )
        .exclude(import_job_id=import_job_id)
        .exists()
    )


@shared_task(bind=True, max_retries=3, acks_late=True)
def process_import_job(self, job_id: str, *, _fail_after_batch: int | None = None) -> dict:
    """
    Idempotent background CSV processing pipeline:
    VALIDATING -> stream parse -> upsert ImportRows -> batched classify & persist Transactions -> AWAITING_REVIEW|COMPLETED.
    Never holds a DB transaction open during provider classification calls.
    """
    with transaction.atomic():
        job = ImportJob.objects.select_for_update().filter(id=job_id).first()
        if job is None:
            return {"status": "MISSING"}
        if job.status in {
            ImportStatus.AWAITING_REVIEW,
            ImportStatus.COMPLETED,
            ImportStatus.CANCELED,
        }:
            return {"status": job.status, "idempotentSkip": True}
        if job.cancel_requested:
            job.status = ImportStatus.CANCELED
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "finished_at", "updated_at"])
            return {"status": ImportStatus.CANCELED}

        job.status = ImportStatus.VALIDATING
        job.attempts += 1
        job.started_at = job.started_at or timezone.now()
        job.save(update_fields=["status", "attempts", "started_at", "updated_at"])

    csv_path = (Path(settings.SOLOLEDGER_STORAGE_DIR) / job.upload_key).resolve()
    if not csv_path.exists():
        ImportJob.objects.filter(id=job.id).update(
            status=ImportStatus.FAILED,
            error_code="UPLOAD_OBJECT_MISSING",
            error_message="Uploaded statement file is missing from storage.",
            finished_at=timezone.now(),
        )
        return {"status": ImportStatus.FAILED, "errorCode": "UPLOAD_OBJECT_MISSING"}

    try:
        parsed_rows: list[ParsedRowResult] = stream_parse_csv(csv_path, job.mapping_json)
    except CsvFormatError as exc:
        ImportJob.objects.filter(id=job.id).update(
            status=ImportStatus.FAILED,
            error_code=exc.code,
            error_message=exc.message[:300],
            finished_at=timezone.now(),
        )
        return {"status": ImportStatus.FAILED, "errorCode": exc.code}

    # Step 1: Upsert ImportRows idempotently by unique (import_job, source_line_no)
    valid_row_objs: list[ImportRow] = []
    invalid_count = 0
    with transaction.atomic():
        for parsed in parsed_rows:
            row_status = ImportRowStatus.VALID if parsed.valid else ImportRowStatus.INVALID
            imp_row, created = ImportRow.objects.get_or_create(
                import_job=job,
                source_line_no=parsed.source_line_no,
                defaults={
                    "raw_hash": parsed.raw_hash,
                    "normalized_description": parsed.description,
                    "posted_date": parsed.posted_date,
                    "signed_amount_minor": parsed.signed_amount_minor,
                    "currency": parsed.currency,
                    "source_txn_id": parsed.source_txn_id,
                    "status": row_status,
                    "error_code": parsed.error_code,
                    "error_detail": parsed.error_detail[:240],
                },
            )
            if not parsed.valid:
                invalid_count += 1
            else:
                valid_row_objs.append(imp_row)

        job.refresh_from_db()
        if job.cancel_requested:
            job.status = ImportStatus.CANCELED
            job.total_rows = len(parsed_rows)
            job.invalid_rows = invalid_count
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "total_rows", "invalid_rows", "finished_at", "updated_at"])
            return {"status": ImportStatus.CANCELED}

        job.status = ImportStatus.PROCESSING
        job.total_rows = len(parsed_rows)
        job.invalid_rows = invalid_count
        job.valid_rows = len(valid_row_objs)
        job.save(update_fields=["status", "total_rows", "invalid_rows", "valid_rows", "updated_at"])

    categories_by_code = {c.code: c for c in Category.objects.filter(active=True)}
    adapter = LangChainCategorizerAdapter(allowed_categories=categories_by_code.keys())
    merchant_rules = {
        r.merchant_key: r.category.code
        for r in MerchantCorrection.objects.select_related("category").filter(
            account_id=job.account_id,
            active=True,
        )
    }

    batch_size = 100
    for batch_idx, start in enumerate(range(0, len(valid_row_objs), batch_size), start=1):
        # Re-check cancellation before classifying & committing each batch
        job.refresh_from_db()
        if job.cancel_requested:
            job.status = ImportStatus.CANCELED
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "finished_at", "updated_at"])
            return {"status": ImportStatus.CANCELED}

        chunk = valid_row_objs[start : start + batch_size]

        # Classify chunk outside open database write lock
        prepared = []
        for imp_row in chunk:
            if Transaction.objects.filter(import_row=imp_row).exists():
                continue
            norm_m = normalize_merchant(imp_row.normalized_description)
            is_dup = _detect_cross_import_duplicate(
                account_id=job.account_id,
                import_job_id=job.id,
                posted_date=imp_row.posted_date,
                normalized_merchant=norm_m,
                amount_minor=int(imp_row.signed_amount_minor or 0),
                external_ref=imp_row.source_txn_id,
            )
            outcome = adapter.classify(
                description=imp_row.normalized_description,
                amount_minor=int(imp_row.signed_amount_minor or 0),
                merchant_rules=merchant_rules,
                duplicate_candidate=is_dup,
            )
            prepared.append((imp_row, outcome, is_dup))

        with transaction.atomic():
            for imp_row, outcome, is_dup in prepared:
                if is_dup and imp_row.status != ImportRowStatus.DUPLICATE_CANDIDATE:
                    imp_row.status = ImportRowStatus.DUPLICATE_CANDIDATE
                    imp_row.save(update_fields=["status"])
                cat_obj = categories_by_code.get(outcome.category_code) or categories_by_code["UNCATEGORIZED"]
                try:
                    txn, created = Transaction.objects.get_or_create(
                        account_id=job.account_id,
                        import_row=imp_row,
                        defaults={
                            "import_job": job,
                            "posted_date": imp_row.posted_date,
                            "description": imp_row.normalized_description,
                            "normalized_merchant": outcome.normalized_merchant,
                            "amount_minor": int(imp_row.signed_amount_minor or 0),
                            "currency": "USD",
                            "external_ref": imp_row.source_txn_id,
                            "category": cat_obj,
                            "category_source": outcome.category_source,
                            "confidence": outcome.confidence,
                            "review_status": outcome.review_status,
                            "duplicate_candidate": is_dup,
                        },
                    )
                    if created:
                        ClassificationSuggestion.objects.create(
                            transaction=txn,
                            suggested_category=cat_obj,
                            confidence=outcome.confidence,
                            method=outcome.method,
                            rule_version=outcome.rule_version,
                            model_version=outcome.model_version,
                            explanation_code=outcome.explanation_code,
                        )
                except IntegrityError:
                    # Idempotent duplicate delivery guard on (account, import_row)
                    pass

            done_txns = Transaction.objects.filter(import_job=job).count()
            needs_review = Transaction.objects.filter(
                import_job=job,
                review_status=ReviewStatus.NEEDS_REVIEW,
            ).count()
            job.processed_rows = min(job.total_rows, done_txns + invalid_count)
            job.needs_review_count = needs_review
            job.save(update_fields=["processed_rows", "needs_review_count", "updated_at"])

        if _fail_after_batch is not None and batch_idx >= _fail_after_batch:
            raise RuntimeError("SIMULATED_WORKER_CRASH_AFTER_BATCH")

    with transaction.atomic():
        job = ImportJob.objects.select_for_update().get(id=job.id)
        if job.cancel_requested:
            job.status = ImportStatus.CANCELED
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "finished_at", "updated_at"])
            return {"status": ImportStatus.CANCELED}

        needs_review = Transaction.objects.filter(
            import_job=job,
            review_status=ReviewStatus.NEEDS_REVIEW,
        ).count()
        job.processed_rows = job.total_rows
        job.needs_review_count = needs_review
        job.status = ImportStatus.AWAITING_REVIEW if needs_review > 0 else ImportStatus.COMPLETED
        job.finished_at = timezone.now()
        job.save(
            update_fields=[
                "processed_rows",
                "needs_review_count",
                "status",
                "finished_at",
                "updated_at",
            ]
        )
        AuditEvent.objects.create(
            account_id=job.account_id,
            actor="worker:sololedger",
            entity_type="import_job",
            entity_id=job.id,
            event_type=f"IMPORT_{job.status}",
            redacted_detail={
                "validRows": job.valid_rows,
                "invalidRows": job.invalid_rows,
                "needsReviewCount": needs_review,
            },
        )
    return {
        "status": job.status,
        "validRows": job.valid_rows,
        "invalidRows": job.invalid_rows,
        "needsReviewCount": needs_review,
    }


@shared_task
def recover_stranded_imports(*, min_age_seconds: int = 10) -> int:
    """Periodic dispatch-recovery scan re-enqueueing QUEUED jobs stranded during broker outages."""
    cutoff = timezone.now() - dt.timedelta(seconds=min_age_seconds)
    stranded = list(
        ImportJob.objects.filter(
            status=ImportStatus.QUEUED,
            enqueued_at__isnull=True,
            cancel_requested=False,
            created_at__lte=cutoff,
        ).order_by("created_at")[:50]
    )
    recovered = 0
    for job in stranded:
        if dispatch_import_job(str(job.id)):
            recovered += 1
    return recovered

