from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api_schemas import (
    BulkReviewRequestSerializer,
    BulkReviewResponseSerializer,
    TransactionReviewRequestSerializer,
    TransactionReviewResponseSerializer,
    TransactionsListResponseSerializer,
)
from apps.accounts.auth import SoloLedgerApiError, require_account
from apps.audit.models import AuditEvent
from apps.categorization.models import Category, MerchantCorrection
from apps.imports.models import ImportJob, ImportStatus
from apps.transactions.models import (
    CategorySource,
    ReviewDecision,
    ReviewDecisionType,
    ReviewStatus,
    Transaction,
)
from apps.transactions.money import minor_to_decimal_str


def serialize_transaction(txn: Transaction) -> dict[str, Any]:
    suggestions = list(txn.suggestions.all())
    latest_sug = suggestions[0] if suggestions else None
    return {
        "id": str(txn.id),
        "importJobId": str(txn.import_job_id),
        "postedDate": txn.posted_date.isoformat(),
        "description": txn.description,
        "merchant": txn.normalized_merchant,
        "signedAmount": minor_to_decimal_str(txn.amount_minor),
        "currency": txn.currency,
        "externalRef": txn.external_ref,
        "categoryCode": txn.category.code,
        "categoryName": txn.category.name,
        "categoryKind": txn.category.kind,
        "categorySource": txn.category_source,
        "confidence": f"{txn.confidence:.3f}" if txn.confidence is not None else None,
        "reviewStatus": txn.review_status,
        "duplicateCandidate": txn.duplicate_candidate,
        "explanationCode": latest_sug.explanation_code if latest_sug else None,
        "version": txn.version,
    }


def filter_transactions_queryset(account, params: dict[str, Any]):
    qs = (
        Transaction.objects.filter(account=account)
        .select_related("category")
        .prefetch_related("suggestions")
        .order_by("-posted_date", "-id")
    )
    category = params.get("category")
    if category:
        qs = qs.filter(category__code=str(category).strip().upper())

    review_status = params.get("reviewStatus")
    if review_status:
        rs = str(review_status).strip().upper()
        if rs not in ReviewStatus.values:
            raise SoloLedgerApiError(
                status_code=400,
                code="INVALID_FILTER",
                message="Invalid reviewStatus filter.",
            )
        qs = qs.filter(review_status=rs)

    date_from = params.get("from")
    if date_from:
        try:
            d_from = dt.date.fromisoformat(str(date_from))
        except ValueError as exc:
            raise SoloLedgerApiError(
                status_code=400,
                code="INVALID_FILTER",
                message="Invalid 'from' date; expected YYYY-MM-DD.",
            ) from exc
        qs = qs.filter(posted_date__gte=d_from)

    date_to = params.get("to")
    if date_to:
        try:
            d_to = dt.date.fromisoformat(str(date_to))
        except ValueError as exc:
            raise SoloLedgerApiError(
                status_code=400,
                code="INVALID_FILTER",
                message="Invalid 'to' date; expected YYYY-MM-DD (exclusive end).",
            ) from exc
        qs = qs.filter(posted_date__lt=d_to)

    q = params.get("q")
    if q:
        term = str(q).strip()
        if term:
            qs = qs.filter(Q(description__icontains=term) | Q(normalized_merchant__icontains=term))

    return qs


