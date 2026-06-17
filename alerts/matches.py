"""Shared match-grouping used by both the dashboard and the email digests:
one card per opinion, carrying its keyword tags (with counts) and snippets."""

from ingestion.models import Opinion


def group_matches_by_opinion(match_qs):
    """Collapse Match rows into per-opinion cards, newest opinions first."""
    cards = {}
    matches = match_qs.select_related("opinion", "keyword").order_by(
        "-opinion__filed_date", "-opinion__first_seen_at", "keyword__text"
    )
    for match in matches:
        card = cards.setdefault(
            match.opinion_id, {"opinion": match.opinion, "keywords": []}
        )
        card["keywords"].append(
            {
                "keyword": match.keyword,
                "count": match.count,
                "snippets": match.snippets,
            }
        )
    return list(cards.values())


def opinions_for_matches(match_qs):
    """Distinct opinions touched by the given matches, newest first."""
    return Opinion.objects.filter(matches__in=match_qs).distinct()
