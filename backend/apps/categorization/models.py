import uuid

from django.db import models
from django.utils import timezone

from apps.accounts.models import Account


class CategoryKind(models.TextChoices):
    EXPENSE = "EXPENSE", "Expense"
    INCOME = "INCOME", "Income"
    TRANSFER = "TRANSFER", "Transfer"


class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=48, unique=True)
    name = models.CharField(max_length=96)
    kind = models.CharField(max_length=16, choices=CategoryKind.choices, default=CategoryKind.EXPENSE)
    active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "categories"
        ordering = ["sort_order", "code"]

    def __str__(self) -> str:
        return self.code


class MerchantCorrection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="merchant_rules")
    merchant_key = models.CharField(max_length=160)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="merchant_rules")
    priority = models.IntegerField(default=100)
    active = models.BooleanField(default=True)
    approved_at = models.DateTimeField(default=timezone.now)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "merchant_corrections"
        indexes = [
            models.Index(fields=["account", "merchant_key"], name="idx_mc_acc_merchant"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "merchant_key"],
                condition=models.Q(active=True),
                name="uniq_active_merchant_rule",
            ),
        ]
        ordering = ["priority", "merchant_key"]

