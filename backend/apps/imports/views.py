from __future__ import annotations

import base64
import datetime as dt
import hashlib
import uuid
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api_schemas import (
    ImportAcceptedResponseSerializer,
    ImportCreateRequestSerializer,
    ImportDetailResponseSerializer,
    ImportPreviewResponseSerializer,
    ImportsListResponseSerializer,
)
from apps.accounts.auth import SoloLedgerApiError, require_account
from apps.audit.models import AuditEvent
from apps.imports.csv_parser import (
    CsvFormatError,
    infer_mapping_and_preview,
    validate_mapping_schema,
)
from apps.imports.models import (
    ImportJob,
    ImportRow,
    ImportRowStatus,
    ImportStatus,
    ImportUploadPreview,
)
from apps.imports.serializers import ImportRowErrorSerializer, ImportSummarySerializer
from apps.transactions.models import ReviewStatus, Transaction
from tasks.import_tasks import dispatch_import_job

ALLOWED_CSV_MIME = {
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "text/plain",
    "application/octet-stream",
}


def _phase_label(status_val: str) -> str:
    return {
        ImportStatus.QUEUED: "Queued for worker",
        ImportStatus.VALIDATING: "Validating CSV rows",
        ImportStatus.PROCESSING: "Categorizing transactions",
        ImportStatus.AWAITING_REVIEW: "Awaiting human review",
        ImportStatus.COMPLETED: "Completed",
        ImportStatus.FAILED: "Failed",
        ImportStatus.CANCELED: "Canceled",
    }.get(status_val, status_val)


def _serialize_import_detail(job: ImportJob) -> dict:
    # Derive needsReviewCount live from transactions table so counts never drift
    live_needs_review = Transaction.objects.filter(
        import_job=job,
        review_status=ReviewStatus.NEEDS_REVIEW,
    ).count()
    if job.needs_review_count != live_needs_review:
        job.needs_review_count = live_needs_review
    err_rows = ImportRow.objects.filter(
        import_job=job,
        status=ImportRowStatus.INVALID,
    ).order_by("source_line_no")[:50]
    can_retry = job.status == ImportStatus.FAILED
    can_cancel = job.status in {
        ImportStatus.QUEUED,
        ImportStatus.VALIDATING,
        ImportStatus.PROCESSING,
    } and not job.cancel_requested
    return {
        "jobId": str(job.id),
        "status": job.status,
        "fileName": job.original_filename,
        "fileSha256": job.file_sha256,
        "totalRows": job.total_rows,
        "processedRows": job.processed_rows,
        "validRows": job.valid_rows,
        "invalidRows": job.invalid_rows,
        "needsReviewCount": live_needs_review,
        "attempts": job.attempts,
        "phaseLabel": _phase_label(job.status),
        "errorCode": job.error_code or None,
        "errorMessage": job.error_message or None,
        "canRetry": can_retry,
        "canCancel": can_cancel,
        "startedAt": job.started_at.isoformat() if job.started_at else None,
        "finishedAt": job.finished_at.isoformat() if job.finished_at else None,
        "createdAt": job.created_at.isoformat(),
        "errors": ImportRowErrorSerializer(err_rows, many=True).data,
    }


def _cleanup_expired_previews() -> None:
    expired = ImportUploadPreview.objects.filter(
        expires_at__lt=timezone.now(),
        consumed_at__isnull=True,
    )
    for item in expired:
        p = Path(settings.SOLOLEDGER_STORAGE_DIR) / item.storage_key
        if p.exists():
            p.unlink(missing_ok=True)
    expired.delete()


