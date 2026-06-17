import datetime
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from ingestion.models import IngestionRun, Opinion
from ingestion.pipeline import (
    canonicalize_url,
    get_backfill_periods,
    get_periods,
    parse_filed_date,
    run_ingestion,
)

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_TODAY = datetime.date(2026, 6, 11)


class HelperTests(TestCase):
    def test_canonicalize_url(self):
        self.assertEqual(
            canonicalize_url("HTTP://WWW.MDCourts.gov/data/opinions/X.pdf#page=2 "),
            "https://www.mdcourts.gov/data/opinions/X.pdf",
        )

    def test_parse_filed_date_formats(self):
        self.assertEqual(parse_filed_date("2026-06-04"), datetime.date(2026, 6, 4))
        self.assertEqual(parse_filed_date("05-29-2026"), datetime.date(2026, 5, 29))
        self.assertEqual(parse_filed_date("5/29/2026"), datetime.date(2026, 5, 29))
        self.assertIsNone(parse_filed_date("corrected"))
        self.assertIsNone(parse_filed_date(""))

    def test_get_periods(self):
        self.assertEqual(get_periods(2, today=FAKE_TODAY), [(2026, 6), (2026, 5)])
        self.assertEqual(
            get_periods(3, today=datetime.date(2026, 1, 5)),
            [(2026, 1), (2025, 12), (2025, 11)],
        )

    def test_backfill_periods_span_2024_to_now(self):
        periods = get_backfill_periods(today=FAKE_TODAY)
        self.assertEqual(periods[0], (2026, 6))
        self.assertEqual(periods[-1], (2024, 1))
        self.assertEqual(len(periods), 30)


class FakeFetcher:
    """Serves the saved live captures; fails on unexpected URLs."""

    def __init__(self, empty=False):
        self.pages_fetched = 0
        self.empty = empty
        self.pdf_urls = []

    def fetch_page(self, url, params=None):
        self.pages_fetched += 1
        if self.empty:
            return BeautifulSoup("<html></html>", "lxml")
        if "unreportedopinions/list" in url:
            return BeautifulSoup((FIXTURES / "unreported-202605.html").read_text(), "lxml")
        if "indexlist.pl" in url:
            return BeautifulSoup((FIXTURES / "reported-2026.html").read_text(), "lxml")
        raise AssertionError(f"unexpected page fetch: {url}")

    def fetch_pdf(self, url):
        self.pdf_urls.append(url)
        return b"%PDF-fake"


class RunIngestionTests(TestCase):
    def run_with_fakes(self, fetcher, **kwargs):
        with (
            patch("ingestion.pipeline.Fetcher", return_value=fetcher),
            patch(
                "ingestion.pipeline.extract_pdf_text",
                return_value="The tenant raised a rent escrow defense.",
            ),
            patch("ingestion.pipeline.time.sleep"),
        ):
            return run_ingestion(today=FAKE_TODAY, **kwargs)

    def test_full_run_stores_opinions(self):
        run = self.run_with_fakes(FakeFetcher())
        self.assertEqual(run.status, IngestionRun.Status.SUCCESS)
        # 112 unreported + 87 reported in the fixtures
        self.assertEqual(run.opinions_found, 199)
        self.assertEqual(run.new_opinions, 199)
        self.assertEqual(run.pdf_failures, 0)
        self.assertEqual(run.parser_branch, "reported:per-row")
        self.assertIsNotNone(run.finished_at)

        reported = Opinion.objects.filter(opinion_type="reported")
        self.assertEqual(reported.count(), 87)
        first = Opinion.objects.get(source_url__endswith="0634s24.pdf")
        self.assertEqual(first.case_name, "Hicks v. State")
        self.assertEqual(first.court, "Appellate Court of Maryland")
        self.assertEqual(first.filed_date, datetime.date(2026, 6, 4))
        self.assertIn("rent escrow", first.text.full_text)

        unreported = Opinion.objects.get(docket="1421", opinion_type="unreported")
        self.assertEqual(unreported.filed_date, datetime.date(2026, 5, 29))

    def test_rerun_is_idempotent(self):
        self.run_with_fakes(FakeFetcher())
        second = self.run_with_fakes(FakeFetcher())
        self.assertEqual(second.status, IngestionRun.Status.SUCCESS)
        self.assertEqual(second.opinions_found, 199)
        self.assertEqual(second.new_opinions, 0)
        self.assertEqual(Opinion.objects.count(), 199)

    def test_zero_opinions_is_anomaly_and_emails_staff(self):
        staff = get_user_model().objects.create_user(
            username="admin", email="admin@org.example", is_staff=True
        )
        run = self.run_with_fakes(FakeFetcher(empty=True))
        self.assertEqual(run.status, IngestionRun.Status.ANOMALY)
        self.assertIn("0 opinions", run.error_summary)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [staff.email])
        self.assertIn("ANOMALY", mail.outbox[0].subject)

    def test_pdf_failures_counted_and_retried_next_run(self):
        fetcher = FakeFetcher()
        with (
            patch("ingestion.pipeline.Fetcher", return_value=fetcher),
            patch(
                "ingestion.pipeline.extract_pdf_text",
                side_effect=ValueError("broken pdf"),
            ),
            patch("ingestion.pipeline.time.sleep"),
        ):
            run = run_ingestion(today=FAKE_TODAY)
        self.assertEqual(run.pdf_failures, 199)
        self.assertEqual(run.new_opinions, 0)
        self.assertEqual(Opinion.objects.count(), 0)
        self.assertEqual(run.status, IngestionRun.Status.ANOMALY)

    def test_listing_fetch_error_marks_run_error(self):
        class BrokenFetcher(FakeFetcher):
            def fetch_page(self, url, params=None):
                raise OSError("connection refused")

        run = self.run_with_fakes(BrokenFetcher())
        self.assertEqual(run.status, IngestionRun.Status.ERROR)
        self.assertIn("connection refused", run.error_summary)
        self.assertIsNotNone(run.finished_at)

    def test_healthz_reports_last_successful_run(self):
        self.run_with_fakes(FakeFetcher())
        response = self.client.get("/healthz", secure=True)
        self.assertIsNotNone(response.json()["last_ingestion_at"])
