from __future__ import annotations

from decimal import Decimal

import pytest

from classification.confidence import (
    determine_review_status,
    normalize_merchant,
    validate_confidence,
)
from classification.langchain_adapter import LangChainCategorizerAdapter
from classification.provider import ProviderSuggestion, SanitizedSuggestionInput

ALLOWED = (
    "SOFTWARE",
    "OFFICE_SUPPLIES",
    "TRANSPORT",
    "MEALS",
    "UTILITIES",
    "PROFESSIONAL_SERVICES",
    "MARKETING",
    "EDUCATION",
    "EQUIPMENT",
    "SUBSCRIPTIONS",
    "INCOME",
    "TRANSFER",
    "UNCATEGORIZED",
)


def test_confidence_boundaries_and_normalization():
    assert validate_confidence(Decimal("0.699")) == Decimal("0.699")
    assert validate_confidence("0.700") == Decimal("0.700")
    assert validate_confidence(None) is None

    for bad in ("-0.001", "1.001", "abc"):
        with pytest.raises(ValueError):
            validate_confidence(bad)

    # Exact review boundary rule: < 0.700 -> NEEDS_REVIEW; >= 0.700 -> SUGGESTED
    assert determine_review_status(Decimal("0.699")) == "NEEDS_REVIEW"
    assert determine_review_status(Decimal("0.700")) == "SUGGESTED"
    assert determine_review_status(None) == "NEEDS_REVIEW"
    assert determine_review_status(Decimal("1.000"), from_user_rule=True) == "APPROVED"
    assert determine_review_status(Decimal("0.990"), from_user_rule=True, duplicate_candidate=True) == "NEEDS_REVIEW"

    assert normalize_merchant("  Demo  Cloud   Hosting #991 ") == "DEMO CLOUD HOSTING"
    assert normalize_merchant("Northwood   Mart   TXN-44") == "NORTHWOOD MART"


def test_precedence_and_provider_privacy_spy():
    observed_payloads: list[SanitizedSuggestionInput] = []

    class SpyProvider:
        kind = "SPY"
        model_version = "spy-v1"

        def suggest(self, payload: SanitizedSuggestionInput) -> ProviderSuggestion:
            observed_payloads.append(payload)
            return ProviderSuggestion(
                category_code="SOFTWARE",
                confidence=Decimal("0.685"),
                model_version=self.model_version,
                explanation_code="SPY_LOW",
            )

    adapter = LangChainCategorizerAdapter(provider=SpyProvider(), allowed_categories=ALLOWED)

    # 1. Account user rule overrides exact lexicon & LLM
    user_hit = adapter.classify(
        description="DEMO CLOUD HOSTING",
        amount_minor=-2500,
        merchant_rules={"DEMO CLOUD HOSTING": "EQUIPMENT"},
    )
    assert user_hit.category_code == "EQUIPMENT"
    assert user_hit.category_source == "USER_RULE"
    assert user_hit.review_status == "APPROVED"

    # 2. Exact lexicon match hits >= 0.700 SUGGESTED without calling provider
    lex_hit = adapter.classify(
        description="ACME OFFICE SUPPLIES #102",
        amount_minor=-4285,
        merchant_rules={},
    )
    assert lex_hit.category_code == "OFFICE_SUPPLIES"
    assert lex_hit.review_status == "SUGGESTED"
    assert len(observed_payloads) == 0

    # 3. Unfamiliar merchant delegates to privacy-minimized LangChain runnable provider
    llm_hit = adapter.classify(
        description="OBSCURE DEV TOOL #42",
        amount_minor=-1900,
        merchant_rules={},
    )
    assert llm_hit.category_code == "SOFTWARE"
    assert llm_hit.review_status == "NEEDS_REVIEW"  # 0.685 < 0.700
    assert len(observed_payloads) == 1
    dto = observed_payloads[0]
    assert dto.normalized_merchant == "OBSCURE DEV TOOL"
    assert dto.amount_sign == "DEBIT"
    assert not hasattr(dto, "account_id")
    assert not hasattr(dto, "accountId")


def test_provider_timeout_safe_fallback_and_live_blocked(settings):
    class FailingProvider:
        kind = "MOCK"
        model_version = "err-v1"

        def suggest(self, payload: SanitizedSuggestionInput) -> ProviderSuggestion:
            raise TimeoutError("Provider timed out")

    adapter = LangChainCategorizerAdapter(provider=FailingProvider(), allowed_categories=ALLOWED)
    res = adapter.classify(description="MYSTERY SHOP", amount_minor=-1200, merchant_rules={})
    assert res.category_code == "UNCATEGORIZED"
    assert res.category_source == "FALLBACK"
    assert res.confidence is None
    assert res.review_status == "NEEDS_REVIEW"

    settings.SOLOLEDGER_LLM_PROVIDER = "live"
    with pytest.raises(RuntimeError, match="BLOCKED_EXTERNAL"):
        LangChainCategorizerAdapter(allowed_categories=ALLOWED)

