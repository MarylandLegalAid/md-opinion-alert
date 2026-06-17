"""Listing-page parsers for mdcourts.gov, lifted from the PoC
(``poc/.../md_opinion_alert.py``) nearly verbatim — the hard-won asset.

Behavioral changes from the PoC are limited to hardening:
- parsers report which layout branch they took, recorded on IngestionRun;
- the unreported parser also captures the Court column (col 0);
- structured logging so a layout change produces a clear signal.
"""

import logging
import re
from urllib.parse import urljoin

from .http import BASE_URL

logger = logging.getLogger(__name__)

UNREPORTED_URL = BASE_URL + "/appellate/unreportedopinions"
UNREPORTED_LIST_BASE = BASE_URL + "/appellate/unreportedopinions/list/"
REPORTED_URL = BASE_URL + "/opinions/opinions"
REPORTED_CGI_URL = BASE_URL + "/cgi-bin/indexlist.pl"

MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]

# Reported-opinion PDF paths encode the issuing court.
REPORTED_COURTS = {
    "/cosa/": "Appellate Court of Maryland",
    "/coa/": "Supreme Court of Maryland",
}


def court_from_reported_url(url):
    for fragment, court in REPORTED_COURTS.items():
        if fragment in url.lower():
            return court
    return ""


def get_segments(cell, num_expected):
    """
    Split a stacked table cell into individual per-case text values.
    The CGI page places all values for a column into one <td>,
    separated by <br> tags. This function splits them back out.
    """
    segments = []
    current = []

    for node in cell.children:
        node_name = getattr(node, "name", None)
        if node_name == "br":
            text = " ".join(current).strip()
            if text:
                segments.append(text)
            current = []
        elif node_name is not None:
            text = node.get_text(" ", strip=True)
            if text:
                current.append(text)
        else:
            for line in str(node).splitlines():
                line = line.strip()
                if line:
                    current.append(line)

    # Capture any trailing text after the last <br>
    text = " ".join(current).strip()
    if text:
        segments.append(text)

    # If only one segment was found but multiple are expected,
    # try splitting on runs of whitespace as a fallback
    if len(segments) <= 1 and num_expected > 1:
        raw = cell.get_text(" ", strip=True)
        sub = [s.strip() for s in re.split(r"\s{2,}|\t", raw) if s.strip()]
        if len(sub) >= num_expected:
            segments = sub

    return segments


