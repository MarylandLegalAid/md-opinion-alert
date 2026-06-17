"""Digest assembly and sending.

Forward-only: a digest covers opinions *ingested* since the
user's last digest — adding a broad keyword never floods email with history.
A user's first digest looks back one cadence period, not the whole corpus,
and never before the user signed up.
"""

import datetime
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from matching.models import Match

from .matches import group_matches_by_opinion
from .models import NotificationLog

logger = logging.getLogger(__name__)

CADENCE_WINDOWS = {
    "daily": datetime.timedelta(days=1),
    "weekly": datetime.timedelta(days=7),
}


def gather_cards(user, since):
    matches = Match.objects.filter(user=user, opinion__first_seen_at__gt=since)
    return group_matches_by_opinion(matches)


def send_digest(user, cadence, now=None):
    """Send one user's digest. Returns the NotificationLog row, or None if
    there was nothing to send (empty digests are skipped)."""
    now = now or timezone.now()
    since = max(
        user.last_digest_at or (now - CADENCE_WINDOWS[cadence]), user.date_joined
    )
    cards = gather_cards(user, since)
    if not cards:
        return None

    context = {
        "user": user,
        "cards": cards,
        "cadence": cadence,
        "site_url": settings.SITE_URL,
    }
    subject = (
        f"MD Opinion Alert — {len(cards)} new matching "
        f"opinion{'s' if len(cards) != 1 else ''}"
    )
    text_body = render_to_string("alerts/email_digest.txt", context)
    html_body = render_to_string("alerts/email_digest.html", context)

    email = EmailMultiAlternatives(subject=subject, body=text_body, to=[user.email])
    email.attach_alternative(html_body, "text/html")

    log = NotificationLog(user=user, cadence=cadence, match_count=len(cards))
    try:
        email.send()
    except Exception as exc:
        logger.exception("Digest send failed for %s", user)
        log.status = NotificationLog.Status.FAILED
        log.error = f"{type(exc).__name__}: {exc}"
    else:
        log.status = NotificationLog.Status.SENT
        log.provider_message_id = getattr(email, "provider_message_id", "")
        user.last_digest_at = now
        user.save(update_fields=["last_digest_at"])
    log.save()
    return log


def send_digests(cadence):
    """Send digests to every active user on the given cadence."""
    users = (
        get_user_model()
        .objects.filter(is_active=True, digest_cadence=cadence)
        .exclude(email="")
    )
    sent = skipped = failed = 0
    for user in users:
        log = send_digest(user, cadence)
        if log is None:
            skipped += 1
        elif log.status == NotificationLog.Status.SENT:
            sent += 1
        else:
            failed += 1
    logger.info(
        "%s digests: %d sent, %d skipped (empty), %d failed",
        cadence, sent, skipped, failed,
    )
    return sent, skipped, failed
