from django.db import models


class Opinion(models.Model):
    """One appellate opinion, deduplicated by canonical PDF URL."""

    class OpinionType(models.TextChoices):
        REPORTED = "reported", "Reported"
        UNREPORTED = "unreported", "Unreported"

    source_url = models.URLField(max_length=500, unique=True)
    case_name = models.CharField(max_length=500, blank=True)
    docket = models.CharField(max_length=200, blank=True)
    court = models.CharField(max_length=200, blank=True)
    opinion_type = models.CharField(max_length=10, choices=OpinionType.choices)
    filed_date = models.DateField(null=True, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_checked_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-filed_date", "-first_seen_at"]
        indexes = [
            models.Index(fields=["opinion_type", "filed_date"]),
            models.Index(fields=["first_seen_at"]),
        ]

    def __str__(self):
        return f"{self.case_name or self.docket} ({self.opinion_type})"


class OpinionText(models.Model):
    """Extracted PDF text, stored once per opinion (PDFs are not persisted)."""

    opinion = models.OneToOneField(
        Opinion, on_delete=models.CASCADE, related_name="text"
    )
    full_text = models.TextField()
    extracted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Text for {self.opinion_id} ({len(self.full_text)} chars)"


class IngestionRun(models.Model):
    """Operational record of one ingest_opinions run."""

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        ANOMALY = "anomaly", "Anomaly"
        ERROR = "error", "Error"

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    periods = models.JSONField(default=list)
    pages_fetched = models.PositiveIntegerField(default=0)
    opinions_found = models.PositiveIntegerField(default=0)
    new_opinions = models.PositiveIntegerField(default=0)
    pdfs_processed = models.PositiveIntegerField(default=0)
    pdf_failures = models.PositiveIntegerField(default=0)
    matches_created = models.PositiveIntegerField(default=0)
    parser_branch = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.SUCCESS
    )
    error_summary = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"Run {self.started_at:%Y-%m-%d %H:%M} — {self.status}"
