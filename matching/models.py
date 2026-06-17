from django.conf import settings
from django.db import models


class Match(models.Model):
    """One keyword hitting one opinion for one user.

    ``count`` and ``snippets`` reproduce the PoC report content: total hit
    count and up to 3 context snippets (±120 chars) per opinion/keyword.
    """

    opinion = models.ForeignKey(
        "ingestion.Opinion", on_delete=models.CASCADE, related_name="matches"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="matches"
    )
    keyword = models.ForeignKey(
        "keywords.Keyword", on_delete=models.CASCADE, related_name="matches"
    )
    count = models.PositiveIntegerField()
    snippets = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["opinion", "user", "keyword"], name="unique_match"
            )
        ]
        indexes = [models.Index(fields=["user", "created_at"])]
        verbose_name_plural = "matches"

    def __str__(self):
        return f"{self.keyword.text} ×{self.count} in {self.opinion_id} for {self.user}"
