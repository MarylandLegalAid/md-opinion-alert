from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Application user, provisioned from Entra ID on first OIDC login.

    Keyed on the immutable Entra object id (``oid``) — never on email, which
    can be reassigned. ``entra_oid`` is null for local dev/password accounts.
    """

    class DigestCadence(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        OFF = "off", "Off"

    entra_oid = models.CharField(max_length=64, unique=True, null=True, blank=True)
    display_name = models.CharField(max_length=255, blank=True)
    digest_cadence = models.CharField(
        max_length=10,
        choices=DigestCadence.choices,
        default=DigestCadence.WEEKLY,
    )
    last_digest_at = models.DateTimeField(null=True, blank=True)
    last_dashboard_visit_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.display_name or self.get_username()
