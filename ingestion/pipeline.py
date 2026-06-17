"""Ingestion orchestration: periods → scrape → dedup → PDF text → store.

One polite crawl per run regardless of user count. Matching is
decoupled: Phase 2 plugs in via ``matching.engine.match_opinions``.
"""

import datetime
import json
import logging
import time
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from . import scrapers
from .http import Fetcher
from .models import IngestionRun, Opinion, OpinionText
from .pdf import extract_pdf_text

logger = logging.getLogger(__name__)

try:
    from matching.engine import match_opinions  # arrives in Phase 2
except ImportError:
    match_opinions = None

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%B %d, %Y")


def canonicalize_url(url):
    """Normalize a PDF URL for dedup keying."""
    scheme, netloc, path, query, _fragment = urlsplit(url.strip())
    return urlunsplit(("https", netloc.lower(), path, query, ""))


def parse_filed_date(date_str):
    for fmt in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(date_str.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def get_periods(months, today=None):
    """Trailing (year, month) tuples, most recent first (PoC ``get_periods``)."""
    today = today or datetime.date.today()
    periods = []
    for i in range(months):
        month = today.month - i
        year = today.year
        if month <= 0:
            month += 12
            year -= 1
        periods.append((year, month))
    return periods


def get_backfill_periods(today=None):
    """Every (year, month) from BACKFILL_START_YEAR-01 through the current month."""
    today = today or datetime.date.today()
    start = datetime.date(settings.BACKFILL_START_YEAR, 1, 1)
    periods = []
    cursor = today.replace(day=1)
    while cursor >= start:
        periods.append((cursor.year, cursor.month))
        cursor = (cursor - datetime.timedelta(days=1)).replace(day=1)
    return periods


class Pipeline:
    def __init__(self, run, fetcher=None, diagnostic_dir=None):
        self.run = run
        self.fetcher = fetcher or Fetcher()
        self.diagnostic_dir = diagnostic_dir
        self.parser_branches = set()

    # -- scraping ------------------------------------------------------------

    def collect_candidates(self, periods):
        """Scrape listing pages for the given periods → candidate dicts."""
        candidates = []
        years_fetched = set()

        for year, month in periods:
            label = f"{scrapers.MONTH_NAMES[month - 1].title()} {year}"
            logger.info("Checking period: %s", label)

            url = f"{scrapers.UNREPORTED_LIST_BASE}{year}{month:02d}"
            soup = self.fetcher.fetch_page(url)
            self._dump_diagnostic(f"unreported-{year}{month:02d}.html", soup)
            unreported = scrapers.extract_unreported_opinions_from_soup(soup)
            logger.info("Found %d unreported opinion(s) for %s", len(unreported), label)
            for op in unreported:
                op["opinion_type"] = Opinion.OpinionType.UNREPORTED
            candidates.extend(unreported)

            if year not in years_fetched:
                years_fetched.add(year)
                params = {
                    "court": "both",
                    "year": str(year),
                    "order": "bydate",
                    "submit": "Submit",
                }
                soup = self.fetcher.fetch_page(scrapers.REPORTED_CGI_URL, params=params)
                self._dump_diagnostic(f"reported-{year}.html", soup)
                reported, branch = scrapers.extract_reported_opinions_from_soup(soup)
                self.parser_branches.add(branch)
                logger.info("Found %d reported opinion(s) for %s", len(reported), year)
                for op in reported:
                    op["opinion_type"] = Opinion.OpinionType.REPORTED
                    op["court"] = scrapers.court_from_reported_url(op["url"])
                candidates.extend(reported)

        # Dedup within the run on canonical URL
        deduped = {}
        for op in candidates:
            deduped.setdefault(canonicalize_url(op["url"]), op)
        self._dump_diagnostic("candidates.json", deduped)
        return deduped

    # -- storage -------------------------------------------------------------

    def ingest(self, candidates):
        """Download + store every candidate not already in the DB.

        Returns the ids of the newly created Opinion rows.
        """
        existing = set(
            Opinion.objects.filter(source_url__in=candidates).values_list(
                "source_url", flat=True
            )
        )
        new_urls = [u for u in candidates if u not in existing]
        new_ids = []
        logger.info(
            "%d candidate(s), %d already stored, %d new",
            len(candidates), len(existing), len(new_urls),
        )

        for url in new_urls:
            op = candidates[url]
            logger.info("[NEW] %s — %s", op["name"] or op["docket"], url)
            try:
                raw = self.fetcher.fetch_pdf(url)
                text = extract_pdf_text(raw)
            except Exception:
                # Failed PDFs are not recorded, so the next run retries them.
                logger.exception("PDF processing failed for %s", url)
                self.run.pdf_failures += 1
                continue
            finally:
                time.sleep(settings.INGEST_PDF_DELAY_SECONDS)

            if not text:
                logger.warning("No text extracted from %s (scanned PDF?)", url)

            with transaction.atomic():
                opinion = Opinion.objects.create(
                    source_url=url,
                    case_name=op["name"][:500],
                    docket=op["docket"][:200],
                    court=op.get("court", "")[:200],
                    opinion_type=op["opinion_type"],
                    filed_date=parse_filed_date(op.get("date", "")),
                )
                OpinionText.objects.create(opinion=opinion, full_text=text)
            new_ids.append(opinion.pk)
            self.run.new_opinions += 1
            self.run.pdfs_processed += 1

        return new_ids

    def _dump_diagnostic(self, filename, content):
        if not self.diagnostic_dir:
            return
        path = self.diagnostic_dir / filename
        if isinstance(content, dict):
            path.write_text(json.dumps(content, indent=2, default=str))
        else:
            path.write_text(str(content))
        logger.info("Diagnostic dump: %s", path)


def run_ingestion(months=1, year=None, backfill=False, diagnostic=False, today=None):
    """Execute one ingestion run and return its IngestionRun record."""
    if backfill:
        periods = get_backfill_periods(today=today)
    elif year:
        periods = [(year, m) for m in range(12, 0, -1)]
    else:
        periods = get_periods(months, today=today)

    run = IngestionRun.objects.create(periods=[f"{y}-{m:02d}" for y, m in periods])

    diagnostic_dir = None
    if diagnostic:
        stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
        diagnostic_dir = settings.BASE_DIR / "var" / "diagnostics" / stamp
        diagnostic_dir.mkdir(parents=True, exist_ok=True)

    pipeline = Pipeline(run, diagnostic_dir=diagnostic_dir)
    try:
        candidates = pipeline.collect_candidates(periods)
        run.opinions_found = len(candidates)
        new_ids = pipeline.ingest(candidates)

        if match_opinions is not None and new_ids:
            run.matches_created = match_opinions(
                Opinion.objects.filter(pk__in=new_ids)
            )
    except Exception as exc:
        run.status = IngestionRun.Status.ERROR
        run.error_summary = f"{type(exc).__name__}: {exc}"
        logger.exception("Ingestion run failed")
    else:
        _evaluate_anomalies(run)
    finally:
        run.pages_fetched = pipeline.fetcher.pages_fetched
        run.parser_branch = ", ".join(sorted(pipeline.parser_branches))
        run.finished_at = timezone.now()
        run.save()

    if run.status != IngestionRun.Status.SUCCESS:
        _alert_admins(run)
    return run


def _evaluate_anomalies(run):
    """'zero found' triggers a check, never silence."""
    problems = []
    if run.opinions_found == 0:
        problems.append(
            "0 opinions found across all listing pages — possible layout change."
        )
    attempted = run.pdfs_processed + run.pdf_failures
    if attempted and run.pdf_failures / attempted > settings.ANOMALY_PDF_FAILURE_THRESHOLD:
        problems.append(
            f"PDF failure rate {run.pdf_failures}/{attempted} exceeds "
            f"{settings.ANOMALY_PDF_FAILURE_THRESHOLD:.0%} threshold."
        )
    if problems:
        run.status = IngestionRun.Status.ANOMALY
        run.error_summary = "\n".join(problems)


def _alert_admins(run):
    from django.contrib.auth import get_user_model

    recipients = list(
        get_user_model()
        .objects.filter(is_staff=True, is_active=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    if not recipients:
        logger.warning("Ingestion %s but no admin emails to notify", run.status)
        return

    body = (
        f"Ingestion run {run.started_at:%Y-%m-%d %H:%M} finished with "
        f"status={run.status}.\n\n"
        f"Periods: {', '.join(run.periods)}\n"
        f"Pages fetched: {run.pages_fetched}\n"
        f"Opinions found: {run.opinions_found}\n"
        f"New opinions: {run.new_opinions}\n"
        f"PDFs processed: {run.pdfs_processed} (failures: {run.pdf_failures})\n"
        f"Parser branch: {run.parser_branch}\n\n"
        f"{run.error_summary}\n\n"
        "Check the IngestionRun entry in Django admin; for layout changes run "
        "`manage.py ingest_opinions --diagnostic`."
    )
    send_mail(
        subject=f"[MD Opinion Alert] Ingestion {run.status.upper()}",
        message=body,
        from_email=None,
        recipient_list=recipients,
        fail_silently=True,
    )
    logger.info("Anomaly alert sent to %d admin(s)", len(recipients))