def apply_single_review(
    *,
    account,
    transaction_id: uuid.UUID,
    expected_version: int,
    decision: str,
    category_code: str | None,
    remember_merchant: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if decision not in {ReviewDecisionType.ACCEPT, ReviewDecisionType.CHANGE}:
        raise SoloLedgerApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="decision must be ACCEPT or CHANGE.",
        )

    with transaction.atomic():
        txn = (
            Transaction.objects.select_for_update()
            .select_related("category", "import_job")
            .filter(id=transaction_id, account=account)
            .first()
        )
        if txn is None:
            raise SoloLedgerApiError(
                status_code=404,
                code="NOT_FOUND",
                message="Transaction not found.",
            )

        if txn.version != expected_version:
            raise SoloLedgerApiError(
                status_code=409,
                code="VERSION_CONFLICT",
                message="This transaction was updated in another request. Refresh to compare.",
                details={
                    "currentVersion": txn.version,
                    "currentCategoryCode": txn.category.code,
                },
            )

        prev_cat = txn.category
        prev_status = txn.review_status

        if decision == ReviewDecisionType.CHANGE:
            if not category_code:
                raise SoloLedgerApiError(
                    status_code=422,
                    code="VALIDATION_ERROR",
                    message="categoryCode is required when decision is CHANGE.",
                    field_errors={"categoryCode": ["Choose a target category."]},
                )
            new_cat = Category.objects.filter(code=str(category_code).strip().upper(), active=True).first()
            if new_cat is None:
                raise SoloLedgerApiError(
                    status_code=422,
                    code="INVALID_CATEGORY",
                    message="Unknown or inactive categoryCode.",
                    field_errors={"categoryCode": ["Select a valid category."]},
                )
        else:
            if category_code:
                new_cat = Category.objects.filter(code=str(category_code).strip().upper(), active=True).first()
                if new_cat is None:
                    raise SoloLedgerApiError(
                        status_code=422,
                        code="INVALID_CATEGORY",
                        message="Unknown or inactive categoryCode.",
                    )
            else:
                new_cat = prev_cat

        dec_row = ReviewDecision.objects.create(
            transaction=txn,
            account=account,
            previous_category=prev_cat,
            new_category=new_cat,
            previous_status=prev_status,
            decision=decision,
        )

        txn.category = new_cat
        txn.category_source = CategorySource.USER_REVIEW
        txn.review_status = ReviewStatus.APPROVED
        txn.duplicate_candidate = False
        txn.version = expected_version + 1
        txn.save(
            update_fields=[
                "category",
                "category_source",
                "review_status",
                "duplicate_candidate",
                "version",
                "updated_at",
            ]
        )

        # Save account-scoped merchant correction ONLY when user explicitly selects rememberMerchant=True
        if remember_merchant:
            existing_rule = (
                MerchantCorrection.objects.select_for_update()
                .filter(account=account, merchant_key=txn.normalized_merchant, active=True)
                .first()
            )
            if existing_rule is not None:
                existing_rule.category = new_cat
                existing_rule.approved_at = timezone.now()
                existing_rule.version += 1
                existing_rule.save(update_fields=["category", "approved_at", "version"])
            else:
                MerchantCorrection.objects.create(
                    account=account,
                    merchant_key=txn.normalized_merchant,
                    category=new_cat,
                    priority=100,
                    active=True,
                )

        # Redacted audit payload (no free-text merchant or statement description stored)
        AuditEvent.objects.create(
            account=account,
            actor=account.display_name,
            entity_type="transaction",
            entity_id=txn.id,
            event_type="TRANSACTION_REVIEWED",
            redacted_detail={
                "decision": decision,
                "newCategoryCode": new_cat.code,
                "rememberMerchant": remember_merchant,
                "version": txn.version,
            },
        )

        job = ImportJob.objects.select_for_update().get(id=txn.import_job_id)
        remaining = Transaction.objects.filter(
            import_job=job,
            review_status=ReviewStatus.NEEDS_REVIEW,
        ).count()
        job.needs_review_count = remaining
        if job.status == ImportStatus.AWAITING_REVIEW and remaining == 0:
            job.status = ImportStatus.COMPLETED
            job.finished_at = job.finished_at or timezone.now()
            job.save(update_fields=["needs_review_count", "status", "finished_at", "updated_at"])
        else:
            job.save(update_fields=["needs_review_count", "updated_at"])

    # Re-fetch with prefetched suggestions so serializer matches GET contract
    refreshed = (
        Transaction.objects.filter(id=txn.id)
        .select_related("category")
        .prefetch_related("suggestions")
        .get()
    )
    decision_payload = {
        "id": str(dec_row.id),
        "transactionId": str(txn.id),
        "previousCategoryCode": prev_cat.code,
        "newCategoryCode": new_cat.code,
        "previousStatus": prev_status,
        "decision": dec_row.decision,
        "createdAt": dec_row.created_at.isoformat(),
    }
    return serialize_transaction(refreshed), decision_payload


