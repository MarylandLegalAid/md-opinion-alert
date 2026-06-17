#!/usr/bin/env python3
"""
Maryland Appellate Court Opinion Keyword Alert Tool
Compatible with Python 3.7+

Changes in this version:
  - Whole-word keyword matching (rent != parent/transparent)
  - Persistent tkinter dialog for both match and no-match outcomes
  - Fixed reported opinions case name extraction (stacked-cell layout)
"""

# ============================================================
# IMPORTS
# ============================================================
import requests
from bs4 import BeautifulSoup
import pdfplumber
import io
import json
import os
import sys
import re
import time
import datetime
import logging
import webbrowser
from urllib.parse import urljoin


# ============================================================
# SECTION 1: CONFIGURATION
# ============================================================

KEYWORDS = [
    "tenant",
    "landlord",
    "Real Property",
    "Consumer Protection Act",
    "Consumer Protection",
    "rental license",
    "rent escrow",
    "ejectment",
    "possession",
    "eviction",
    "warranty of habitability",
    "covenant of quiet enjoyment",
    "retaliatory eviction",
    "lease",
    "failure to pay rent",
    "holding over",
    "breach of lease",
    "landlord-tenant",
    "wrongful detainer",
    "rent",
    "housing code",
    "housing inspector",
    "MCALA",
    "MCDCA",
    "lead inspection",
    "due process",
    "procedural due process",
    "substantive due process",
]

MONTHS_TO_CHECK = 1

SHOW_WINDOWS_NOTIFICATION = True
AUTO_OPEN_REPORT          = True

USE_EMAIL       = False
USE_TEAMS       = False
EMAIL_RECIPIENT = "yourname@yourfirm.com"

PROCESSED_FILE = "processed_opinions.json"
LOG_FILE       = "opinion_scraper.log"
RESULTS_FILE   = "latest_results.html"

DELAY_BETWEEN_PDFS = 2
REQUEST_TIMEOUT    = 45
DIAGNOSTIC_MODE    = False

# ============================================================
# CONFIG FILE OVERRIDE
# Written by MDCourtAlertSetup -- do not edit this block manually.
# Edit settings using the setup tool instead.
# ============================================================
_config_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config.json"
)
if os.path.exists(_config_path):
    try:
        with open(_config_path, "r", encoding="utf-8") as _f:
            _cfg = json.load(_f)
        KEYWORDS                  = _cfg.get("keywords", KEYWORDS)
        MONTHS_TO_CHECK           = _cfg.get("months_to_check", MONTHS_TO_CHECK)
        SHOW_WINDOWS_NOTIFICATION = _cfg.get("show_notification", SHOW_WINDOWS_NOTIFICATION)
        AUTO_OPEN_REPORT          = _cfg.get("auto_open_report", AUTO_OPEN_REPORT)
    except Exception:
        pass   # Silently fall back to hardcoded defaults


# ============================================================
# SECTION 2: CONSTANTS
# ============================================================

BASE_URL             = "https://www.mdcourts.gov"
UNREPORTED_URL       = BASE_URL + "/appellate/unreportedopinions"
UNREPORTED_LIST_BASE = BASE_URL + "/appellate/unreportedopinions/list/"
REPORTED_URL         = BASE_URL + "/opinions/opinions"
REPORTED_CGI_URL     = BASE_URL + "/cgi-bin/indexlist.pl"

MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december"
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ============================================================
# SECTION 3: LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ============================================================
# SECTION 4: PROCESSED-OPINION TRACKING
# ============================================================

def load_processed():
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_processed(processed):
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(processed)), f, indent=2)
    log.info("Saved %d processed URLs to %s", len(processed), PROCESSED_FILE)


# ============================================================
# SECTION 5: PAGE FETCHING
# ============================================================

