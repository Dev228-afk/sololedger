from __future__ import annotations

import uuid
from typing import Any

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api_schemas import (
    CategoriesListResponseSerializer,
    MerchantRulePatchRequestSerializer,
    MerchantRulePatchResponseSerializer,
    MerchantRulesListResponseSerializer,
)
from apps.accounts.auth import SoloLedgerApiError, require_account
from apps.audit.models import AuditEvent
from apps.categorization.models import Category, MerchantCorrection


def serialize_rule(rule: MerchantCorrection) -> dict[str, Any]:
    return {
        "id": str(rule.id),
        "merchantKey": rule.merchant_key,
        "categoryCode": rule.category.code,
        "categoryName": rule.category.name,
        "priority": rule.priority,
        "active": rule.active,
        "approvedAt": rule.approved_at.isoformat(),
        "version": rule.version,
    }


class CategoriesListView(APIView):
    @extend_schema(responses={200: CategoriesListResponseSerializer})
    def get(self, request: Request) -> Response:
        cats = Category.objects.filter(active=True).order_by("sort_order", "code")
        return Response(
            {
                "items": [
                    {
                        "id": str(c.id),
                        "code": c.code,
                        "name": c.name,
                        "kind": c.kind,
                        "sortOrder": c.sort_order,
                    }
                    for c in cats
                ]
            }
        )


class MerchantRulesListView(APIView):
    @extend_schema(responses={200: MerchantRulesListResponseSerializer})
    def get(self, request: Request) -> Response:
        account = require_account(request._request)
        limit_raw = request.query_params.get("limit", "50")
        try:
            limit = max(1, min(100, int(limit_raw)))
        except ValueError as exc:
            raise SoloLedgerApiError(
                status_code=400,
                code="INVALID_FILTER",
                message="limit must be an integer.",
            ) from exc

        qs = (
            MerchantCorrection.objects.filter(account=account)
            .select_related("category")
            .order_by("priority", "merchant_key", "id")
        )
        offset = 0
        cursor = request.query_params.get("cursor")
        if cursor:
            try:
                offset = max(0, int(cursor))
            except ValueError as exc:
                raise SoloLedgerApiError(
                    status_code=400,
                    code="INVALID_CURSOR",
                    message="Malformed merchant rules cursor.",
                ) from exc

        rows = list(qs[offset : offset + limit + 1])
        next_cursor = str(offset + limit) if len(rows) > limit else None
        rows = rows[:limit]
        return Response(
            {
                "items": [serialize_rule(r) for r in rows],
                "nextCursor": next_cursor,
            }
        )


class MerchantRuleDetailView(APIView):
    @extend_schema(request=MerchantRulePatchRequestSerializer, responses={200: MerchantRulePatchResponseSerializer})
    def patch(self, request: Request, rule_id: str) -> Response:
        account = require_account(request._request, check_csrf=True)
        try:
            uid = uuid.UUID(str(rule_id))
        except ValueError as exc:
            raise SoloLedgerApiError(status_code=404, code="NOT_FOUND", message="Merchant rule not found.") from exc

        body = request.data if isinstance(request.data, dict) else {}
        expected_version = body.get("version")
        if not isinstance(expected_version, int) or expected_version < 1:
            raise SoloLedgerApiError(
                status_code=422,
                code="VALIDATION_ERROR",
                message="Positive integer 'version' is required.",
                field_errors={"version": ["Missing valid version."]},
            )

        with transaction.atomic():
            rule = (
                MerchantCorrection.objects.select_for_update()
                .select_related("category")
                .filter(id=uid, account=account)
                .first()
            )
            if rule is None:
                raise SoloLedgerApiError(
                    status_code=404,
                    code="NOT_FOUND",
                    message="Merchant rule not found.",
                )
            if rule.version != expected_version:
                raise SoloLedgerApiError(
                    status_code=409,
                    code="VERSION_CONFLICT",
                    message="Merchant rule was modified concurrently. Refresh to continue.",
                    details={"currentVersion": rule.version},
                )

            if "categoryCode" in body and body["categoryCode"] is not None:
                cat = Category.objects.filter(code=str(body["categoryCode"]).strip().upper(), active=True).first()
                if cat is None:
                    raise SoloLedgerApiError(
                        status_code=422,
                        code="INVALID_CATEGORY",
                        message="Unknown categoryCode.",
                    )
                rule.category = cat

            if "active" in body and body["active"] is not None:
                rule.active = bool(body["active"])

            if "priority" in body and body["priority"] is not None:
                if not isinstance(body["priority"], int) or body["priority"] < 1 or body["priority"] > 1000:
                    raise SoloLedgerApiError(
                        status_code=422,
                        code="VALIDATION_ERROR",
                        message="priority must be between 1 and 1000.",
                    )
                rule.priority = body["priority"]

            rule.version = expected_version + 1
            rule.save(update_fields=["category", "active", "priority", "version"])
            AuditEvent.objects.create(
                account=account,
                actor=account.display_name,
                entity_type="merchant_correction",
                entity_id=rule.id,
                event_type="MERCHANT_RULE_UPDATED",
                redacted_detail={
                    "categoryCode": rule.category.code,
                    "active": rule.active,
                    "priority": rule.priority,
                    "version": rule.version,
                },
            )

        return Response({"rule": serialize_rule(rule)})