class ImportPreviewCreateView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(responses={201: ImportPreviewResponseSerializer})
    def post(self, request: Request) -> Response:
        account = require_account(request._request, check_csrf=True)
        _cleanup_expired_previews()

        uploaded = request.FILES.get("file")
        if uploaded is None:
            raise SoloLedgerApiError(
                status_code=400,
                code="BAD_REQUEST",
                message="Multipart field 'file' is required.",
            )

        if uploaded.size is not None and uploaded.size > settings.MAX_UPLOAD_BYTES:
            raise SoloLedgerApiError(
                status_code=413,
                code="FILE_TOO_LARGE",
                message="CSV file exceeds maximum size limit of 10 MB.",
            )

        filename = Path(uploaded.name or "statement.csv").name
        content_type = (uploaded.content_type or "").split(";")[0].strip().lower()
        if not filename.lower().endswith(".csv") or (content_type and content_type not in ALLOWED_CSV_MIME):
            raise SoloLedgerApiError(
                status_code=415,
                code="UNSUPPORTED_MEDIA_TYPE",
                message="Only UTF-8 .csv files are supported.",
            )

        upload_token = uuid.uuid4()
        storage_key = f"preview_{upload_token}.csv"
        dest_path = (Path(settings.SOLOLEDGER_STORAGE_DIR) / storage_key).resolve()
        hasher = hashlib.sha256()
        total_bytes = 0

        try:
            with dest_path.open("wb") as handle:
                for chunk in uploaded.chunks():
                    total_bytes += len(chunk)
                    if total_bytes > settings.MAX_UPLOAD_BYTES:
                        raise SoloLedgerApiError(
                            status_code=413,
                            code="FILE_TOO_LARGE",
                            message="CSV file exceeds maximum size limit of 10 MB.",
                        )
                    hasher.update(chunk)
                    handle.write(chunk)

            headers, preview_rows, suggested = infer_mapping_and_preview(dest_path)
        except CsvFormatError as exc:
            dest_path.unlink(missing_ok=True)
            raise SoloLedgerApiError(
                status_code=422,
                code=exc.code,
                message=exc.message,
            ) from exc
        except SoloLedgerApiError:
            dest_path.unlink(missing_ok=True)
            raise

        sha256_hex = hasher.hexdigest()
        expires_at = timezone.now() + dt.timedelta(hours=24)
        ImportUploadPreview.objects.create(
            upload_token=upload_token,
            account=account,
            storage_key=storage_key,
            original_filename=filename[:255],
            file_sha256=sha256_hex,
            file_size=total_bytes,
            expires_at=expires_at,
        )

        return Response(
            {
                "uploadToken": str(upload_token),
                "fileName": filename,
                "sha256": sha256_hex,
                "headers": headers,
                "previewRows": preview_rows,
                "suggestedMapping": suggested,
                "expiresAt": expires_at.isoformat(),
            },
            status=201,
        )


