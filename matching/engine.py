"""Keyword matching over stored opinion text.

Two-stage matching that preserves the PoC's semantics exactly:

1. **SQL narrow**: Postgres regex with ``\\y`` word boundaries (the Postgres
   spelling of ``\\b``), optionally pre-filtered by full-text search on the
   GIN-indexed tsvector. FTS stems (``rent`` → ``renting``) so it over-matches;
   it is only ever a cheap candidate filter, never the verdict.
2. **Python confirm**: the PoC's exact ``\\b<kw>\\b`` / ``re.IGNORECASE``
   pattern recomputes the hit count and builds the ±120-char snippets, so
   ``rent`` ≠ ``parent``/``renter`` exactly as the desktop tool behaved.
"""

import logging
import re

from django.contrib.postgres.search import SearchQuery, SearchVector

from ingestion.models import OpinionText
from keywords.models import Keyword

from .models import Match

logger = logging.getLogger(__name__)

SNIPPET_RADIUS = 120
MAX_SNIPPETS = 3


def _python_pattern(keyword):
    escaped = re.escape(keyword.text)
    if keyword.match_whole_word:
        escaped = r"\b" + escaped + r"\b"
    return re.compile(escaped, re.IGNORECASE if keyword.case_insensitive else 0)


def _sql_filter(queryset, keyword):
    escaped = re.escape(keyword.text)
    if keyword.match_whole_word:
        pattern = r"\y" + escaped + r"\y"
        # FTS pre-filter only applies to whole-word terms: it tokenizes on word
        # boundaries, so substring matching would be wrongly narrowed by it.
        queryset = queryset.annotate(
            fts=SearchVector("full_text", config="english")
        ).filter(fts=SearchQuery(keyword.text, config="english", search_type="plain"))
    else:
        pattern = escaped
    lookup = "full_text__iregex" if keyword.case_insensitive else "full_text__regex"
    return queryset.filter(**{lookup: pattern})


def find_hits(text, keyword):
    """PoC ``find_keywords`` for a single keyword: (count, snippets) or None."""
    hits = list(_python_pattern(keyword).finditer(text))
    if not hits:
        return None
    snippets = []
    for hit in hits[:MAX_SNIPPETS]:
        start = max(0, hit.start() - SNIPPET_RADIUS)
        end = min(len(text), hit.end() + SNIPPET_RADIUS)
        snippet = text[start:end].replace("\n", " ").strip()
        snippets.append("..." + snippet + "...")
    return len(hits), snippets


def compute_keyword_hits(keyword, opinion_qs=None):
    """Yield ``(opinion_id, count, snippets)`` for a keyword over opinions."""
    texts = OpinionText.objects.all()
    if opinion_qs is not None:
        texts = texts.filter(opinion__in=opinion_qs)
    texts = _sql_filter(texts, keyword)

    for opinion_id, full_text in texts.values_list("opinion_id", "full_text").iterator():
        result = find_hits(full_text, keyword)
        if result:
            yield opinion_id, result[0], result[1]


def _fan_out(keyword, hits, users):
    """Create Match rows for every (hit, user) pair; returns rows created."""
    rows = [
        Match(opinion_id=opinion_id, user=user, keyword=keyword,
              count=count, snippets=snippets)
        for opinion_id, count, snippets in hits
        for user in users
    ]
    created = Match.objects.bulk_create(rows, ignore_conflicts=True)
    return len(created)


def match_opinions(opinion_qs):
    """Match every active keyword against the given (new) opinions.

    Called from the ingestion pipeline after new opinions are stored.
    Returns the number of Match rows created.
    """
    total = 0
    for keyword in Keyword.objects.all():
        users = list(keyword.users())
        if not users:
            continue
        hits = list(compute_keyword_hits(keyword, opinion_qs))
        if hits:
            total += _fan_out(keyword, hits, users)
    if total:
        logger.info("Matching created %d match rows", total)
    return total


def match_keyword_against_corpus(keyword):
    """Corpus-wide matching for a newly added keyword (dashboard
    retroactivity). Returns the number of Match rows created."""
    users = list(keyword.users())
    if not users:
        return 0
    return _fan_out(keyword, compute_keyword_hits(keyword), users)


def match_user_against_list(user, keyword_list):
    """Backfill matches for a user who just subscribed to a list."""
    total = 0
    for keyword in keyword_list.keywords.all():
        total += _fan_out(keyword, compute_keyword_hits(keyword), [user])
    return total


def remove_user_list_matches(user, keyword_list):
    """Drop a user's matches from a list they unsubscribed from."""
    deleted, _ = Match.objects.filter(user=user, keyword__list=keyword_list).delete()
    return deleted

