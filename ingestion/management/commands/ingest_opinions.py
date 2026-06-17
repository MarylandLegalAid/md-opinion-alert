from django.core.management.base import BaseCommand, CommandError

from ingestion.models import IngestionRun
from ingestion.pipeline import run_ingestion


class Command(BaseCommand):
    help = (
        "Scrape mdcourts.gov for reported/unreported appellate opinions, "
        "store new ones, and run keyword matching."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--months",
            type=int,
            default=1,
            help="Trailing months of unreported listings to check (default 1).",
        )
        parser.add_argument(
            "--year",
            type=int,
            help="Ingest a single calendar year (all 12 unreported months + "
            "the reported listing for that year).",
        )
        parser.add_argument(
            "--backfill",
            action="store_true",
            help="One-time historical ingest from BACKFILL_START_YEAR onward.",
        )
        parser.add_argument(
            "--diagnostic",
            action="store_true",
            help="Dump raw listing HTML and parsed candidates to var/diagnostics/.",
        )

    def handle(self, *args, **options):
        if options["backfill"] and options["year"]:
            raise CommandError("--backfill and --year are mutually exclusive.")

        run = run_ingestion(
            months=options["months"],
            year=options["year"],
            backfill=options["backfill"],
            diagnostic=options["diagnostic"],
        )

        summary = (
            f"Run finished: status={run.status} found={run.opinions_found} "
            f"new={run.new_opinions} pdf_failures={run.pdf_failures} "
            f"matches={run.matches_created} branch={run.parser_branch}"
        )
        if run.status == IngestionRun.Status.ERROR:
            raise CommandError(f"{summary}\n{run.error_summary}")
        if run.status == IngestionRun.Status.ANOMALY:
            self.stderr.write(self.style.WARNING(f"{summary}\n{run.error_summary}"))
        else:
            self.stdout.write(self.style.SUCCESS(summary))
