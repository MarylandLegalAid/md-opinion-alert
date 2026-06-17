import datetime
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from alerts.digests import send_digest, send_digests
from alerts.email_backends import ACSEmailBackend, GraphEmailBackend
from alerts.models import NotificationLog
from ingestion.models import Opinion, OpinionText
from keywords.models import Keyword
from matching.engine import match_keyword_against_corpus

User = get_user_model()


def make_matched_opinion(user, slug="case", text="The rent was due.", kw=None):
    opinion = Opinion.objects.create(
        source_url=f"https://www.mdcourts.gov/data/opinions/{slug}.pdf",
        case_name=f"{slug} v. State",
        docket=slug,
        opinion_type=Opinion.OpinionType.REPORTED,
        filed_date=datetime.date(2026, 6, 1),
    )
    OpinionText.objects.create(opinion=opinion, full_text=text)
    kw = kw or Keyword.objects.filter(owner=user).first() or Keyword.objects.create(
        text="rent", owner=user
    )
    match_keyword_against_corpus(kw)
    return opinion


class DashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="jane", password="x")
        self.client.force_login(self.user)

    def test_empty_state_onboarding(self):
        response = self.client.get("/", secure=True)
        self.assertContains(response, "Choose your keywords")

    def test_dashboard_shows_match_cards(self):
        make_matched_opinion(self.user)
        response = self.client.get("/", secure=True)
        self.assertContains(response, "case v. State")
        self.assertContains(response, "rent ×1")
        self.assertContains(response, "Show keyword context")

    def test_keyword_filter(self):
        make_matched_opinion(self.user, slug="rent-case")
        other_kw = Keyword.objects.create(text="zoning", owner=self.user)
        make_matched_opinion(
            self.user, slug="zoning-case", text="A zoning appeal.", kw=other_kw
        )
        response = self.client.get(f"/?keyword={other_kw.pk}", secure=True)
        self.assertContains(response, "zoning-case v. State")
        self.assertNotContains(response, "rent-case v. State")

    def test_new_badge_for_opinions_since_last_visit(self):
        self.client.get("/", secure=True)  # establishes last visit
        make_matched_opinion(self.user)
        response = self.client.get("/", secure=True)
        self.assertContains(response, "NEW")
        # second view: no longer new
        response = self.client.get("/", secure=True)
        self.assertNotContains(response, "NEW")


class AboutTests(TestCase):
    def test_about_page_renders(self):
        user = User.objects.create_user(username="jane", password="x")
        self.client.force_login(user)
        response = self.client.get("/about/", secure=True)
        self.assertContains(response, "About MD Opinion Alert")
        self.assertContains(response, "Zafar Shah")

    def test_about_requires_login(self):
        response = self.client.get("/about/", secure=True)
        self.assertEqual(response.status_code, 302)


class PreferencesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="jane", password="x")
        self.client.force_login(self.user)

    def test_update_cadence(self):
        response = self.client.post(
            "/preferences/", {"digest_cadence": "daily"}, secure=True, follow=True
        )
        self.assertContains(response, "Preferences saved")
        self.user.refresh_from_db()
        self.assertEqual(self.user.digest_cadence, "daily")

    def test_invalid_cadence_rejected(self):
        self.client.post("/preferences/", {"digest_cadence": "hourly"}, secure=True)
        self.user.refresh_from_db()
        self.assertEqual(self.user.digest_cadence, "weekly")


