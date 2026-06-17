"""Polite HTTP layer for mdcourts.gov.

- Honest identifying User-Agent (settings.SCRAPER_USER_AGENT).
- robots.txt fetched once per process and honored.
- Jittered exponential backoff on transient 5xx/timeouts.
- Single concurrent crawler; callers add the inter-PDF delay.
"""

import logging
import random
import time
from urllib import robotparser
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from django.conf import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://www.mdcourts.gov"
REQUEST_TIMEOUT = 45
PDF_TIMEOUT = 60
MAX_ATTEMPTS = 3


class FetchError(Exception):
    pass


class RobotsDisallowed(FetchError):
    pass


class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": settings.SCRAPER_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._robots = None
        self.pages_fetched = 0

    def _robots_allowed(self, url):
        if self._robots is None:
            parser = robotparser.RobotFileParser()
            robots_url = f"{BASE_URL}/robots.txt"
            try:
                response = self.session.get(robots_url, timeout=REQUEST_TIMEOUT)
                if response.status_code in (401, 403):
                    parser.disallow_all = True
                elif response.status_code >= 400:
                    parser.allow_all = True
                else:
                    parser.parse(response.text.splitlines())
            except requests.RequestException:
                logger.warning("Could not fetch robots.txt; assuming allowed")
                parser.allow_all = True
            self._robots = parser
        return self._robots.can_fetch(settings.SCRAPER_USER_AGENT, url)

    def _get(self, url, params=None, timeout=REQUEST_TIMEOUT):
        if urlparse(url).netloc.endswith("mdcourts.gov") and not self._robots_allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")

        last_exc = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self.session.get(url, params=params, timeout=timeout)
                if response.status_code >= 500:
                    raise requests.HTTPError(
                        f"{response.status_code} from {url}", response=response
                    )
                response.raise_for_status()
                self.pages_fetched += 1
                return response
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                transient = status is None or status >= 500
                last_exc = exc
                if not transient or attempt == MAX_ATTEMPTS:
                    break
                delay = (2**attempt) + random.uniform(0, 1)
                logger.warning(
                    "Fetch attempt %d/%d failed for %s (%s); retrying in %.1fs",
                    attempt, MAX_ATTEMPTS, url, exc, delay,
                )
                time.sleep(delay)
        raise FetchError(f"Failed to fetch {url}: {last_exc}") from last_exc

    def fetch_page(self, url, params=None):
        """GET a listing page and return BeautifulSoup.

        lxml (not html.parser) is required here: the reported-opinions CGI page
        uses unclosed <td> tags, which html.parser turns into one giant nested
        cell, breaking per-row field extraction. lxml auto-closes them.
        """
        response = self._get(url, params=params)
        return BeautifulSoup(response.text, "lxml")

    def fetch_pdf(self, url):
        """GET a PDF and return its raw bytes."""
        return self._get(url, timeout=PDF_TIMEOUT).content
