from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class SanitizedSuggestionInput:
    """Privacy-minimized payload forwarded to provider/LangChain: zero account IDs, raw CSV lines, or PII."""
    normalized_merchant: str
    amount_sign: str  # "DEBIT" | "CREDIT"
    allowed_categories: tuple[str, ...]


@dataclass(frozen=True)
class ProviderSuggestion:
    category_code: str
    confidence: Decimal | None
    model_version: str
    explanation_code: str


class CategorizerProvider(Protocol):
    kind: str
    model_version: str

    def suggest(self, payload: SanitizedSuggestionInput) -> ProviderSuggestion: ...


class MockCategorizerProvider:
    kind = "MOCK"
    model_version = "mock-heuristic-v1"

    _HINTS: dict[str, tuple[str, str]] = {
        "SUPPLY": ("OFFICE_SUPPLIES", "0.660"),
        "MART": ("UNCATEGORIZED", "0.520"),
        "CLUB": ("SUBSCRIPTIONS", "0.680"),
        "EXPRESS": ("TRANSPORT", "0.670"),
        "GRILL": ("MEALS", "0.690"),
        "TECH": ("SOFTWARE", "0.730"),
        "STUDIO": ("PROFESSIONAL_SERVICES", "0.650"),
    }

    def suggest(self, payload: SanitizedSuggestionInput) -> ProviderSuggestion:
        merch = payload.normalized_merchant
        if payload.amount_sign == "CREDIT" and "CLIENT" in merch:
            return ProviderSuggestion(
                category_code="INCOME",
                confidence=Decimal("0.830"),
                model_version=self.model_version,
                explanation_code="MOCK_CREDIT_CLIENT_HINT",
            )
        for token, (cat, conf_str) in self._HINTS.items():
            if token in merch and cat in payload.allowed_categories:
                return ProviderSuggestion(
                    category_code=cat,
                    confidence=Decimal(conf_str),
                    model_version=self.model_version,
                    explanation_code=f"MOCK_TOKEN_{token}",
                )
        # Deterministic low-confidence abstention for unfamiliar merchants -> routes to review
        digest = int(hashlib.sha256(merch.encode("utf-8")).hexdigest()[:4], 16)
        heuristic = Decimal("0.450") + (Decimal(digest % 200) / Decimal("1000"))
        return ProviderSuggestion(
            category_code="UNCATEGORIZED",
            confidence=heuristic.quantize(Decimal("0.001")),
            model_version=self.model_version,
            explanation_code="MOCK_LOW_CONFIDENCE_ABSTAIN",
        )