class TransactionsListView(APIView):
    @extend_schema(responses={200: TransactionsListResponseSerializer})
    def get(self, request: Request) -> Response:
        account = require_account(request._request)
        limit_raw = request.query_params.get("limit", "50")
        try:
            limit = int(limit_raw)
        except ValueError as exc:
            raise SoloLedgerApiError(
                status_code=400,
                code="INVALID_FILTER",
                message="limit must be an integer between 1 and 100.",
            ) from exc
        if limit < 1 or limit > 100:
            raise SoloLedgerApiError(
                status_code=400,
                code="INVALID_FILTER",
                message="limit must be between 1 and 100.",
            )

        base_qs = filter_transactions_queryset(account, request.query_params)
        total_count = base_qs.count()

        cursor = request.query_params.get("cursor")
        qs = base_qs
        if cursor:
            try:
                date_str, tid_str = cursor.split("|", 1)
                c_date = dt.date.fromisoformat(date_str)
                c_uid = uuid.UUID(tid_str)
                qs = qs.filter(Q(posted_date__lt=c_date) | Q(posted_date=c_date, id__lt=c_uid))
            except Exception as exc:
                raise SoloLedgerApiError(
                    status_code=400,
                    code="INVALID_CURSOR",
                    message="Malformed transactions pagination cursor.",
                ) from exc

        rows = list(qs[: limit + 1])
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = f"{last.posted_date.isoformat()}|{last.id}"
            rows = rows[:limit]

        return Response(
            {
                "items": [serialize_transaction(r) for r in rows],
                "nextCursor": next_cursor,
                "totalCount": total_count,
            }
        )


class TransactionReviewView(APIView):
    @extend_schema(request=TransactionReviewRequestSerializer, responses={200: TransactionReviewResponseSerializer})
    def patch(self, request: Request, transaction_id: str) -> Response:
        account = require_account(request._request, check_csrf=True)
        try:
            uid = uuid.UUID(str(transaction_id))
        except ValueError as exc:
            raise SoloLedgerApiError(status_code=404, code="NOT_FOUND", message="Transaction not found.") from exc

        body = request.data if isinstance(request.data, dict) else {}
        version_raw = body.get("version")
        if not isinstance(version_raw, int) or version_raw < 1:
            raise SoloLedgerApiError(
                status_code=422,
                code="VALIDATION_ERROR",
                message="Positive integer 'version' is required for optimistic locking.",
                field_errors={"version": ["Missing valid version."]},
            )
        decision = str(body.get("decision", "")).upper()
        category_code = body.get("categoryCode")
        remember_merchant = bool(body.get("rememberMerchant", False))

        txn_data, dec_data = apply_single_review(
            account=account,
            transaction_id=uid,
            expected_version=version_raw,
            decision=decision,
            category_code=str(category_code) if category_code else None,
            remember_merchant=remember_merchant,
        )
        return Response({"transaction": txn_data, "reviewDecision": dec_data})


class BulkReviewView(APIView):
    @extend_schema(request=BulkReviewRequestSerializer, responses={200: BulkReviewResponseSerializer})
    def post(self, request: Request) -> Response:
        account = require_account(request._request, check_csrf=True)
        body = request.data if isinstance(request.data, dict) else {}
        items = body.get("items")
        if not isinstance(items, list) or len(items) == 0 or len(items) > 100:
            raise SoloLedgerApiError(
                status_code=422,
                code="VALIDATION_ERROR",
                message="Provide between 1 and 100 review items.",
                field_errors={"items": ["List length must be between 1 and 100."]},
            )

        accepted: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        for entry in items:
            if not isinstance(entry, dict):
                conflicts.append({"code": "INVALID_ITEM", "message": "Malformed review entry."})
                continue
            raw_tid = entry.get("transactionId")
            ver = entry.get("version")
            if not raw_tid or not isinstance(ver, int):
                conflicts.append(
                    {
                        "transactionId": raw_tid,
                        "code": "VALIDATION_ERROR",
                        "message": "transactionId and integer version are required.",
                    }
                )
                continue
            try:
                uid = uuid.UUID(str(raw_tid))
                txn_data, _ = apply_single_review(
                    account=account,
                    transaction_id=uid,
                    expected_version=ver,
                    decision=str(entry.get("decision", "")).upper(),
                    category_code=str(entry["categoryCode"]) if entry.get("categoryCode") else None,
                    remember_merchant=bool(entry.get("rememberMerchant", False)),
                )
                accepted.append(txn_data)
            except SoloLedgerApiError as exc:
                conflicts.append(
                    {
                        "transactionId": str(raw_tid),
                        "code": exc.code,
                        "message": exc.message,
                        "details": exc.details,
                    }
                )

        return Response({"accepted": accepted, "conflicts": conflicts})