class ImportsCollectionView(APIView):
    parser_classes = [JSONParser]

    @extend_schema(operation_id="imports_list", responses={200: ImportsListResponseSerializer})
    def get(self, request: Request) -> Response:
        account = require_account(request._request)
        limit_raw = request.query_params.get("limit", "20")
        try:
            limit = int(limit_raw)
        except ValueError as exc:
            raise SoloLedgerApiError(
                status_code=400,
                code="INVALID_FILTER",
                message="limit must be an integer between 1 and 50.",
            ) from exc
        if limit < 1 or limit > 50:
            raise SoloLedgerApiError(
                status_code=400,
                code="INVALID_FILTER",
                message="limit must be between 1 and 50.",
            )

        qs = ImportJob.objects.filter(account=account).order_by("-created_at", "-id")
        cursor = request.query_params.get("cursor")
        if cursor:
            try:
                pad = "=" * (-len(cursor) % 4)
                decoded = base64.urlsafe_b64decode(f"{cursor}{pad}".encode("ascii")).decode("utf-8")
                ts_str, cid = decoded.split("|", 1)
                ts_val = dt.datetime.fromisoformat(ts_str)
                qs = qs.filter(created_at__lt=ts_val) | ImportJob.objects.filter(
                    account=account, created_at=ts_val, id__lt=uuid.UUID(cid)
                )
            except Exception as exc:
                raise SoloLedgerApiError(
                    status_code=400,
                    code="INVALID_CURSOR",
                    message="Malformed pagination cursor.",
                ) from exc

        rows = list(qs[: limit + 1])
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            raw_cur = f"{last.created_at.isoformat()}|{last.id}".encode()
            next_cursor = base64.urlsafe_b64encode(raw_cur).decode("ascii").rstrip("=")
            rows = rows[:limit]

        # Reconcile live needsReviewCount before serialization
        for row in rows:
            row.needs_review_count = Transaction.objects.filter(
                import_job=row,
                review_status=ReviewStatus.NEEDS_REVIEW,
            ).count()

        return Response(
            {
                "items": ImportSummarySerializer(rows, many=True).data,
                "nextCursor": next_cursor,
            }
        )

    @extend_schema(request=ImportCreateRequestSerializer, responses={202: ImportAcceptedResponseSerializer})
    def post(self, request: Request) -> Response:
        account = require_account(request._request, check_csrf=True)
        body = request.data if isinstance(request.data, dict) else {}
        idempotency_key = request.headers.get("Idempotency-Key") or request.META.get("HTTP_IDEMPOTENCY_KEY")
        if idempotency_key is not None:
            idempotency_key = idempotency_key.strip()[:128] or None

        if idempotency_key:
            prior = ImportJob.objects.filter(account=account, idempotency_key=idempotency_key).first()
            if prior is not None:
                return Response(
                    {
                        "jobId": str(prior.id),
                        "status": prior.status,
                        "statusUrl": f"/api/v1/imports/{prior.id}",
                    },
                    status=202,
                )

        upload_token = body.get("uploadToken")
        mapping = body.get("mapping")
        if not upload_token or not isinstance(mapping, dict):
            raise SoloLedgerApiError(
                status_code=422,
                code="VALIDATION_ERROR",
                message="uploadToken and mapping are required.",
            )

        try:
            token_uuid = uuid.UUID(str(upload_token))
        except ValueError as exc:
            raise SoloLedgerApiError(
                status_code=422,
                code="INVALID_UPLOAD_TOKEN",
                message="Invalid uploadToken format.",
            ) from exc

        preview = ImportUploadPreview.objects.filter(
            upload_token=token_uuid,
            account=account,
        ).first()
        if preview is None:
            raise SoloLedgerApiError(
                status_code=422,
                code="INVALID_UPLOAD_TOKEN",
                message="Upload token not found for active account.",
            )
        if preview.consumed_at is not None or preview.expires_at < timezone.now():
            raise SoloLedgerApiError(
                status_code=422,
                code="EXPIRED_UPLOAD_TOKEN",
                message="Upload preview token has expired or already been used.",
            )

        mapping_errors = validate_mapping_schema(mapping)
        if mapping_errors:
            raise SoloLedgerApiError(
                status_code=422,
                code="INVALID_MAPPING",
                message="Column mapping requires explicit valid fields.",
                field_errors=mapping_errors,
            )

        dup = (
            ImportJob.objects.filter(account=account, file_sha256=preview.file_sha256)
            .exclude(status__in=[ImportStatus.FAILED, ImportStatus.CANCELED])
            .first()
        )
        if dup is not None:
            raise SoloLedgerApiError(
                status_code=409,
                code="DUPLICATE_IMPORT",
                message="This exact statement is already imported for your account.",
                details={"existingImportId": str(dup.id)},
            )

        try:
            with transaction.atomic():
                job = ImportJob.objects.create(
                    account=account,
                    upload_key=preview.storage_key,
                    file_sha256=preview.file_sha256,
                    original_filename=preview.original_filename,
                    status=ImportStatus.QUEUED,
                    idempotency_key=idempotency_key,
                    mapping_json=mapping,
                )
                preview.consumed_at = timezone.now()
                preview.save(update_fields=["consumed_at"])
                AuditEvent.objects.create(
                    account=account,
                    actor=account.display_name,
                    entity_type="import_job",
                    entity_id=job.id,
                    event_type="IMPORT_QUEUED",
                    redacted_detail={"fileSha256": job.file_sha256},
                )
                job_id_str = str(job.id)
                transaction.on_commit(lambda: dispatch_import_job(job_id_str))
        except IntegrityError:
            if idempotency_key:
                prior = ImportJob.objects.filter(account=account, idempotency_key=idempotency_key).first()
                if prior is not None:
                    return Response(
                        {
                            "jobId": str(prior.id),
                            "status": prior.status,
                            "statusUrl": f"/api/v1/imports/{prior.id}",
                        },
                        status=202,
                    )
            raise

        return Response(
            {
                "jobId": str(job.id),
                "status": job.status,
                "statusUrl": f"/api/v1/imports/{job.id}",
            },
            status=202,
        )