@override_settings(SITE_URL="https://app.example")
class DigestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="jane", email="jane@org.example", digest_cadence="weekly"
        )

    def test_forward_only_window(self):
        make_matched_opinion(self.user, slug="old")
        # Pretend the last digest already covered everything stored so far
        self.user.last_digest_at = timezone.now()
        self.user.save()

        self.assertIsNone(send_digest(self.user, "weekly"))
        self.assertEqual(len(mail.outbox), 0)

        make_matched_opinion(self.user, slug="fresh", text="rent again")
        log = send_digest(self.user, "weekly")
        self.assertEqual(log.status, NotificationLog.Status.SENT)
        self.assertEqual(log.match_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("fresh v. State", mail.outbox[0].body)
        self.assertNotIn("old v. State", mail.outbox[0].body)

    def test_first_digest_looks_back_one_cadence_period(self):
        # Joined long ago, so the cadence window is the binding cutoff
        User.objects.filter(pk=self.user.pk).update(
            date_joined=timezone.now() - datetime.timedelta(days=365)
        )
        self.user.refresh_from_db()
        opinion = make_matched_opinion(self.user, slug="recent")
        Opinion.objects.filter(pk=opinion.pk).update(
            first_seen_at=timezone.now() - datetime.timedelta(days=30)
        )
        # 30 days old > 7-day weekly window → skipped
        self.assertIsNone(send_digest(self.user, "weekly"))

        fresh = make_matched_opinion(self.user, slug="thisweek", text="rent now")
        Opinion.objects.filter(pk=fresh.pk).update(
            first_seen_at=timezone.now() - datetime.timedelta(days=2)
        )
        log = send_digest(self.user, "weekly")
        self.assertEqual(log.match_count, 1)

    def test_first_digest_excludes_opinions_ingested_before_signup(self):
        # Ingested before signup but within the weekly window → excluded
        before = make_matched_opinion(self.user, slug="presignup")
        Opinion.objects.filter(pk=before.pk).update(
            first_seen_at=self.user.date_joined - datetime.timedelta(days=2)
        )
        self.assertIsNone(send_digest(self.user, "weekly"))

        make_matched_opinion(self.user, slug="postsignup", text="rent later")
        log = send_digest(self.user, "weekly")
        self.assertEqual(log.match_count, 1)
        self.assertIn("postsignup v. State", mail.outbox[0].body)
        self.assertNotIn("presignup v. State", mail.outbox[0].body)

    def test_last_digest_at_updated_on_send(self):
        make_matched_opinion(self.user)
        send_digest(self.user, "weekly")
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_digest_at)

    def test_send_digests_selects_by_cadence(self):
        daily_user = User.objects.create_user(
            username="dan", email="dan@org.example", digest_cadence="daily"
        )
        off_user = User.objects.create_user(
            username="omar", email="omar@org.example", digest_cadence="off"
        )
        make_matched_opinion(self.user)
        kw = Keyword.objects.create(text="rent", owner=daily_user)
        match_keyword_against_corpus(kw)
        kw2 = Keyword.objects.create(text="rent", owner=off_user)
        match_keyword_against_corpus(kw2)

        sent, skipped, failed = send_digests("weekly")
        self.assertEqual((sent, skipped, failed), (1, 0, 0))
        self.assertEqual(mail.outbox[0].to, ["jane@org.example"])

        sent, _, _ = send_digests("daily")
        self.assertEqual(sent, 1)
        self.assertEqual(mail.outbox[1].to, ["dan@org.example"])
        # "off" users never selected
        self.assertEqual(NotificationLog.objects.filter(user=off_user).count(), 0)

    def test_failure_logged(self):
        make_matched_opinion(self.user)
        with patch(
            "alerts.digests.EmailMultiAlternatives.send",
            side_effect=RuntimeError("smtp down"),
        ):
            log = send_digest(self.user, "weekly")
        self.assertEqual(log.status, NotificationLog.Status.FAILED)
        self.assertIn("smtp down", log.error)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.last_digest_at)

    def test_commands_run(self):
        make_matched_opinion(self.user)
        call_command("send_weekly_digests")
        self.assertEqual(len(mail.outbox), 1)
        call_command("send_daily_digests")
        self.assertEqual(len(mail.outbox), 1)  # jane is weekly; nothing added

    def test_unsubscribe_link_present(self):
        make_matched_opinion(self.user)
        send_digest(self.user, "weekly")
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn("https://app.example/preferences/", html)
        self.assertIn("https://app.example/preferences/", mail.outbox[0].body)


@override_settings(
    ACS_ENDPOINT="https://acs.example", ACS_SENDER_ADDRESS="alerts@org.example"
)
class ACSBackendTests(TestCase):
    def test_send_builds_acs_payload(self):
        backend = ACSEmailBackend()
        fake_client = MagicMock()
        fake_client.begin_send.return_value.result.return_value = {"id": "msg-1"}
        backend._client = fake_client

        from django.core.mail import EmailMultiAlternatives

        message = EmailMultiAlternatives(
            subject="Test", body="plain", to=["jane@org.example"]
        )
        message.attach_alternative("<p>html</p>", "text/html")
        self.assertEqual(backend.send_messages([message]), 1)

        payload = fake_client.begin_send.call_args[0][0]
        self.assertEqual(payload["senderAddress"], "alerts@org.example")
        self.assertEqual(payload["recipients"]["to"], [{"address": "jane@org.example"}])
        self.assertEqual(payload["content"]["plainText"], "plain")
        self.assertEqual(payload["content"]["html"], "<p>html</p>")
        self.assertEqual(message.provider_message_id, "msg-1")


@override_settings(
    AZURE_TENANT_ID="t", AZURE_CLIENT_ID="c", AZURE_CLIENT_SECRET="s",
    GRAPH_SENDER_ADDRESS="shared@org.example",
)
class GraphBackendTests(TestCase):
    def test_send_posts_to_graph(self):
        backend = GraphEmailBackend()
        with (
            patch.object(GraphEmailBackend, "_token", return_value="tok"),
            patch("alerts.email_backends.requests.post") as post,
        ):
            post.return_value.raise_for_status = MagicMock()
            from django.core.mail import EmailMessage

            message = EmailMessage(subject="T", body="b", to=["x@org.example"])
            self.assertEqual(backend.send_messages([message]), 1)

        url = post.call_args[0][0]
        self.assertIn("shared@org.example", url)
        body = post.call_args[1]["json"]
        self.assertEqual(body["message"]["subject"], "T")
        self.assertTrue(body["saveToSentItems"])
