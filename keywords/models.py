from django.conf import settings
from django.db import models
from django.db.models import Q


class KeywordList(models.Model):
    """A named, admin-curated, shareable collection of keywords."""

    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    is_shared = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Keyword(models.Model):
    """A search term belonging to a shared list *or* personal to a user.

    Match options mirror the PoC: whole-word, case-insensitive by default;
    multi-word phrases work with the same boundary anchoring.
    """

    text = models.CharField(max_length=200)
    list = models.ForeignKey(
        KeywordList,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="keywords",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="personal_keywords",
    )
    match_whole_word = models.BooleanField(default=True)
    case_insensitive = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="keyword_list_xor_owner",
                condition=(
                    Q(list__isnull=False, owner__isnull=True)
                    | Q(list__isnull=True, owner__isnull=False)
                ),
            ),
            models.UniqueConstraint(
                fields=["list", "text"],
                name="unique_keyword_per_list",
                condition=Q(list__isnull=False),
            ),
            models.UniqueConstraint(
                fields=["owner", "text"],
                name="unique_keyword_per_owner",
                condition=Q(owner__isnull=False),
            ),
        ]
        ordering = ["text"]

    def __str__(self):
        scope = self.list.name if self.list_id else f"personal:{self.owner}"
        return f"{self.text} ({scope})"

    def users(self):
        """All users whose dashboards/digests this keyword feeds."""
        from django.contrib.auth import get_user_model

        if self.owner_id:
            return get_user_model().objects.filter(pk=self.owner_id)
        return get_user_model().objects.filter(
            subscriptions__keyword_list_id=self.list_id
        )


class Subscription(models.Model):
    """A user's subscription to a shared keyword list."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    keyword_list = models.ForeignKey(
        KeywordList, on_delete=models.CASCADE, related_name="subscriptions"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "keyword_list"], name="unique_subscription"
            )
        ]

    def __str__(self):
        return f"{self.user} → {self.keyword_list}"
