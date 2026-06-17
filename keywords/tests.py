from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from ingestion.models import Opinion, OpinionText
from keywords.models import Keyword, KeywordList, Subscription
from matching.models import Match

User = get_user_model()

SEED_LIST_NAME = "Landlord-Tenant & Consumer Core"


class ModelInvariantTests(TestCase):
    def test_seeded_list_present(self):
        kw_list = KeywordList.objects.get(name=SEED_LIST_NAME)
        self.assertEqual(kw_list.keywords.count(), 28)
        self.assertTrue(kw_list.is_shared)

    def test_keyword_must_have_list_xor_owner(self):
        user = User.objects.create_user(username="u")
        kw_list = KeywordList.objects.create(name="L")
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Keyword.objects.create(text="orphan")
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Keyword.objects.create(text="both", list=kw_list, owner=user)

    def test_duplicate_subscription_rejected(self):
        user = User.objects.create_user(username="u")
        kw_list = KeywordList.objects.create(name="L")
        Subscription.objects.create(user=user, keyword_list=kw_list)
        with self.assertRaises(IntegrityError):
            Subscription.objects.create(user=user, keyword_list=kw_list)


class KeywordUITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="jane", password="x")
        self.client.force_login(self.user)
        self.seed_list = KeywordList.objects.get(name=SEED_LIST_NAME)
        opinion = Opinion.objects.create(
            source_url="https://www.mdcourts.gov/data/opinions/t.pdf",
            case_name="Tenant v. Landlord",
            opinion_type=Opinion.OpinionType.REPORTED,
        )
        OpinionText.objects.create(
            opinion=opinion, full_text="The tenant sought rent escrow relief."
        )

    def test_manage_page_renders(self):
        response = self.client.get("/keywords/", secure=True)
        self.assertContains(response, "Landlord-Tenant &amp; Consumer Core")
        self.assertContains(response, "No personal keywords yet")

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get("/keywords/", secure=True)
        self.assertEqual(response.status_code, 302)

    def test_subscribe_backfills_dashboard_matches(self):
        response = self.client.post(
            f"/keywords/lists/{self.seed_list.pk}/subscribe/", secure=True
        )
        self.assertContains(response, "Unsubscribe")
        # "tenant", "rent escrow" and "rent" from the seed list hit the corpus
        self.assertEqual(Match.objects.filter(user=self.user).count(), 3)

    def test_unsubscribe_removes_matches(self):
        self.client.post(f"/keywords/lists/{self.seed_list.pk}/subscribe/", secure=True)
        response = self.client.post(
            f"/keywords/lists/{self.seed_list.pk}/unsubscribe/", secure=True
        )
        self.assertContains(response, "Subscribe")
        self.assertEqual(Match.objects.count(), 0)

    def test_add_personal_keyword_matches_corpus(self):
        response = self.client.post(
            "/keywords/personal/add/", {"text": "escrow"}, secure=True
        )
        self.assertContains(response, "escrow")
        match = Match.objects.get(user=self.user)
        self.assertEqual(match.keyword.text, "escrow")

    def test_add_duplicate_personal_keyword_rejected(self):
        Keyword.objects.create(text="escrow", owner=self.user)
        response = self.client.post(
            "/keywords/personal/add/", {"text": "Escrow"}, secure=True
        )
        self.assertContains(response, "already have that keyword")
        self.assertEqual(self.user.personal_keywords.count(), 1)

    def test_delete_personal_keyword_cascades_matches(self):
        self.client.post("/keywords/personal/add/", {"text": "escrow"}, secure=True)
        kw = self.user.personal_keywords.get()
        self.client.post(f"/keywords/personal/{kw.pk}/delete/", secure=True)
        self.assertEqual(self.user.personal_keywords.count(), 0)
        self.assertEqual(Match.objects.count(), 0)

    def test_cannot_delete_someone_elses_keyword(self):
        other = User.objects.create_user(username="bob")
        kw = Keyword.objects.create(text="theirs", owner=other)
        response = self.client.post(
            f"/keywords/personal/{kw.pk}/delete/", secure=True
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Keyword.objects.filter(pk=kw.pk).exists())
