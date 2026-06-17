======================================================================
MARYLAND APPELLATE COURT OPINION ALERT TOOL
IT Documentation  --  Version 1.0  --  June 2026
======================================================================

CONTENTS
--------
 1. Overview
 2. System Requirements
 3. Directory Structure and Files
 4. Python Package Dependencies
 5. Network and Firewall Requirements
 6. Scraping Architecture
 7. Configuration System (config.json)
 8. Keyword Matching Logic
 9. Notification System
10. Windows Task Scheduler Integration
11. Data Storage and Privacy
12. Security Considerations
13. Deployment Instructions (IT)
14. End User Instructions
15. Troubleshooting
16. Uninstall Instructions

======================================================================
1. OVERVIEW
======================================================================
The Maryland Appellate Court Opinion Alert Tool is a Python-based
automation utility that periodically scrapes publicly available
appellate court opinions from the Maryland Courts website
(mdcourts.gov), extracts text from the PDF opinions, searches for
user-defined keywords, and notifies the user via a Windows dialog
and HTML report.

The tool operates entirely locally on the user's PC. It does not use
cloud services, external APIs, or collect any user data. All data is
stored in a local directory on the user's PC.

Target users: Attorneys and legal professionals monitoring Maryland
appellate court decisions for relevant topics such as landlord-tenant
law, real property, and consumer protection.