def extract_reported_opinions_from_soup(soup):
    """
    Extract reported opinions from the CGI results page.

    The CGI page uses a stacked-cell layout: all PDF links are in
    one <td>, all case names in a sibling <td>, all dates in another.
    Each cell contains values separated by <br> tags.
    We split each cell into segments and match by position.

    Returns ``(opinions, parser_branch)`` where parser_branch is one of
    ``reported:stacked``, ``reported:per-row``, ``reported:links-only``,
    ``reported:none``.
    """
    opinions = []
    seen_urls = set()

    # Collect all /data/opinions/ PDF links in page order
    all_pdf_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".pdf") and "/data/opinions/" in href.lower():
            full_url = urljoin(BASE_URL, href)
            if full_url not in seen_urls:
                seen_urls.add(full_url)
                all_pdf_links.append((a, full_url))

    if not all_pdf_links:
        logger.warning("No reported opinion PDF links found")
        return opinions, "reported:none"

    num_links = len(all_pdf_links)
    logger.info("Found %d PDF links in CGI page", num_links)

    # Check whether all links share the same parent <td> (stacked layout)
    first_td = all_pdf_links[0][0].find_parent("td")
    all_in_one = first_td is not None and all(
        link.find_parent("td") is first_td for link, _ in all_pdf_links
    )

    if all_in_one:
        # ----------------------------------------------------------
        # Stacked-cell layout
        # ----------------------------------------------------------
        branch = "reported:stacked"
        logger.info("CGI layout: stacked cells")

        parent_row = first_td.find_parent("tr")
        if not parent_row:
            logger.warning("Could not find parent <tr> of links cell")
            for link, full_url in all_pdf_links:
                opinions.append(
                    {
                        "name": link.get_text(strip=True),
                        "url": full_url,
                        "docket": link.get_text(strip=True),
                        "date": "",
                    }
                )
            return opinions, "reported:links-only"

        all_cells = parent_row.find_all("td")
        parties_segs = []
        dates_segs = []

        for cell in all_cells:
            if cell is first_td:
                continue

            segs = get_segments(cell, num_links)
            if not segs:
                continue

            date_hits = sum(1 for s in segs if re.search(r"\d{4}-\d{2}-\d{2}", s))
            party_hits = sum(
                1
                for s in segs
                if (
                    " v. " in s
                    or " vs. " in s
                    or s.lower().startswith("in re")
                    or s.lower().startswith("in the matter")
                    or s.lower().startswith("attorney grievance")
                )
            )

            if date_hits > 0 and not dates_segs:
                dates_segs = segs
                logger.info("Dates column: %d segment(s) found", len(segs))
            if party_hits > 0 and not parties_segs:
                parties_segs = segs
                logger.info("Parties column: %d segment(s) found", len(segs))

        if not parties_segs:
            logger.warning(
                "Parties column not identified; falling back to docket numbers"
            )

        for i, (link, full_url) in enumerate(all_pdf_links):
            docket = link.get_text(strip=True)
            case_name = parties_segs[i].strip() if i < len(parties_segs) else ""
            date_str = ""
            if i < len(dates_segs):
                m = re.search(r"\d{4}-\d{2}-\d{2}", dates_segs[i])
                if m:
                    date_str = m.group(0)

            opinions.append(
                {
                    "name": case_name,
                    "url": full_url,
                    "docket": docket,
                    "date": date_str,
                }
            )

    else:
        # ----------------------------------------------------------
        # Standard per-row layout (fallback)
        # ----------------------------------------------------------
        branch = "reported:per-row"
        logger.info("CGI layout: standard per-row")

        for link, full_url in all_pdf_links:
            docket = link.get_text(strip=True)
            case_name = ""
            date_str = ""
            parent_row = link.find_parent("tr")

            if parent_row:
                cells = parent_row.find_all("td")
                for cell in cells:
                    if cell.find("a"):
                        continue
                    ct = cell.get_text(" ", strip=True)
                    if (
                        " v. " in ct
                        or " vs. " in ct
                        or ct.lower().startswith("in re")
                        or ct.lower().startswith("in the matter")
                    ) and len(ct) < 200:
                        case_name = ct
                        break
                for cell in cells:
                    ct = cell.get_text(strip=True)
                    m = re.search(r"\d{4}-\d{2}-\d{2}", ct)
                    if m:
                        date_str = m.group(0)
                        break

            opinions.append(
                {
                    "name": case_name if case_name != docket else "",
                    "url": full_url,
                    "docket": docket,
                    "date": date_str,
                }
            )

    return opinions, branch


def extract_unreported_opinions_from_soup(soup):
    """
    Extract unreported opinions from a monthly list page.
    Confirmed column order:
        Col 0: Court
        Col 1: Filed date
        Col 2: Docket (PDF link here)
        Col 3: Term
        Col 4: Judge
        Col 5: Appellant
        Col 6: Appellee
    """
    opinions = []
    seen_urls = set()

    for link in soup.find_all("a", href=True):
        href = link["href"]
        href_low = href.lower()

        if not (href_low.endswith(".pdf") and "unreported-opinions" in href_low):
            continue

        full_url = urljoin(BASE_URL, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        docket = link.get_text(strip=True)
        case_name = ""
        date_str = ""
        court = ""

        parent_row = link.find_parent("tr")
        if parent_row:
            cells = parent_row.find_all("td")

            if len(cells) > 0:
                court = cells[0].get_text(" ", strip=True)
            if len(cells) > 1:
                date_str = cells[1].get_text(strip=True)

            if len(cells) > 6:
                appellant = cells[5].get_text(" ", strip=True)
                appellee = cells[6].get_text(" ", strip=True)
                if appellant and appellee:
                    case_name = appellant + " v. " + appellee
                elif appellant:
                    case_name = appellant
            elif len(cells) > 5:
                case_name = cells[5].get_text(" ", strip=True)

        opinions.append(
            {
                "name": case_name,
                "url": full_url,
                "docket": docket,
                "date": date_str,
                "court": court,
            }
        )

    return opinions
