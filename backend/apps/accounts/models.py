import uuid

from django.db import models


class Account(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    display_name = models.CharField(max_length=160)
    timezone = models.CharField(max_length=64, default="America/Los_Angeles")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts"
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return self.display_name

