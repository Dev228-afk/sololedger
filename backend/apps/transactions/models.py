import uuid

from django.db import models

from apps.accounts.models import Account
from apps.categorization.models import Category
from apps.imports.models import ImportJob, ImportRow


class CategorySource(models.TextChoices):
    USER_RULE = "USER_RULE", "User rule"
    KEYWORD = "KEYWORD", "Keyword rule"
    LLM = "LLM", "LLM adapter"
    FALLBACK = "FALLBACK", "Fallback"
    USER_REVIEW = "USER_REVIEW", "User review"


class ReviewStatus(models.TextChoices):
    SUGGESTED = "SUGGESTED", "Suggested"
    NEEDS_REVIEW = "NEEDS_REVIEW", "Needs review"
    APPROVED = "APPROVED", "Approved"


class Transaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="transactions")
    import_row = models.OneToOneField(ImportRow, on_delete=models.PROTECT, related_name="transaction")
    import_job = models.ForeignKey(ImportJob, on_delete=models.PROTECT, related_name="transactions")
    posted_date = models.DateField()
    description = models.CharField(max_length=300)
    normalized_merchant = models.CharField(max_length=160)
    amount_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3, default="USD")
    external_ref = models.CharField(max_length=128, null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="transactions")
    category_source = models.CharField(max_length=24, choices=CategorySource.choices)
    confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    review_status = models.CharField(max_length=24, choices=ReviewStatus.choices)
    duplicate_candidate = models.BooleanField(default=False)
    version = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "transactions"
        constraints = [
            models.UniqueConstraint(
                fields=["account", "import_row"],
                name="uniq_txn_account_import_row",
            ),
        ]
        indexes = [
            models.Index(fields=["account", "-posted_date", "-id"], name="idx_txn_acc_date_id"),
            models.Index(fields=["account", "review_status"], name="idx_txn_acc_rev_status"),
        ]
        ordering = ["-posted_date", "-id"]


class ClassificationSuggestion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT, related_name="suggestions")
    suggested_category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="+")
    confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    method = models.CharField(max_length=32)
    rule_version = models.CharField(max_length=32)
    model_version = models.CharField(max_length=64, null=True, blank=True)
    explanation_code = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "classification_suggestions"
        ordering = ["-created_at"]


class ReviewDecisionType(models.TextChoices):
    ACCEPT = "ACCEPT", "Accept"
    CHANGE = "CHANGE", "Change"


class ReviewDecision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT, related_name="review_decisions")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="review_decisions")
    previous_category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="+")
    new_category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="+")
    previous_status = models.CharField(max_length=24)
    decision = models.CharField(max_length=16, choices=ReviewDecisionType.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "review_decisions"
        ordering = ["-created_at"]

