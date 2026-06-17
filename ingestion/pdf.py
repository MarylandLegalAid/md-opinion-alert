"""PDF text extraction (lifted from the PoC's ``extract_pdf_text``).

PDFs are processed in memory and never persisted; only the extracted text is
stored.
"""

import io
import logging

import pdfplumber

logger = logging.getLogger(__name__)


def extract_pdf_text(raw):
    """Return the full extracted text of a PDF given its raw bytes."""
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        pages = []
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                pages.append(t)
            # Release the page's cached layout objects; otherwise memory grows
            # with document length and large opinions can OOM a 512MB instance.
            page.close()
        return "\n".join(pages)
