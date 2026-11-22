from __future__ import annotations

from django.conf import settings
from django.db import connection
from drf_spectacular.utils import extend_schema
from redis import Redis
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .api_schemas import (
    DemoAccountsListResponseSerializer,
    DemoSessionRequestSerializer,
    DemoSessionResponseSerializer,
    HealthResponseSerializer,
)
from .auth import SESSION_COOKIE_NAME, SoloLedgerApiError, create_signed_session_token
from .models import Account


class DemoAccountSerializer(serializers.ModelSerializer):
    displayName = serializers.CharField(source="display_name")

    class Meta:
        model = Account
        fields = ["id", "displayName", "timezone"]


class HealthView(APIView):
    @extend_schema(responses={200: HealthResponseSerializer})
    def get(self, request: Request) -> Response:
        db_ok = False
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
                db_ok = cur.fetchone() is not None
        except Exception:
            db_ok = False

        redis_ok = False
        try:
            client = Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=1, socket_timeout=1)
            redis_ok = bool(client.ping())
            client.close()
        except Exception:
            redis_ok = False

        status_text = "ok" if db_ok else "degraded"
        return Response(
            {
                "status": status_text,
                "version": settings.SOLOLEDGER_VERSION,
                "dependencies": {
                    "postgres": "ok" if db_ok else "unavailable",
                    "redis": "ok" if redis_ok else "unavailable",
                },
            },
            status=200 if db_ok else 503,
        )


class DemoAccountsListView(APIView):
    @extend_schema(responses={200: DemoAccountsListResponseSerializer})
    def get(self, request: Request) -> Response:
        accounts = Account.objects.order_by("created_at", "id")
        return Response({"items": DemoAccountSerializer(accounts, many=True).data})


class DemoSessionView(APIView):
    @extend_schema(responses={200: DemoSessionResponseSerializer})
    def get(self, request: Request) -> Response:
        raw = getattr(request._request, "demo_account", None)
        payload = getattr(request._request, "demo_session_payload", None)
        if raw is None or payload is None:
            return Response({"account": None, "csrfToken": None})
        return Response(
            {
                "account": DemoAccountSerializer(raw).data,
                "csrfToken": payload["csrfToken"],
            }
        )

    @extend_schema(request=DemoSessionRequestSerializer, responses={200: DemoSessionResponseSerializer})
    def post(self, request: Request) -> Response:
        account_id = request.data.get("accountId") if isinstance(request.data, dict) else None
        if not account_id:
            raise SoloLedgerApiError(
                status_code=422,
                code="VALIDATION_ERROR",
                message="accountId is required.",
                field_errors={"accountId": ["Select a demo account."]},
            )
        account = Account.objects.filter(id=account_id).first()
        if account is None:
            raise SoloLedgerApiError(
                status_code=404,
                code="NOT_FOUND",
                message="Demo account not found.",
            )
        token, csrf_token = create_signed_session_token(str(account.id))
        res = Response(
            {
                "account": DemoAccountSerializer(account).data,
                "csrfToken": csrf_token,
            },
            status=200,
        )
        res.set_cookie(
            SESSION_COOKIE_NAME,
            token,
            httponly=True,
            samesite="Lax",
            path="/",
        )
        return res
