from pathlib import Path

from bs4 import BeautifulSoup
from django.test import SimpleTestCase

from ingestion import scrapers

FIXTURES = Path(__file__).parent / "fixtures"


def load_soup(name):
    # lxml, matching Fetcher.fetch_page (html.parser breaks on the CGI page's
    # unclosed <td> tags)
    return BeautifulSoup((FIXTURES / name).read_text(), "lxml")


class ReportedParserTests(SimpleTestCase):
    """Against a live capture of the CGI results page (2026-06-11)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.opinions, cls.branch = scrapers.extract_reported_opinions_from_soup(
            load_soup("reported-2026.html")
        )

    def test_finds_all_opinions(self):
        self.assertEqual(len(self.opinions), 87)

    def test_parser_branch_reported(self):
        self.assertEqual(self.branch, "reported:per-row")

    def test_first_opinion_fields(self):
        first = self.opinions[0]
        self.assertEqual(first["name"], "Hicks v. State")
        self.assertEqual(first["docket"], "0634/24")
        self.assertEqual(first["date"], "2026-06-04")
        self.assertTrue(first["url"].endswith("/data/opinions/cosa/2026/0634s24.pdf"))

    def test_case_names_mostly_present(self):
        named = sum(1 for o in self.opinions if o["name"])
        self.assertGreater(named / len(self.opinions), 0.9)

    def test_no_duplicate_urls(self):
        urls = [o["url"] for o in self.opinions]
        self.assertEqual(len(urls), len(set(urls)))

    def test_court_derived_from_url(self):
        self.assertEqual(
            scrapers.court_from_reported_url(self.opinions[0]["url"]),
            "Appellate Court of Maryland",
        )
        coa = [o for o in self.opinions if "/coa/" in o["url"]]
        self.assertTrue(coa)
        self.assertEqual(
            scrapers.court_from_reported_url(coa[0]["url"]),
            "Supreme Court of Maryland",
        )


class UnreportedParserTests(SimpleTestCase):
    """Against a live capture of the May 2026 monthly list (2026-06-11)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.opinions = scrapers.extract_unreported_opinions_from_soup(
            load_soup("unreported-202605.html")
        )

    def test_finds_all_opinions(self):
        self.assertEqual(len(self.opinions), 112)

    def test_first_opinion_fields(self):
        first = self.opinions[0]
        self.assertEqual(first["name"], "Findley, Orean Obrian v. State")
        self.assertEqual(first["docket"], "1421")
        self.assertEqual(first["date"], "05-29-2026")
        self.assertEqual(first["court"], "Appellate Court of Maryland")
        self.assertIn("unreported-opinions", first["url"])

    def test_all_have_urls_and_dockets(self):
        for op in self.opinions:
            self.assertTrue(op["url"].lower().endswith(".pdf"))
            self.assertTrue(op["docket"])


class ZeroResultTests(SimpleTestCase):
    def test_empty_page_reports_none_branch(self):
        soup = BeautifulSoup("<html><body><p>maintenance</p></body></html>", "lxml")
        opinions, branch = scrapers.extract_reported_opinions_from_soup(soup)
        self.assertEqual(opinions, [])
        self.assertEqual(branch, "reported:none")
        self.assertEqual(scrapers.extract_unreported_opinions_from_soup(soup), [])
