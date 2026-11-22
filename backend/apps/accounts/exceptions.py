from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError as DrfValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

from .auth import SoloLedgerApiError


def sololedger_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    request = context.get("request")
    raw_request = getattr(request, "_request", request)
    request_id = getattr(raw_request, "request_id", "req_unknown")

    if isinstance(exc, SoloLedgerApiError):
        return Response(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "requestId": request_id,
                    "details": exc.details,
                    "fieldErrors": exc.field_errors,
                }
            },
            status=exc.status_code,
        )

    if isinstance(exc, DrfValidationError):
        field_errors: dict[str, list[str]] = {}
        detail = exc.detail
        if isinstance(detail, dict):
            for key, val in detail.items():
                if isinstance(val, list):
                    field_errors[str(key)] = [str(v) for v in val]
                else:
                    field_errors[str(key)] = [str(val)]
        elif isinstance(detail, list):
            field_errors["nonField"] = [str(v) for v in detail]
        else:
            field_errors["nonField"] = [str(detail)]
        return Response(
            {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed.",
                    "requestId": request_id,
                    "details": {},
                    "fieldErrors": field_errors,
                }
            },
            status=422,
        )

    if isinstance(exc, DjangoValidationError):
        return Response(
            {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": str(exc),
                    "requestId": request_id,
                    "details": {},
                    "fieldErrors": {},
                }
            },
            status=422,
        )

    response = exception_handler(exc, context)
    if response is not None:
        return Response(
            {
                "error": {
                    "code": f"HTTP_{response.status_code}",
                    "message": str(response.data.get("detail", "Request failed."))
                    if isinstance(response.data, dict)
                    else "Request failed.",
                    "requestId": request_id,
                    "details": {},
                    "fieldErrors": {},
                }
            },
            status=response.status_code,
        )
    return None