class ImportDetailView(APIView):
    @extend_schema(operation_id="imports_retrieve", responses={200: ImportDetailResponseSerializer})
    def get(self, request: Request, job_id: str) -> Response:
        account = require_account(request._request)
        try:
            uid = uuid.UUID(str(job_id))
        except ValueError as exc:
            raise SoloLedgerApiError(status_code=404, code="NOT_FOUND", message="Import job not found.") from exc
        job = ImportJob.objects.filter(id=uid, account=account).first()
        if job is None:
            raise SoloLedgerApiError(status_code=404, code="NOT_FOUND", message="Import job not found.")
        return Response(_serialize_import_detail(job))


class ImportRetryView(APIView):
    @extend_schema(request=None, responses={202: ImportAcceptedResponseSerializer})
    def post(self, request: Request, job_id: str) -> Response:
        account = require_account(request._request, check_csrf=True)
        try:
            uid = uuid.UUID(str(job_id))
        except ValueError as exc:
            raise SoloLedgerApiError(status_code=404, code="NOT_FOUND", message="Import job not found.") from exc

        with transaction.atomic():
            job = ImportJob.objects.select_for_update().filter(id=uid, account=account).first()
            if job is None:
                raise SoloLedgerApiError(status_code=404, code="NOT_FOUND", message="Import job not found.")
            if job.status != ImportStatus.FAILED:
                raise SoloLedgerApiError(
                    status_code=409,
                    code="INVALID_STATE_TRANSITION",
                    message=f"Import job in status {job.status} cannot be retried.",
                )
            job.status = ImportStatus.QUEUED
            job.error_code = ""
            job.error_message = ""
            job.enqueued_at = None
            job.cancel_requested = False
            job.save(
                update_fields=[
                    "status",
                    "error_code",
                    "error_message",
                    "enqueued_at",
                    "cancel_requested",
                    "updated_at",
                ]
            )
            AuditEvent.objects.create(
                account=account,
                actor=account.display_name,
                entity_type="import_job",
                entity_id=job.id,
                event_type="IMPORT_RETRIED",
                redacted_detail={"attempt": job.attempts + 1},
            )
            job_id_str = str(job.id)
            transaction.on_commit(lambda: dispatch_import_job(job_id_str))
        return Response({"jobId": str(job.id), "status": ImportStatus.QUEUED}, status=202)


class ImportCancelView(APIView):
    @extend_schema(request=None, responses={202: ImportAcceptedResponseSerializer})
    def post(self, request: Request, job_id: str) -> Response:
        account = require_account(request._request, check_csrf=True)
        try:
            uid = uuid.UUID(str(job_id))
        except ValueError as exc:
            raise SoloLedgerApiError(status_code=404, code="NOT_FOUND", message="Import job not found.") from exc

        reason = ""
        if isinstance(request.data, dict) and request.data.get("reason"):
            reason = str(request.data["reason"])[:200]

        with transaction.atomic():
            job = ImportJob.objects.select_for_update().filter(id=uid, account=account).first()
            if job is None:
                raise SoloLedgerApiError(status_code=404, code="NOT_FOUND", message="Import job not found.")
            if job.status in {ImportStatus.COMPLETED, ImportStatus.FAILED, ImportStatus.CANCELED}:
                raise SoloLedgerApiError(
                    status_code=409,
                    code="INVALID_STATE_TRANSITION",
                    message=f"Import job is already terminal ({job.status}).",
                )
            job.cancel_requested = True
            job.cancel_reason = reason
            if job.status in {ImportStatus.QUEUED, ImportStatus.AWAITING_REVIEW}:
                job.status = ImportStatus.CANCELED
                job.finished_at = timezone.now()
            job.save(update_fields=["cancel_requested", "cancel_reason", "status", "finished_at", "updated_at"])
            AuditEvent.objects.create(
                account=account,
                actor=account.display_name,
                entity_type="import_job",
                entity_id=job.id,
                event_type="IMPORT_CANCEL_REQUESTED",
                redacted_detail={"status": job.status},
            )
        return Response({"jobId": str(job.id), "status": job.status}, status=202)
