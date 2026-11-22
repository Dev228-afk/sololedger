from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from langchain_core.runnables import RunnableLambda

from .confidence import determine_review_status, normalize_merchant
from .provider import (
    CategorizerProvider,
    MockCategorizerProvider,
    SanitizedSuggestionInput,
)
from .rules import RULE_VERSION, match_deterministic_rule


@dataclass(frozen=True)
class CategorizationOutcome:
    normalized_merchant: str
    category_code: str
    category_source: str  # USER_RULE | KEYWORD | LLM | FALLBACK
    confidence: Decimal | None
    review_status: str  # APPROVED | SUGGESTED | NEEDS_REVIEW
    method: str
    rule_version: str
    model_version: str | None
    explanation_code: str


class LangChainCategorizerAdapter:
    """
    Orchestrates deterministic classification precedence using langchain_core Runnables:
    1. Account-scoped active MerchantCorrection -> APPROVED (1.000)
    2. Exact merchant lexicon -> SUGGESTED / NEEDS_REVIEW
    3. Keyword/fuzzy rules -> SUGGESTED / NEEDS_REVIEW
    4. Opt-in provider chain (MockCategorizerProvider locally; LIVE gated) -> SUGGESTED / NEEDS_REVIEW
    5. Safe fallback -> UNCATEGORIZED + NEEDS_REVIEW
    """

    def __init__(
        self,
        *,
        provider: CategorizerProvider | None = None,
        allowed_categories: Iterable[str],
    ) -> None:
        self.allowed_categories = tuple(allowed_categories)
        if provider is not None:
            self.provider = provider
        elif settings.SOLOLEDGER_LLM_PROVIDER == "live":
            raise RuntimeError("BLOCKED_EXTERNAL: Live LLM provider requires user-supplied key and spend approval.")
        else:
            self.provider = MockCategorizerProvider()

        self._provider_chain = RunnableLambda(self._build_sanitized_input) | RunnableLambda(
            lambda dto: self.provider.suggest(dto)
        )

    @staticmethod
    def _build_sanitized_input(raw: dict) -> SanitizedSuggestionInput:
        return SanitizedSuggestionInput(
            normalized_merchant=str(raw["normalized_merchant"]),
            amount_sign=str(raw["amount_sign"]),
            allowed_categories=tuple(raw["allowed_categories"]),
        )

    def classify(
        self,
        *,
        description: str,
        amount_minor: int,
        merchant_rules: dict[str, str],
        duplicate_candidate: bool = False,
    ) -> CategorizationOutcome:
        norm_merchant = normalize_merchant(description)

        # 1. Account-approved prior merchant correction takes highest precedence
        if norm_merchant in merchant_rules:
            rule_cat = merchant_rules[norm_merchant]
            conf = Decimal("1.000")
            return CategorizationOutcome(
                normalized_merchant=norm_merchant,
                category_code=rule_cat,
                category_source="USER_RULE",
                confidence=conf,
                review_status=determine_review_status(
                    conf, from_user_rule=True, duplicate_candidate=duplicate_candidate
                ),
                method="USER_RULE",
                rule_version=RULE_VERSION,
                model_version=None,
                explanation_code="PRIOR_MERCHANT_RULE",
            )

        # 2 & 3. Exact lexicon + deterministic keyword heuristics
        rule_hit = match_deterministic_rule(norm_merchant, amount_minor)
        if rule_hit is not None:
            return CategorizationOutcome(
                normalized_merchant=norm_merchant,
                category_code=rule_hit.category_code,
                category_source="KEYWORD",
                confidence=rule_hit.confidence,
                review_status=determine_review_status(
                    rule_hit.confidence, duplicate_candidate=duplicate_candidate
                ),
                method=rule_hit.method,
                rule_version=rule_hit.rule_version,
                model_version=None,
                explanation_code=rule_hit.explanation_code,
            )

        # 4. Sanitized LangChain runnable provider step (timeout/error safe fallback)
        try:
            suggestion = self._provider_chain.invoke(
                {
                    "normalized_merchant": norm_merchant,
                    "amount_sign": "CREDIT" if amount_minor >= 0 else "DEBIT",
                    "allowed_categories": self.allowed_categories,
                }
            )
            cat = suggestion.category_code
            if cat not in self.allowed_categories:
                cat = "UNCATEGORIZED"
            rev = determine_review_status(
                suggestion.confidence, duplicate_candidate=duplicate_candidate
            )
            return CategorizationOutcome(
                normalized_merchant=norm_merchant,
                category_code=cat,
                category_source="LLM" if cat != "UNCATEGORIZED" else "FALLBACK",
                confidence=suggestion.confidence,
                review_status=rev,
                method=f"{self.provider.kind}_CHAIN",
                rule_version=RULE_VERSION,
                model_version=suggestion.model_version,
                explanation_code=suggestion.explanation_code,
            )
        except Exception:
            return CategorizationOutcome(
                normalized_merchant=norm_merchant,
                category_code="UNCATEGORIZED",
                category_source="FALLBACK",
                confidence=None,
                review_status="NEEDS_REVIEW",
                method="FALLBACK_ERROR_SAFE",
                rule_version=RULE_VERSION,
                model_version=None,
                explanation_code="PROVIDER_UNAVAILABLE_FALLBACK",
            )
