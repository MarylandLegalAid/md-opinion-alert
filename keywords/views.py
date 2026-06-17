from django.contrib.auth.decorators import login_required
from django.db.models import Count, Exists, OuterRef
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from matching.engine import (
    match_keyword_against_corpus,
    match_user_against_list,
    remove_user_list_matches,
)

from .models import Keyword, KeywordList, Subscription


def _shared_lists(user):
    return (
        KeywordList.objects.filter(is_shared=True)
        .annotate(
            keyword_count=Count("keywords", distinct=True),
            subscribed=Exists(
                Subscription.objects.filter(user=user, keyword_list=OuterRef("pk"))
            ),
        )
        .prefetch_related("keywords")
    )


def _personal_keywords(user):
    return user.personal_keywords.all()


@login_required
def manage(request):
    return render(
        request,
        "keywords/manage.html",
        {
            "lists": _shared_lists(request.user),
            "personal_keywords": _personal_keywords(request.user),
        },
    )


def _list_card_response(request, list_id):
    kw_list = _shared_lists(request.user).get(pk=list_id)
    return render(request, "keywords/_list_card.html", {"kw_list": kw_list})


@login_required
@require_POST
def subscribe(request, list_id):
    kw_list = get_object_or_404(KeywordList, pk=list_id, is_shared=True)
    _, created = Subscription.objects.get_or_create(
        user=request.user, keyword_list=kw_list
    )
    if created:
        # Dashboard is retroactive: backfill matches over the
        # stored corpus right away.
        match_user_against_list(request.user, kw_list)
    return _list_card_response(request, list_id)


@login_required
@require_POST
def unsubscribe(request, list_id):
    kw_list = get_object_or_404(KeywordList, pk=list_id, is_shared=True)
    Subscription.objects.filter(user=request.user, keyword_list=kw_list).delete()
    remove_user_list_matches(request.user, kw_list)
    return _list_card_response(request, list_id)


def _personal_response(request, error=""):
    return render(
        request,
        "keywords/_personal.html",
        {"personal_keywords": _personal_keywords(request.user), "error": error},
    )


@login_required
@require_POST
def add_personal(request):
    text = request.POST.get("text", "").strip()
    error = ""
    if not text:
        error = "Enter a keyword or phrase."
    elif len(text) > 200:
        error = "Keywords are limited to 200 characters."
    elif request.user.personal_keywords.filter(text__iexact=text).exists():
        error = "You already have that keyword."
    else:
        keyword = Keyword.objects.create(text=text, owner=request.user)
        match_keyword_against_corpus(keyword)
    return _personal_response(request, error)


@login_required
@require_POST
def delete_personal(request, keyword_id):
    get_object_or_404(Keyword, pk=keyword_id, owner=request.user).delete()
    return _personal_response(request)
