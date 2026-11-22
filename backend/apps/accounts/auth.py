from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from django.conf import settings
from django.http import HttpRequest

from .models import Account

SESSION_COOKIE_NAME = "sololedger_demo_session"


class SoloLedgerApiError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        field_errors: dict[str, list[str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        self.field_errors = field_errors or {}


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64_decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(f"{encoded}{padding}".encode("ascii"))


def _sign_payload(encoded: str) -> str:
    digest = hmac.new(
        settings.SOLOLEDGER_SESSION_SECRET.encode("utf-8"),
        encoded.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _b64_encode(digest)


def create_signed_session_token(account_id: str, csrf_token: str | None = None) -> tuple[str, str]:
    csrf = csrf_token or secrets.token_urlsafe(24)
    payload = {
        "accountId": account_id,
        "csrfToken": csrf,
        "issuedAt": int(time.time()),
    }
    encoded = _b64_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _sign_payload(encoded)
    return f"{encoded}.{sig}", csrf


def verify_signed_session_token(raw: str | None) -> dict[str, Any] | None:
    if not raw or "." not in raw:
        return None
    parts = raw.split(".", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    encoded, provided_sig = parts
    expected_sig = _sign_payload(encoded)
    if not hmac.compare_digest(provided_sig.encode("utf-8"), expected_sig.encode("utf-8")):
        return None
    try:
        parsed = json.loads(_b64_decode(encoded).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    if not isinstance(parsed.get("accountId"), str) or not isinstance(parsed.get("csrfToken"), str):
        return None
    return parsed


def require_account(request: HttpRequest, *, check_csrf: bool = False) -> Account:
    account = getattr(request, "demo_account", None)
    session_data = getattr(request, "demo_session_payload", None)
    if account is None or session_data is None:
        raise SoloLedgerApiError(
            status_code=401,
            code="UNAUTHORIZED",
            message="Select a demo account session before accessing SoloLedger.",
        )
    if check_csrf:
        provided = request.headers.get("X-Csrf-Token") or request.META.get("HTTP_X_CSRF_TOKEN")
        expected = str(session_data.get("csrfToken", ""))
        if not provided or not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
            raise SoloLedgerApiError(
                status_code=403,
                code="CSRF_MISMATCH",
                message="Missing or invalid CSRF token.",
            )
    return account

