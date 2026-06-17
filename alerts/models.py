from django.conf import settings
from django.db import models


class NotificationLog(models.Model):
    """One row per digest email sent (or attempted)."""

    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_logs",
    )
    cadence = models.CharField(max_length=10)
    match_count = models.PositiveIntegerField()
    sent_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    provider_message_id = models.CharField(max_length=200, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-sent_at"]

    def __str__(self):
        return (
            f"{self.cadence} digest to {self.user} "
            f"at {self.sent_at:%Y-%m-%d %H:%M} ({self.status})"
        )
