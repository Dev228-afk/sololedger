from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

RULE_VERSION = "rules-v1.0"


@dataclass(frozen=True)
class RuleMatch:
    category_code: str
    confidence: Decimal
    method: str
    explanation_code: str
    rule_version: str = RULE_VERSION


EXACT_LEXICON: dict[str, tuple[str, str]] = {
    "DEMO CLOUD HOSTING": ("SOFTWARE", "0.940"),
    "SYNTHETIC CODE REPO PRO": ("SOFTWARE", "0.950"),
    "VECTOR DESIGN SUITE": ("SOFTWARE", "0.930"),
    "ACME OFFICE SUPPLIES": ("OFFICE_SUPPLIES", "0.920"),
    "PAPER & TONER DEPOT": ("OFFICE_SUPPLIES", "0.910"),
    "METRO RAIL PASS": ("TRANSPORT", "0.910"),
    "DOWNTOWN RIDE SHARE": ("TRANSPORT", "0.860"),
    "HARBOR ROASTERS CAFE": ("MEALS", "0.840"),
    "BISTRO CLIENT LUNCH": ("MEALS", "0.850"),
    "NORTHGRID FIBER INTERNET": ("UTILITIES", "0.930"),
    "CITY POWER & LIGHT": ("UTILITIES", "0.920"),
    "PACIFIC CPA ADVISORY": ("PROFESSIONAL_SERVICES", "0.940"),
    "OAKRIDGE LEGAL STUDIO": ("PROFESSIONAL_SERVICES", "0.920"),
    "SEARCH PROMO STUDIO": ("MARKETING", "0.910"),
    "SOCIAL CAMPAIGN BOOST": ("MARKETING", "0.880"),
    "WORKSHOP BOOK HOUSE": ("EDUCATION", "0.880"),
    "ONLINE SYSTEMS ACADEMY": ("EDUCATION", "0.890"),
    "ERGONOMIC DESK CO": ("EQUIPMENT", "0.910"),
    "THUNDERBOLT DOCK STORE": ("EQUIPMENT", "0.900"),
    "MONTHLY NEWS BRIEF": ("SUBSCRIPTIONS", "0.890"),
    "CREATIVE STOCK VAULT": ("SUBSCRIPTIONS", "0.870"),
    "CLIENT RETAINER PAYOUT": ("INCOME", "0.970"),
    "FREELANCE INVOICE ACH": ("INCOME", "0.960"),
    "OWNER SAVINGS TRANSFER": ("TRANSFER", "0.950"),
}

KEYWORD_RULES: list[tuple[tuple[str, ...], str, str, str]] = [
    (("CLOUD", "SAAS", "HOSTING", "DOMAIN", "API", "LICENSE", "SOFTWARE"), "SOFTWARE", "0.820", "KW_SOFTWARE"),
    (("OFFICE", "PAPER", "STATIONERY", "INK", "TONER", "SHIPPING"), "OFFICE_SUPPLIES", "0.800", "KW_OFFICE"),
    (("TRANSIT", "RAIL", "AIRLINE", "PARKING", "TAXI", "UBER", "LYFT", "RIDE"), "TRANSPORT", "0.780", "KW_TRANSPORT"),
    (("CAFE", "COFFEE", "BISTRO", "DINER", "LUNCH", "DELI", "BAKERY"), "MEALS", "0.750", "KW_MEALS"),
    (("FIBER", "INTERNET", "ELECTRIC", "UTILITY", "WIRELESS", "TELECOM"), "UTILITIES", "0.840", "KW_UTILITIES"),
    (("CPA", "ACCOUNTING", "LEGAL", "COUNSEL", "CONSULTING", "ADVISORY"), "PROFESSIONAL_SERVICES", "0.830", "KW_PRO_SERV"),
    (("ADS", "MARKETING", "SPONSORED", "PROMO", "CAMPAIGN"), "MARKETING", "0.790", "KW_MARKETING"),
    (("ACADEMY", "COURSE", "BOOK", "SEMINAR", "TRAINING"), "EDUCATION", "0.790", "KW_EDUCATION"),
    (("MONITOR", "KEYBOARD", "LAPTOP", "HARDWARE", "DESK", "DOCK"), "EQUIPMENT", "0.810", "KW_EQUIPMENT"),
    (("SUBSCRIPTION", "MEMBERSHIP", "DIGEST", "VAULT", "MONTHLY PASS"), "SUBSCRIPTIONS", "0.760", "KW_SUBS"),
    (("PAYOUT", "RETAINER", "INVOICE ACH", "DEPOSIT", "CLIENT PAYMENT"), "INCOME", "0.910", "KW_INCOME"),
    (("TRANSFER", "OWNER DRAW", "INTERNAL XFER", "SWEEP"), "TRANSFER", "0.900", "KW_TRANSFER"),
    # Intentionally ambiguous merchant tokens receive lower heuristic confidence (<0.700)
    (("MARKET", "GENERAL STORE", "CARD PURCHASE", "POINT OF SALE"), "OFFICE_SUPPLIES", "0.620", "KW_AMBIGUOUS_STORE"),
]


def match_deterministic_rule(normalized_merchant: str, amount_minor: int) -> RuleMatch | None:
    if normalized_merchant in EXACT_LEXICON:
        cat_code, conf_str = EXACT_LEXICON[normalized_merchant]
        # Positive credits matching an expense merchant lexicon remain valid refunds unless category is INCOME/TRANSFER.
        return RuleMatch(
            category_code=cat_code,
            confidence=Decimal(conf_str),
            method="EXACT_LEXICON",
            explanation_code="EXACT_MERCHANT_MATCH",
        )

    for keywords, cat_code, conf_str, exp_code in KEYWORD_RULES:
        if any(kw in normalized_merchant for kw in keywords):
            if cat_code == "INCOME" and amount_minor < 0:
                continue
            return RuleMatch(
                category_code=cat_code,
                confidence=Decimal(conf_str),
                method="KEYWORD_RULE",
                explanation_code=exp_code,
            )

    if amount_minor > 0 and ("REFUND" in normalized_merchant or "REVERSAL" in normalized_merchant):
        # Refunds with clear category tokens fall into keyword match above; ambiguous refunds go to review.
        return RuleMatch(
            category_code="UNCATEGORIZED",
            confidence=Decimal("0.640"),
            method="REFUND_HEURISTIC",
            explanation_code="REFUND_NEEDS_CATEGORY",
        )

    return None

