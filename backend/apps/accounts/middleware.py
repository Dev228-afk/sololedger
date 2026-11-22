from __future__ import annotations

import uuid

from django.http import HttpRequest, HttpResponse

from .auth import SESSION_COOKIE_NAME, verify_signed_session_token
from .models import Account


class RequestIdAndSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming_req_id = request.headers.get("X-Request-Id")
        request_id = incoming_req_id or f"req_{uuid.uuid4().hex[:12]}"
        request.request_id = request_id
        request.demo_account = None
        request.demo_session_payload = None

        raw_cookie = request.COOKIES.get(SESSION_COOKIE_NAME)
        payload = verify_signed_session_token(raw_cookie)
        if payload:
            account = Account.objects.filter(id=payload["accountId"]).first()
            if account is not None:
                request.demo_account = account
                request.demo_session_payload = payload

        response = self.get_response(request)
        response["X-Request-Id"] = request_id
        return response

