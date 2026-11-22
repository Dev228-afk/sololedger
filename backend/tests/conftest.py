from __future__ import annotations

import uuid

import pytest
from django.test import Client

from apps.accounts.models import Account
from apps.categorization.models import Category, CategoryKind

TEST_CATEGORIES = [
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


@pytest.fixture
def temp_storage(settings, tmp_path):
    settings.SOLOLEDGER_STORAGE_DIR = tmp_path
    return tmp_path


@pytest.fixture
def seeded_accounts_and_categories(db):
    acc_a, _ = Account.objects.update_or_create(
        id=uuid.UUID("11111111-1111-5111-8111-111111111101"),
        defaults={"display_name": "Demo Freelancer — Studio North", "timezone": "America/Los_Angeles"},
    )
    acc_b, _ = Account.objects.update_or_create(
        id=uuid.UUID("11111111-1111-5111-8111-111111111102"),
        defaults={"display_name": "Demo Consultant — Cedar Labs", "timezone": "America/New_York"},
    )
    for code, name, kind, order in TEST_CATEGORIES:
        Category.objects.update_or_create(
            code=code,
            defaults={"name": name, "kind": kind, "active": True, "sort_order": order},
        )
    return acc_a, acc_b


def auth_client(account_id: uuid.UUID) -> tuple[Client, str]:
    client = Client()
    res = client.post(
        "/api/v1/demo/session",
        data={"accountId": str(account_id)},
        content_type="application/json",
    )
    assert res.status_code == 200
    csrf_token = res.json()["csrfToken"]
    return client, csrf_token