======================================================================
2. SYSTEM REQUIREMENTS
======================================================================
- Windows 10 or Windows 11
- Python 3.7 or later  (https://python.org/downloads)
  Tested with Python 3.14
- Internet access to www.mdcourts.gov (HTTPS, port 443)
- Approximately 50 MB disk space for tool and accumulated data files
- Microsoft Outlook is NOT required
  (notifications use Python's built-in tkinter dialog)

======================================================================
3. DIRECTORY STRUCTURE AND FILES
======================================================================
Default install directory:  C:\md_opinion_alert\

Files present after setup:
  md_opinion_alert.py         Main scraper and alert script
  md_court_setup.py           Setup and configuration GUI (source)
  config.json                 User configuration written by setup GUI
  run_opinion_alert.bat       Launcher called by Task Scheduler
  README.txt                  This file

Files created during operation:
  processed_opinions.json     Tracks already-processed opinion URLs
                              Prevents duplicate alerts across runs
  latest_results.html         Most recent keyword match report
                              Opens in browser automatically on match
  opinion_scraper.log         Full run history, errors, match log
                              Grows by approx. 1 KB per weekly run

======================================================================
4. PYTHON PACKAGE DEPENDENCIES
======================================================================
External packages (installed by setup tool or manually via pip):
  requests        >= 2.31    HTTP requests to mdcourts.gov
  beautifulsoup4  >= 4.12    HTML page parsing
  pdfplumber      >= 0.10    PDF text extraction
  lxml            >= 5.0     HTML/XML parser backend for bs4
  plyer           >= 2.1     Fallback desktop notification

Standard library modules used (no installation required):
  tkinter, json, os, sys, re, time, datetime, logging,
  webbrowser, io, urllib, threading, shutil, subprocess

To install all external packages manually:
  python -m pip install requests beautifulsoup4 pdfplumber lxml plyer

======================================================================
5. NETWORK AND FIREWALL REQUIREMENTS
======================================================================
Outbound connections required (HTTPS, port 443):
  Host:     www.mdcourts.gov
  Purpose:  Fetching opinion listing pages and downloading PDF files

No inbound connections are required.
No user credentials are transmitted to any server.
All accessed content is publicly available without authentication.

URLs accessed during a typical run:
  https://www.mdcourts.gov/cgi-bin/indexlist.pl
      Reported opinions index (CGI query with year parameter)

  https://www.mdcourts.gov/appellate/unreportedopinions/list/YYYYMM
      Unreported opinions monthly listing (e.g. /list/202606)

  https://www.mdcourts.gov/data/opinions/{cosa|coa}/YYYY/*.pdf
      Reported opinion PDF files

  https://www.mdcourts.gov/sites/default/files/unreported-opinions/*.pdf
      Unreported opinion PDF files

No other external connections are made.
pip package downloads occur only when the setup tool is run.

======================================================================
6. SCRAPING ARCHITECTURE
======================================================================

A. REPORTED OPINIONS
   Source:   https://www.mdcourts.gov/cgi-bin/indexlist.pl
   Method:   HTTP GET with query parameters:
               court=both, year=YYYY, order=bydate, submit=Submit
   Response: HTML page with a stacked-column table layout.
             All PDF links appear in one <td> cell, all case names
             in a sibling <td>, all dates in another, separated by
             <br> tags within each cell.
   PDFs:     Hosted at /data/opinions/{cosa|coa}/YYYY/*.pdf
   Parsing:  extract_reported_opinions_from_soup() splits each
             stacked cell by <br> tags and matches case name to
             PDF link by position (index) within each column.

B. UNREPORTED OPINIONS
   Source:   https://www.mdcourts.gov/appellate/unreportedopinions
             /list/YYYYMM
   Method:   HTTP GET (direct URL, no query parameters)
   Response: Standard HTML table, one row per opinion.
   Columns:  0=Court | 1=Filed | 2=Docket(PDF link) | 3=Term
             4=Judge | 5=Appellant | 6=Appellee
   PDFs:     Hosted at /sites/default/files/unreported-opinions/*.pdf
   Parsing:  extract_unreported_opinions_from_soup() reads columns
             by fixed index from each <tr>.

C. PDF TEXT EXTRACTION
   Library:  pdfplumber
   Method:   PDF bytes downloaded to memory (not saved to disk),
             text extracted page by page using pdfplumber.
   Note:     Maryland court PDFs are text-based (not scanned images).
             No OCR is performed. Extraction is reliable.

D. KEYWORD MATCHING
   Module:   Python re (regex)
   Pattern:  \b<keyword>\b  (word boundary anchors)
   Effect:   "rent" matches the word "rent" but NOT "parent",
             "transparent", "currently", or "renter".
             Multi-word phrases (e.g. "warranty of habitability")
             are matched at phrase boundaries.
   Case:     All matching is case-insensitive (re.IGNORECASE).

E. DEDUPLICATION
   Each processed PDF URL is stored in processed_opinions.json.
   On each run, already-processed URLs are skipped instantly.
   This means each opinion is keyword-checked only once across
   all runs, regardless of how many months the tool looks back.
   Deleting processed_opinions.json causes all opinions to be
   re-checked on the next run.

F. RATE LIMITING
   A 2-second delay is applied between individual PDF downloads
   to avoid excessive load on the court's server.

G. SCOPE PER RUN
   Controlled by MONTHS_TO_CHECK in config.json (default: 1).
   Each run checks:
     - Unreported opinions: current month only
     - Reported opinions:   all opinions in the current year
   Reported opinions are fetched once per year even when
   MONTHS_TO_CHECK > 1 (deduplication handles the rest).

======================================================================
7. CONFIGURATION SYSTEM (config.json)
======================================================================
All user settings are stored in config.json in the install directory.
This file is written by the setup GUI (MDCourtAlertSetup.exe or
md_court_setup.py) and read by md_opinion_alert.py at startup.

If config.json is absent, md_opinion_alert.py falls back to the
hardcoded defaults in its Section 1.

config.json structure and fields:
{
    "keywords": [           List of search terms. Each entry matched
        "tenant",           independently as a whole word or phrase.
        "landlord",         Case-insensitive. Add/remove freely.
        ...
    ],
    "months_to_check": 1,   Integer 1-12. How far back to look for
                            new opinions. 1 is standard for weekly runs.
                            Use 2-3 after a gap in runs.
    "show_notification": true,
                            Boolean. Show popup dialog after every run
                            (including runs with no matches).
    "auto_open_report": true,
                            Boolean. Auto-open latest_results.html in
                            browser when matches are found.
    "schedule_frequency": "weekly",
                            "daily" or "weekly". For reference only;
                            actual schedule is in Task Scheduler.
    "schedule_day": "Monday",
                            Day of week for weekly schedule.
    "schedule_time": "08:00"
                            24-hour time for scheduled run.
    "install_folder": "C:\\md_opinion_alert"
                            Stored by setup tool for reference.
}

======================================================================
8. KEYWORD MATCHING LOGIC
======================================================================
Keywords support:
  Single words:   "tenant", "eviction", "rent"
  Phrases:        "warranty of habitability", "Real Property"
  Case:           Always matched case-insensitively

Word boundary examples:
  "rent"    matches "rent", "Rent", "RENT"
            does NOT match "parent", "transparent", "currently"
  "lease"   matches "lease", "Lease"
            does NOT match "release", "subleased"
  "possession" matches "possession"
            does NOT match "repossession" (separate keyword if needed)

To also catch "leasehold", add it as a separate keyword entry.
Each line in the keywords list is an independent search.

Keyword results in the HTML report show:
  - How many times the keyword appears (count)
  - Up to 3 context snippets showing 120 characters of surrounding
    text on each side of the match, with the keyword highlighted

======================================================================
9. NOTIFICATION SYSTEM
======================================================================
Notification method: Python tkinter messagebox (built-in library,
no installation required, no Outlook or Teams required).

Behavior:
  - A dialog box appears when the script completes
  - The dialog floats on top of all other windows
  - It remains visible until the user clicks OK
  - It fires for BOTH match and no-match outcomes
    (so the user always knows the tool ran successfully)

When matches are found:
  1. Browser opens automatically with latest_results.html
  2. Dialog appears: "MD Court Alert -- X Opinion(s) Found"
     Body shows match count, report file path, Click OK prompt

When no matches are found:
  Dialog appears: "MD Court Alert -- Zero Opinions Found"
  Body confirms the tool ran successfully with timestamp.

The HTML report (latest_results.html) contains for each match:
  - Case name and docket number (clickable link to PDF)
  - Court and opinion type (Reported / Unreported)
  - Filed date
  - Keyword tags showing keyword and occurrence count
  - Expandable "Show keyword context" section with up to 3
    text snippets per keyword, keyword highlighted in yellow

Email and Microsoft Teams notifications are disabled in this
deployment due to firm SMTP (Basic Auth disabled) and Power Platform
network restrictions. They can be re-enabled in Section 1 of
md_opinion_alert.py and in config.json if those restrictions change.

======================================================================
10. WINDOWS TASK SCHEDULER INTEGRATION
======================================================================
Task name:     MD Court Opinion Alert
Trigger:       Configurable via setup GUI
               Default: Weekly, Monday, 08:00 AM
Action:        Run run_opinion_alert.bat
Run context:   Logged-on user (no elevated privileges required)
Condition:     Runs only when the user is logged on

Task is created by the setup tool using schtasks.exe:
  schtasks /create
           /tn "MD Court Opinion Alert"
           /tr "C:\md_opinion_alert\run_opinion_alert.bat"
           /sc WEEKLY /d MON /st 08:00 /f

The /f flag silently overwrites any existing task with the same name,
allowing re-configuration without manual deletion.

run_opinion_alert.bat contents:
  @echo off
  cd /d C:\md_opinion_alert
  python md_opinion_alert.py

To view, modify, or delete the task:
  Windows Start -> Task Scheduler -> Task Scheduler Library
  Find: MD Court Opinion Alert

Run history and results:
  opinion_scraper.log in the install directory records every run
  with timestamp, opinions checked, matches found, and any errors.

======================================================================
11. DATA STORAGE AND PRIVACY
======================================================================
All data is stored locally in the install directory.
No data is transmitted to any external server other than mdcourts.gov.
No personal information is collected or stored.
Content accessed is publicly available Maryland court records.

File growth over time:
  processed_opinions.json   Grows ~1 URL per opinion checked.
                            Approximately 5-10 KB per month of use.
                            Can be deleted to force full recheck.
  opinion_scraper.log       Grows ~1-2 KB per weekly run.
                            Recommend archiving or clearing annually.
  latest_results.html       Overwritten each run (matches only).
                            Typically under 500 KB.

======================================================================
12. SECURITY CONSIDERATIONS
======================================================================
- Script runs as the logged-on user. No administrator privileges needed
  for operation (setup tool does need to write to install directory).
- No passwords or credentials stored anywhere.
- No inbound network connections.
- All external traffic is HTTPS to a .gov website.
- PDF content is processed in memory; PDF files are not saved to disk.
- No macros, no executable content from downloaded files.
- Task Scheduler task runs with standard user privileges.

Antivirus note:
  PyInstaller-packaged executables (.exe built from Python) are
  sometimes flagged as suspicious by antivirus software (false
  positive due to PyInstaller packaging format). The full source
  code is available for review. If flagged, add an exception for
  MDCourtAlertSetup.exe in your endpoint security policy.

======================================================================
13. DEPLOYMENT INSTRUCTIONS (IT)
======================================================================
PREREQUISITES ON EACH USER PC:
  1. Install Python 3.7 or later
     https://python.org/downloads
     During install, check "Add Python to PATH"

  2. Python will be installed when MDCourtAlertSetup.exe is run
     (the setup tool runs pip install automatically)

BUILD THE SETUP EXECUTABLE (one-time, done by IT):
  1. On a machine with Python, install PyInstaller:
     python -m pip install pyinstaller

  2. Place both files in the same folder:
       md_court_setup.py
       md_opinion_alert.py

  3. Run:
     pyinstaller --onefile --windowed
                 --add-data "md_opinion_alert.py;."
                 --name "MDCourtAlertSetup"
                 md_court_setup.py

  4. The executable is created at:
       dist\MDCourtAlertSetup.exe

  5. Distribute MDCourtAlertSetup.exe to colleagues.
     This single file contains everything needed for setup.

NOTE: md_opinion_alert.py must be present at the same level as
md_court_setup.py when building the exe. The exe bundles it and
extracts it to the install directory during setup.

COLLEAGUE SETUP PROCESS (no IT involvement needed after exe delivery):
  1. User receives MDCourtAlertSetup.exe
  2. Double-click to open
  3. Review/edit keyword list
  4. Set schedule preferences
  5. Click Install / Save
  6. Tool is configured and scheduled automatically

======================================================================
14. END USER INSTRUCTIONS
======================================================================
INITIAL SETUP:
  1. Double-click MDCourtAlertSetup.exe
  2. The keywords list is pre-filled with common landlord-tenant,
     real property, and consumer protection terms
  3. Add, remove, or edit keywords -- one per line
     Phrases are supported (e.g. "warranty of habitability")
  4. Choose Daily or Weekly schedule and preferred day/time
  5. Click Install / Save
  6. A confirmation dialog will appear

CHANGING KEYWORDS OR SCHEDULE LATER:
  1. Double-click MDCourtAlertSetup.exe again
  2. Your previous settings will be pre-loaded
  3. Make your changes
  4. Click Install / Save

RESETTING TO DEFAULTS:
  1. Open MDCourtAlertSetup.exe
  2. Click Reset to Defaults
  3. Click Install / Save

REVIEWING RESULTS:
  - When matches are found, a popup appears and your browser opens
    the results report automatically
  - You can open C:\md_opinion_alert\latest_results.html manually
    at any time to review the last set of results
  - Each result shows the case name as a clickable PDF link,
    matched keywords, and highlighted text context

WHAT THE POPUPS MEAN:
  "MD Court Alert -- X Opinion(s) Found"
    New opinions were posted since the last run and matched your
    keywords. Review latest_results.html for details.

  "MD Court Alert -- Zero Opinions Found"
    The tool ran successfully. No new opinions matched your keywords
    since the last run. This is normal between court opinion days.

======================================================================
15. TROUBLESHOOTING
======================================================================
No popup appears on scheduled run day
  - Were you logged in when the task was scheduled to run?
    The task runs only while you are logged on.
  - Open Task Scheduler, find "MD Court Opinion Alert",
    check "Last Run Result":
      0x0      = Success
      0x1      = General error -- open opinion_scraper.log
      0x8007010B = Wrong working directory -- re-run setup tool
  - Right-click task -> Run to test immediately

Popup says "Zero Opinions Found" every week
  - This is normal on weeks when the court posts no new opinions
    or posts opinions that do not match your keywords.
  - Maryland courts typically post opinions Tuesdays and Fridays.
  - To confirm the tool is running correctly, open opinion_scraper.log
    and check that the last run timestamp is recent.

Tool finds fewer opinions than expected
  - Open opinion_scraper.log and look for lines saying
    "No text extracted" -- this indicates PDF download failures
    (usually a temporary network issue).
  - Delete processed_opinions.json and run again to retry those.

"ModuleNotFoundError" in opinion_scraper.log
  - Python packages need reinstalling.
  - Open Command Prompt: python -m pip install requests
    beautifulsoup4 pdfplumber lxml plyer

MDCourtAlertSetup.exe flagged by antivirus
  - False positive due to PyInstaller packaging. Add an exception
    for MDCourtAlertSetup.exe in your endpoint security policy.
    Source code is available for review on request.

Site layout changed -- tool finds 0 opinions unexpectedly
  - mdcourts.gov may have updated its HTML structure.
  - Set DIAGNOSTIC_MODE = True in md_opinion_alert.py Section 1,
    run the script, and review the output.
  - The scraping logic is in two functions:
      extract_reported_opinions_from_soup()
      extract_unreported_opinions_from_soup()
  - Contact the tool maintainer with the diagnostic output.

======================================================================
16. UNINSTALL INSTRUCTIONS
======================================================================

USING THE SETUP TOOL (recommended for non-technical users):
  1. Open MDCourtAlertSetup.exe
  2. Click Uninstall in the button bar
  3. Confirm removal of the scheduled task when prompted
  4. Choose whether to delete the install folder when prompted
     Select No if you want to keep your results or keyword list
  5. Click OK to close

The uninstall process removes:
  - The Windows Task Scheduler task "MD Court Opinion Alert"
  - The install folder and all its contents (if confirmed)

The uninstall process does NOT remove:
  - Python itself
  - Any Python packages installed (requests, pdfplumber, etc.)
    These are shared libraries and may be used by other tools.
    Remove manually via pip if needed:
    python -m pip uninstall requests beautifulsoup4 pdfplumber lxml plyer

MANUAL UNINSTALL (if setup tool is unavailable):
  Step 1 -- Remove the scheduled task:
    Open Task Scheduler
    Find "MD Court Opinion Alert" in the Task Scheduler Library
    Right-click -> Delete -> Yes

  Step 2 -- Delete the install folder:
    Open File Explorer
    Navigate to C:\md_opinion_alert\ (or your custom install path)
    Delete the folder

  Step 3 -- Remove Python packages (optional):
    Open Command Prompt or PowerShell
    python -m pip uninstall requests beautifulsoup4 pdfplumber lxml plyer

PRESERVING YOUR DATA BEFORE UNINSTALL:
  If you want to keep a record of your keyword match history:
    Copy latest_results.html to another location before uninstalling
    Copy opinion_scraper.log to another location before uninstalling

  If you want to re-install later with the same keywords:
    Copy config.json to another location before uninstalling
    After reinstalling, place config.json back in the install folder
    or open the setup tool and re-enter your keywords manually.

======================================================================
END OF DOCUMENTATION
======================================================================