def fetch_page(url, params=None):
    """GET a page and return BeautifulSoup, or None on error."""
    try:
        resp = requests.get(
            url, params=params, headers=HEADERS,
            timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")

    except requests.RequestException as e:
        log.error("Failed to fetch %s: %s", url, e)
        return None


# ============================================================
# SECTION 6: OPINION EXTRACTION
# ============================================================

def get_segments(cell, num_expected):
    """
    Split a stacked table cell into individual per-case text values.
    The CGI page places all values for a column into one <td>,
    separated by <br> tags. This function splits them back out.
    """
    segments = []
    current  = []

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
        raw  = cell.get_text(" ", strip=True)
        sub  = [s.strip() for s in re.split(r"\s{2,}|\t", raw) if s.strip()]
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
    """
    opinions  = []
    seen_urls = set()

    # Collect all /data/opinions/ PDF links in page order
    all_pdf_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if (href.lower().endswith(".pdf")
                and "/data/opinions/" in href.lower()):
            full_url = urljoin(BASE_URL, href)
            if full_url not in seen_urls:
                seen_urls.add(full_url)
                all_pdf_links.append((a, full_url))

    if not all_pdf_links:
        log.warning("    No reported opinion PDF links found.")
        return opinions

    num_links = len(all_pdf_links)
    log.info("    Found %d PDF links in CGI page.", num_links)

    # Check whether all links share the same parent <td> (stacked layout)
    first_td   = all_pdf_links[0][0].find_parent("td")
    all_in_one = (
        first_td is not None
        and all(
            link.find_parent("td") is first_td
            for link, _ in all_pdf_links
        )
    )

    if all_in_one:
        # ----------------------------------------------------------
        # Stacked-cell layout
        # ----------------------------------------------------------
        log.info("    CGI layout: stacked cells.")

        parent_row = first_td.find_parent("tr")
        if not parent_row:
            log.warning("    Could not find parent <tr> of links cell.")
            for link, full_url in all_pdf_links:
                opinions.append({
                    "name":    link.get_text(strip=True),
                    "url":     full_url,
                    "docket":  link.get_text(strip=True),
                    "date":    "",
                    "is_html": False,
                })
            return opinions

        all_cells    = parent_row.find_all("td")
        parties_segs = []
        dates_segs   = []

        for cell in all_cells:
            if cell is first_td:
                continue

            segs = get_segments(cell, num_links)
            if not segs:
                continue

            date_hits = sum(
                1 for s in segs
                if re.search(r"\d{4}-\d{2}-\d{2}", s)
            )
            party_hits = sum(
                1 for s in segs
                if (" v. " in s
                    or " vs. " in s
                    or s.lower().startswith("in re")
                    or s.lower().startswith("in the matter")
                    or s.lower().startswith("attorney grievance"))
            )

            if date_hits > 0 and not dates_segs:
                dates_segs = segs
                log.info(
                    "    Dates column: %d segment(s) found.", len(segs)
                )
            if party_hits > 0 and not parties_segs:
                parties_segs = segs
                log.info(
                    "    Parties column: %d segment(s) found.", len(segs)
                )

        if not parties_segs:
            log.warning(
                "    Parties column not identified. "
                "Will display docket numbers only."
            )

        for i, (link, full_url) in enumerate(all_pdf_links):
            docket    = link.get_text(strip=True)
            case_name = (
                parties_segs[i].strip()
                if i < len(parties_segs)
                else ""
            )
            date_str = ""
            if i < len(dates_segs):
                m = re.search(r"\d{4}-\d{2}-\d{2}", dates_segs[i])
                if m:
                    date_str = m.group(0)

            display_name = (
                case_name + "  [" + docket + "]"
                if case_name
                else docket
            )

            opinions.append({
                "name":    display_name,
                "url":     full_url,
                "docket":  docket,
                "date":    date_str,
                "is_html": False,
            })

    else:
        # ----------------------------------------------------------
        # Standard per-row layout (fallback)
        # ----------------------------------------------------------
        log.info("    CGI layout: standard per-row.")

        for link, full_url in all_pdf_links:
            docket     = link.get_text(strip=True)
            case_name  = ""
            date_str   = ""
            parent_row = link.find_parent("tr")

            if parent_row:
                cells = parent_row.find_all("td")
                for cell in cells:
                    if cell.find("a"):
                        continue
                    ct = cell.get_text(" ", strip=True)
                    if ((" v. " in ct or " vs. " in ct
                            or ct.lower().startswith("in re")
                            or ct.lower().startswith("in the matter"))
                            and len(ct) < 200):
                        case_name = ct
                        break
                for cell in cells:
                    ct = cell.get_text(strip=True)
                    m  = re.search(r"\d{4}-\d{2}-\d{2}", ct)
                    if m:
                        date_str = m.group(0)
                        break

            display_name = (
                case_name + "  [" + docket + "]"
                if case_name and case_name != docket
                else docket
            )

            opinions.append({
                "name":    display_name,
                "url":     full_url,
                "docket":  docket,
                "date":    date_str,
                "is_html": False,
            })

    return opinions


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
    opinions  = []
    seen_urls = set()

    for link in soup.find_all("a", href=True):
        href     = link["href"]
        href_low = href.lower()

        if not (href_low.endswith(".pdf")
                and "unreported-opinions" in href_low):
            continue

        full_url = urljoin(BASE_URL, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        docket    = link.get_text(strip=True)
        case_name = ""
        date_str  = ""

        parent_row = link.find_parent("tr")
        if parent_row:
            cells = parent_row.find_all("td")

            if len(cells) > 1:
                date_str = cells[1].get_text(strip=True)

            if len(cells) > 6:
                appellant = cells[5].get_text(" ", strip=True)
                appellee  = cells[6].get_text(" ", strip=True)
                if appellant and appellee:
                    case_name = appellant + " v. " + appellee
                elif appellant:
                    case_name = appellant
            elif len(cells) > 5:
                case_name = cells[5].get_text(" ", strip=True)

        display_name = (
            case_name + "  [" + docket + "]"
            if case_name
            else docket
        )

        opinions.append({
            "name":    display_name,
            "url":     full_url,
            "docket":  docket,
            "date":    date_str,
            "is_html": False,
        })

    return opinions


def get_reported_opinions(year):
    """Query CGI script for reported opinions in a given year."""
    params = {
        "court":  "both",
        "year":   str(year),
        "order":  "bydate",
        "submit": "Submit",
    }
    log.info("    Fetching reported opinions for year %s...", year)
    soup = fetch_page(REPORTED_CGI_URL, params)
    if not soup:
        return []
    opinions = extract_reported_opinions_from_soup(soup)
    log.info("    Found %d reported opinion(s).", len(opinions))
    return opinions


def get_unreported_opinions(year, month):
    """
    Fetch unreported opinions from confirmed direct URL:
        /appellate/unreportedopinions/list/YYYYMM
    """
    month_name = MONTH_NAMES[month - 1]
    target_url = (
        UNREPORTED_LIST_BASE + str(year) + ("%02d" % month)
    )
    log.info(
        "    Fetching unreported opinions for %s %s...",
        month_name.title(), year
    )
    soup = fetch_page(target_url)
    if not soup:
        return []
    opinions = extract_unreported_opinions_from_soup(soup)
    log.info("    Found %d unreported opinion(s).", len(opinions))
    return opinions


# ============================================================
# SECTION 7: TEXT EXTRACTION
# ============================================================

def extract_pdf_text(pdf_url):
    """Download a PDF and return its full extracted text."""
    try:
        resp = requests.get(
            pdf_url, headers=HEADERS, timeout=60, stream=True
        )
        resp.raise_for_status()
        raw = resp.content

        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            pages = []
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
            return "\n".join(pages)

    except Exception as e:
        log.error("PDF extraction failed for %s: %s", pdf_url, e)
        return ""


# ============================================================
# SECTION 8: KEYWORD MATCHING
# ============================================================

def find_keywords(text):
    """
    Search for keywords using whole-word boundary matching.
    \b ensures 'rent' does not match 'parent' or 'transparent'.
    'lease' does not match 'release'. Etc.
    """
    results = []
    if not text:
        return results

    for kw in KEYWORDS:
        pattern = re.compile(
            r"\b" + re.escape(kw) + r"\b",
            re.IGNORECASE
        )
        hits = list(pattern.finditer(text))
        if not hits:
            continue

        snippets = []
        for hit in hits[:3]:
            start   = max(0, hit.start() - 120)
            end     = min(len(text), hit.end() + 120)
            snippet = text[start:end].replace("\n", " ").strip()
            snippets.append("..." + snippet + "...")

        results.append({
            "keyword":  kw,
            "count":    len(hits),
            "snippets": snippets,
        })

    return results


# ============================================================
# SECTION 9: HTML REPORT
# ============================================================

def build_html_report(matches):
    """Build a styled HTML report listing all matching opinions."""
    ts = datetime.datetime.now().strftime("%B %d, %Y at %I:%M %p")

    html = (
        "<!DOCTYPE html>\n"
        "<html lang='en'>\n"
        "<head>\n"
        "<meta charset='utf-8'>\n"
        "<title>MD Appellate Court Opinion Alert</title>\n"
        "<style>\n"
        "body { font-family: Calibri, Arial, sans-serif;"
        " max-width: 900px; margin: 24px auto; color: #222;"
        " line-height: 1.5; }\n"
        "h1 { color: #002868; border-bottom: 3px solid #BF0A30;"
        " padding-bottom: 6px; }\n"
        ".card { background: #f4f6fb; border-left: 5px solid #002868;"
        " padding: 14px 18px; margin: 18px 0; border-radius: 5px; }\n"
        ".title { font-size: 1.1em; font-weight: bold; }\n"
        ".meta { color: #555; font-size: 0.88em; margin: 3px 0 10px; }\n"
        ".tag { display: inline-block; background: #002868; color: #fff;"
        " padding: 2px 9px; border-radius: 3px; font-size: 0.82em;"
        " margin: 2px 3px 4px 0; }\n"
        ".snippet { background: #fff; border: 1px solid #ccd;"
        " padding: 7px 11px; margin: 5px 0; font-size: 0.88em;"
        " border-radius: 4px; }\n"
        "mark { background: #ffe066; padding: 1px 2px; }\n"
        "summary { cursor: pointer; color: #002868;"
        " font-weight: bold; margin-top: 8px; }\n"
        "a { color: #002868; }\n"
        ".footer { margin-top: 36px; font-size: 0.82em; color: #888; }\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        "<h1>Maryland Appellate Court Opinion Alert</h1>\n"
        "<p>Generated: " + ts + "<br>\n"
        "<strong>" + str(len(matches))
        + " opinion(s)</strong> matched your keyword list.</p>\n"
        "<hr>\n"
    )

    for m in matches:
        kw_tags = ""
        for kw in m["keywords_found"]:
            kw_tags += (
                "<span class='tag'>"
                + kw["keyword"] + " x" + str(kw["count"])
                + "</span>"
            )

        snippet_blocks = ""
        for kw in m["keywords_found"][:6]:
            snippet_blocks += (
                "<p style='margin:6px 0 2px'><strong>"
                + kw["keyword"] + "</strong>:</p>\n"
            )
            for snip in kw["snippets"][:2]:
                highlighted = re.sub(
                    r"(\b" + re.escape(kw["keyword"]) + r"\b)",
                    r"<mark>\1</mark>",
                    snip,
                    flags=re.IGNORECASE
                )
                snippet_blocks += (
                    "<div class='snippet'>"
                    + highlighted + "</div>\n"
                )

        meta_parts = [m["source"]]
        if m.get("docket"):
            meta_parts.append("Docket: " + m["docket"])
        if m.get("date"):
            meta_parts.append(m["date"])

        html += (
            "\n<div class='card'>\n"
            "  <div class='title'>"
            "<a href='" + m["url"] + "' target='_blank'>"
            + m["name"] + "</a></div>\n"
            "  <div class='meta'>"
            + " &bull; ".join(meta_parts) + "</div>\n"
            "  <div>" + kw_tags + "</div>\n"
            "  <details>\n"
            "    <summary>Show keyword context</summary>\n"
            + snippet_blocks
            + "  </details>\n"
            "</div>\n"
        )

    html += (
        "\n<div class='footer'>\n"
        "Sources: "
        "<a href='" + REPORTED_URL + "'>Reported Opinions</a> | "
        "<a href='" + UNREPORTED_URL + "'>Unreported Opinions</a><br>\n"
        "Generated automatically by the MD Opinion Alert Tool.\n"
        "</div>\n</body>\n</html>"
    )

    return html


# ============================================================
# SECTION 10: NOTIFICATIONS
# ============================================================

def show_persistent_notification(title, message):
    """
    Show a dialog box that stays on screen until the user clicks OK.
    Uses Python's built-in tkinter -- no pip install required.
    Floats above all other windows.
    Called for BOTH match and no-match outcomes.
    """
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.lift()
        root.focus_force()

        messagebox.showinfo(title, message, parent=root)
        root.destroy()

        log.info("Notification shown: %s", title)

    except Exception as e:
        log.warning("tkinter notification failed: %s", e)
        try:
            from plyer import notification
            notification.notify(
                title=title,
                message=message,
                app_name="MD Opinion Alert",
                timeout=60,
            )
        except Exception as e2:
            log.warning("Plyer fallback also failed: %s", e2)


def open_report_in_browser():
    """Open the HTML report in the default browser."""
    try:
        report_path = os.path.abspath(RESULTS_FILE)
        file_url    = "file:///" + report_path.replace("\\", "/")
        webbrowser.open(file_url)
        log.info("Opened report in browser: %s", report_path)
    except Exception as e:
        log.warning("Could not open browser: %s", e)


# ============================================================
# SECTION 11: MAIN
# ============================================================

def get_periods():
    """Return list of (year, month) tuples to check."""
    today   = datetime.date.today()
    periods = []
    for i in range(MONTHS_TO_CHECK):
        month = today.month - i
        year  = today.year
        if month <= 0:
            month += 12
            year  -= 1
        periods.append((year, month))
    return periods


def main():
    log.info("=" * 60)
    log.info("MD Appellate Court Opinion Scraper -- Run started")
    log.info(
        "Timestamp: %s",
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    log.info("=" * 60)

    processed     = load_processed()
    all_matches   = []
    periods       = get_periods()
    years_fetched = set()

    for year, month in periods:
        label = MONTH_NAMES[month - 1].title() + " " + str(year)
        log.info("\n--- Checking period: %s ---", label)

        log.info("  Fetching unreported opinions...")
        unreported = get_unreported_opinions(year, month)

        if year not in years_fetched:
            log.info("  Fetching reported opinions...")
            reported = get_reported_opinions(year)
            years_fetched.add(year)
        else:
            log.info(
                "  Reported opinions for %s already fetched.", year
            )
            reported = []

        unreported_tagged = []
        for op in unreported:
            tagged = dict(op)
            tagged["source"] = (
                "Unreported -- Appellate Court of Maryland"
            )
            unreported_tagged.append(tagged)

        reported_tagged = []
        for op in reported:
            tagged = dict(op)
            tagged["source"] = (
                "Reported -- "
                "Appellate Court / Supreme Court of Maryland"
            )
            reported_tagged.append(tagged)

        queue = unreported_tagged + reported_tagged

        seen_this_run = set()
        deduped = []
        for op in queue:
            if op["url"] not in seen_this_run:
                seen_this_run.add(op["url"])
                deduped.append(op)
        queue = deduped

        log.info("  Opinions to process: %d", len(queue))

        for opinion in queue:
            url = opinion["url"]

            if url in processed:
                log.info("  [SKIP]  %s", opinion["name"])
                continue

            log.info("  [CHECK] %s", opinion["name"])
            log.info("          %s", url)

            text = extract_pdf_text(url)

            if not text:
                log.warning("          No text extracted.")
                processed.add(url)
                continue

            kw_hits = find_keywords(text)

            if kw_hits:
                found = [kw["keyword"] for kw in kw_hits]
                log.info("  MATCH -- Keywords: %s", found)
                matched = dict(opinion)
                matched["keywords_found"] = kw_hits
                all_matches.append(matched)
            else:
                log.info("          No keyword matches.")

            processed.add(url)
            time.sleep(DELAY_BETWEEN_PDFS)

    save_processed(processed)

    log.info("\n" + "=" * 60)
    log.info(
        "Run complete. %d matching opinion(s) found.",
        len(all_matches)
    )
    log.info("=" * 60)

    if all_matches:
        report = build_html_report(all_matches)
        with open(RESULTS_FILE, "w", encoding="utf-8") as f:
            f.write(report)
        log.info("HTML report saved to %s", RESULTS_FILE)

        # Open browser first so report loads while dialog is open
        if AUTO_OPEN_REPORT:
            open_report_in_browser()

        # Persistent dialog -- stays until user clicks OK
        if SHOW_WINDOWS_NOTIFICATION:
            show_persistent_notification(
                "MD Court Alert -- "
                + str(len(all_matches)) + " Opinion(s) Found",
                str(len(all_matches))
                + " new appellate opinion(s) matched "
                + "your keywords.\n\n"
                + "The full report has opened in your browser.\n\n"
                + "File: " + os.path.abspath(RESULTS_FILE)
                + "\n\nClick OK to dismiss."
            )

    else:
        log.info("No new keyword matches found this run.")

        # Persistent dialog even when nothing found --
        # confirms the tool ran successfully
        if SHOW_WINDOWS_NOTIFICATION:
            show_persistent_notification(
                "MD Court Alert -- Zero Opinions Found",
                "The MD Court Opinion Alert tool ran successfully.\n\n"
                + "No new appellate opinions matched your keywords "
                + "this run.\n\n"
                + "Checked: "
                + datetime.datetime.now().strftime(
                    "%B %d, %Y at %I:%M %p"
                )
                + "\n\nClick OK to dismiss."
            )


if __name__ == "__main__":
    main()