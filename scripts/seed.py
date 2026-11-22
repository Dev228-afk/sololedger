#!/usr/bin/env python
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.db import transaction  # noqa: E402

from apps.accounts.models import Account  # noqa: E402
from apps.categorization.models import Category, CategoryKind  # noqa: E402

DEMO_ACCOUNTS = [
    (
        uuid.UUID("11111111-1111-5111-8111-111111111101"),
        "Demo Freelancer — Studio North",
        "America/Los_Angeles",
    ),
    (
        uuid.UUID("11111111-1111-5111-8111-111111111102"),
        "Demo Consultant — Cedar Labs",
        "America/New_York",
    ),
]

CANONICAL_CATEGORIES = [
    ("SOFTWARE", "Software & Cloud", CategoryKind.EXPENSE, 10),
    ("OFFICE_SUPPLIES", "Office Supplies", CategoryKind.EXPENSE, 20),
    ("TRANSPORT", "Transport & Transit", CategoryKind.EXPENSE, 30),
    ("MEALS", "Meals & Client Coffee", CategoryKind.EXPENSE, 40),
    ("UTILITIES", "Utilities & Internet", CategoryKind.EXPENSE, 50),
    ("PROFESSIONAL_SERVICES", "Professional Services", CategoryKind.EXPENSE, 60),
    ("MARKETING", "Marketing & Promo", CategoryKind.EXPENSE, 70),
    ("EDUCATION", "Education & Books", CategoryKind.EXPENSE, 80),
    ("EQUIPMENT", "Hardware & Equipment", CategoryKind.EXPENSE, 90),
    ("SUBSCRIPTIONS", "Subscriptions", CategoryKind.EXPENSE, 100),
    ("INCOME", "Client Income", CategoryKind.INCOME, 110),
    ("TRANSFER", "Internal Transfers", CategoryKind.TRANSFER, 120),
    ("UNCATEGORIZED", "Uncategorized", CategoryKind.EXPENSE, 130),
]


def seed_all() -> dict:
    with transaction.atomic():
        for acc_id, name, tz in DEMO_ACCOUNTS:
            Account.objects.update_or_create(
                id=acc_id,
                defaults={"display_name": name, "timezone": tz},
            )
        for code, name, kind, order in CANONICAL_CATEGORIES:
            Category.objects.update_or_create(
                code=code,
                defaults={"name": name, "kind": kind, "active": True, "sort_order": order},
            )

    summary = {
        "event": "seed.complete",
        "accounts": Account.objects.count(),
        "categories": Category.objects.count(),
    }
    print(json.dumps(summary))
    return summary


if __name__ == "__main__":
    seed_all()

