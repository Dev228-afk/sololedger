import uuid

from django.db import models

from apps.accounts.models import Account


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="audit_events")
    actor = models.CharField(max_length=128)
    entity_type = models.CharField(max_length=64)
    entity_id = models.UUIDField()
    event_type = models.CharField(max_length=64)
    redacted_detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_events"
        indexes = [
            models.Index(fields=["account", "-created_at"], name="idx_audit_acc_created"),
            models.Index(fields=["entity_type", "entity_id"], name="idx_audit_entity"),
        ]
        ordering = ["-created_at"]

