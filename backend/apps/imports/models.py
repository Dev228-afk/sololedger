import uuid

from django.db import models

from apps.accounts.models import Account


class ImportStatus(models.TextChoices):
    QUEUED = "QUEUED", "Queued"
    VALIDATING = "VALIDATING", "Validating"
    PROCESSING = "PROCESSING", "Processing"
    AWAITING_REVIEW = "AWAITING_REVIEW", "Awaiting review"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"
    CANCELED = "CANCELED", "Canceled"


class ImportUploadPreview(models.Model):
    upload_token = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="upload_previews")
    storage_key = models.CharField(max_length=255)
    original_filename = models.CharField(max_length=255)
    file_sha256 = models.CharField(max_length=64)
    file_size = models.BigIntegerField()
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "import_upload_previews"
        indexes = [
            models.Index(fields=["account", "expires_at"], name="idx_preview_acc_exp"),
        ]


class ImportJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="import_jobs")
    upload_key = models.CharField(max_length=255)
    file_sha256 = models.CharField(max_length=64)
    original_filename = models.CharField(max_length=255)
    status = models.CharField(max_length=24, choices=ImportStatus.choices, default=ImportStatus.QUEUED)
    idempotency_key = models.CharField(max_length=128, null=True, blank=True)
    mapping_json = models.JSONField(default=dict)
    total_rows = models.IntegerField(default=0)
    processed_rows = models.IntegerField(default=0)
    valid_rows = models.IntegerField(default=0)
    invalid_rows = models.IntegerField(default=0)
    needs_review_count = models.IntegerField(default=0)
    attempts = models.IntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True, default="")
    error_message = models.CharField(max_length=300, blank=True, default="")
    cancel_requested = models.BooleanField(default=False)
    cancel_reason = models.CharField(max_length=200, blank=True, default="")
    enqueued_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "import_jobs"
        constraints = [
            models.UniqueConstraint(
                fields=["account", "idempotency_key"],
                condition=models.Q(idempotency_key__isnull=False),
                name="uniq_import_idempotency_key",
            ),
        ]
        indexes = [
            models.Index(fields=["account", "-created_at", "-id"], name="idx_import_acc_created"),
            models.Index(fields=["status", "enqueued_at"], name="idx_import_status_enq"),
        ]
        ordering = ["-created_at", "-id"]


class ImportRowStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    VALID = "VALID", "Valid"
    INVALID = "INVALID", "Invalid"
    DUPLICATE_CANDIDATE = "DUPLICATE_CANDIDATE", "Duplicate candidate"


class ImportRow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    import_job = models.ForeignKey(ImportJob, on_delete=models.PROTECT, related_name="rows")
    source_line_no = models.IntegerField()
    raw_hash = models.CharField(max_length=64)
    normalized_description = models.CharField(max_length=300, blank=True, default="")
    posted_date = models.DateField(null=True, blank=True)
    signed_amount_minor = models.BigIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=12, blank=True, default="")
    source_txn_id = models.CharField(max_length=128, null=True, blank=True)
    status = models.CharField(max_length=24, choices=ImportRowStatus.choices, default=ImportRowStatus.PENDING)
    error_code = models.CharField(max_length=64, null=True, blank=True)
    error_detail = models.CharField(max_length=240, blank=True, default="")

    class Meta:
        db_table = "import_rows"
        constraints = [
            models.UniqueConstraint(
                fields=["import_job", "source_line_no"],
                name="uniq_import_row_line",
            ),
        ]
        indexes = [
            models.Index(fields=["import_job", "source_line_no"], name="idx_import_row_line"),
        ]
        ordering = ["source_line_no"]

