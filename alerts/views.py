import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.utils import timezone

from ingestion.models import Opinion
from keywords.models import Keyword
from matching.models import Match

from .matches import group_matches_by_opinion

PAGE_SIZE = 25


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@login_required
def dashboard(request):
    """Per-user dashboard: retroactive matches over the whole corpus."""
    user = request.user
    match_qs = Match.objects.filter(user=user)

    keyword_id = request.GET.get("keyword") or None
    opinion_type = request.GET.get("type") or None
    court = request.GET.get("court") or None
    date_from = _parse_date(request.GET.get("from"))
    date_to = _parse_date(request.GET.get("to"))

    if keyword_id:
        match_qs = match_qs.filter(keyword_id=keyword_id)

    opinion_qs = (
        Opinion.objects.filter(matches__in=match_qs)
        .distinct()
        .order_by("-filed_date", "-first_seen_at")
    )
    if opinion_type in dict(Opinion.OpinionType.choices):
        opinion_qs = opinion_qs.filter(opinion_type=opinion_type)
    if court:
        opinion_qs = opinion_qs.filter(court=court)
    if date_from:
        opinion_qs = opinion_qs.filter(filed_date__gte=date_from)
    if date_to:
        opinion_qs = opinion_qs.filter(filed_date__lte=date_to)

    page = Paginator(opinion_qs, PAGE_SIZE).get_page(request.GET.get("page"))
    cards = group_matches_by_opinion(
        match_qs.filter(opinion__in=page.object_list)
    )

    previous_visit = user.last_dashboard_visit_at
    for card in cards:
        card["is_new"] = bool(
            previous_visit and card["opinion"].first_seen_at > previous_visit
        )
    user.last_dashboard_visit_at = timezone.now()
    user.save(update_fields=["last_dashboard_visit_at"])

    user_keywords = Keyword.objects.filter(owner=user) | Keyword.objects.filter(
        list__subscriptions__user=user
    )
    courts = (
        Opinion.objects.filter(matches__user=user)
        .exclude(court="")
        .values_list("court", flat=True)
        .distinct()
        .order_by("court")
    )

    has_keywords = user_keywords.exists()
    return render(
        request,
        "alerts/dashboard.html",
        {
            "cards": cards,
            "page": page,
            "keywords": user_keywords.order_by("text"),
            "courts": courts,
            "opinion_types": Opinion.OpinionType.choices,
            "has_keywords": has_keywords,
            "filters": {
                "keyword": keyword_id or "",
                "type": opinion_type or "",
                "court": court or "",
                "from": request.GET.get("from", ""),
                "to": request.GET.get("to", ""),
            },
        },
    )


@login_required
def about(request):
    return render(request, "alerts/about.html")


@login_required
def preferences(request):
    user = request.user
    if request.method == "POST":
        cadence = request.POST.get("digest_cadence")
        if cadence in dict(user.DigestCadence.choices):
            user.digest_cadence = cadence
            user.save(update_fields=["digest_cadence"])
            messages.success(request, "Preferences saved.")
            return redirect("preferences")
        messages.error(request, "Invalid digest cadence.")
    return render(
        request,
        "alerts/preferences.html",
        {"cadence_choices": user.DigestCadence.choices},
    )
