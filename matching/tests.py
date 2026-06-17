from django.contrib.auth import get_user_model
from django.test import TestCase

from ingestion.models import Opinion, OpinionText
from keywords.models import Keyword, KeywordList, Subscription
from matching.engine import (
    match_keyword_against_corpus,
    match_opinions,
    match_user_against_list,
    remove_user_list_matches,
)
from matching.models import Match

User = get_user_model()


def make_opinion(url_slug, text):
    opinion = Opinion.objects.create(
        source_url=f"https://www.mdcourts.gov/data/opinions/{url_slug}.pdf",
        case_name=url_slug,
        opinion_type=Opinion.OpinionType.REPORTED,
    )
    OpinionText.objects.create(opinion=opinion, full_text=text)
    return opinion


class MatchingSemanticsTests(TestCase):
    """The PoC guarantees, now enforced in SQL + Python."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="jane")
        cls.kw = Keyword.objects.create(text="rent", owner=cls.user)

    def test_whole_word_match(self):
        op = make_opinion("rent-case", "The tenant failed to pay rent on time.")
        self.assertEqual(match_keyword_against_corpus(self.kw), 1)
        match = Match.objects.get()
        self.assertEqual(match.opinion, op)
        self.assertEqual(match.count, 1)
        self.assertIn("rent", match.snippets[0])

    def test_rent_does_not_match_parent_or_renter(self):
        make_opinion("parent-case", "The parent and the renter were transparent.")
        self.assertEqual(match_keyword_against_corpus(self.kw), 0)
        self.assertEqual(Match.objects.count(), 0)

    def test_case_insensitive_by_default(self):
        make_opinion("caps-case", "RENT was overdue.")
        self.assertEqual(match_keyword_against_corpus(self.kw), 1)

    def test_phrase_matching(self):
        kw = Keyword.objects.create(text="rent escrow", owner=self.user)
        make_opinion("escrow-case", "The court established a rent escrow account.")
        make_opinion("no-escrow", "Escrow was mentioned; rent was not nearby.")
        self.assertEqual(match_keyword_against_corpus(kw), 1)

    def test_regex_special_chars_escaped(self):
        # '.' must match literally, not as a regex wildcard
        kw = Keyword.objects.create(text="Md. Code", owner=self.user)
        make_opinion("cite-case", "Under Md. Code the rule applies.")
        make_opinion("trap-case", "Under MdX Code nothing applies.")
        self.assertEqual(match_keyword_against_corpus(kw), 1)
        self.assertEqual(Match.objects.get().opinion.case_name, "cite-case")

    def test_count_and_snippet_cap(self):
        make_opinion("many-rents", " ".join(["The rent is due."] * 7))
        match_keyword_against_corpus(self.kw)
        match = Match.objects.get()
        self.assertEqual(match.count, 7)
        self.assertEqual(len(match.snippets), 3)
        self.assertTrue(all(s.startswith("...") for s in match.snippets))

    def test_hyphenated_phrase(self):
        kw = Keyword.objects.create(text="landlord-tenant", owner=self.user)
        make_opinion("lt-case", "This landlord-tenant dispute arose in Baltimore.")
        self.assertEqual(match_keyword_against_corpus(kw), 1)


class FanOutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.list = KeywordList.objects.create(name="Test List")
        cls.kw = Keyword.objects.create(text="eviction", list=cls.list)
        cls.alice = User.objects.create_user(username="alice")
        cls.bob = User.objects.create_user(username="bob")
        cls.opinion = make_opinion("evict", "An eviction was ordered.")

    def test_list_keyword_matches_all_subscribers(self):
        Subscription.objects.create(user=self.alice, keyword_list=self.list)
        Subscription.objects.create(user=self.bob, keyword_list=self.list)
        created = match_opinions(Opinion.objects.all())
        self.assertEqual(created, 2)
        self.assertEqual(set(Match.objects.values_list("user__username", flat=True)),
                         {"alice", "bob"})

    def test_no_subscribers_no_matches(self):
        self.assertEqual(match_opinions(Opinion.objects.all()), 0)

    def test_subscribe_backfills_and_unsubscribe_cleans_up(self):
        Subscription.objects.create(user=self.alice, keyword_list=self.list)
        created = match_user_against_list(self.alice, self.list)
        self.assertEqual(created, 1)

        deleted = remove_user_list_matches(self.alice, self.list)
        self.assertEqual(deleted, 1)
        self.assertEqual(Match.objects.count(), 0)

    def test_match_is_idempotent(self):
        Subscription.objects.create(user=self.alice, keyword_list=self.list)
        match_user_against_list(self.alice, self.list)
        match_user_against_list(self.alice, self.list)
        self.assertEqual(Match.objects.count(), 1)

    def test_pipeline_hook_matches_only_new_opinions(self):
        Subscription.objects.create(user=self.alice, keyword_list=self.list)
        match_opinions(Opinion.objects.all())
        new = make_opinion("evict2", "Another eviction case entirely.")
        created = match_opinions(Opinion.objects.filter(pk=new.pk))
        self.assertEqual(created, 1)
        self.assertEqual(Match.objects.filter(opinion=new).count(), 1)
