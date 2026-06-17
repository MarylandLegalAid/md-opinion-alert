from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from accounts.auth import EntraOIDCBackend

User = get_user_model()

MEMBER_CLAIMS = {
    "oid": "11111111-1111-1111-1111-111111111111",
    "acct": 0,
    "email": "jane@org.example",
    "name": "Jane Lawyer",
}


@override_settings(
    OIDC_RP_CLIENT_ID="test-client",
    OIDC_RP_CLIENT_SECRET="test-secret",
    ADMIN_APP_ROLE="Admin",
)
class VerifyClaimsTests(TestCase):
    def setUp(self):
        self.backend = EntraOIDCBackend()

    def test_member_accepted(self):
        self.assertTrue(self.backend.verify_claims(MEMBER_CLAIMS))

    def test_guest_rejected(self):
        claims = {**MEMBER_CLAIMS, "acct": 1}
        self.assertFalse(self.backend.verify_claims(claims))

    def test_acct_string_zero_accepted(self):
        claims = {**MEMBER_CLAIMS, "acct": "0"}
        self.assertTrue(self.backend.verify_claims(claims))

    def test_missing_oid_rejected(self):
        claims = {k: v for k, v in MEMBER_CLAIMS.items() if k != "oid"}
        self.assertFalse(self.backend.verify_claims(claims))

    def test_missing_email_and_upn_rejected(self):
        claims = {k: v for k, v in MEMBER_CLAIMS.items() if k != "email"}
        self.assertFalse(self.backend.verify_claims(claims))

    def test_upn_accepted_in_place_of_email(self):
        claims = {k: v for k, v in MEMBER_CLAIMS.items() if k != "email"}
        claims["preferred_username"] = "jane@org.example"
        self.assertTrue(self.backend.verify_claims(claims))

    def test_no_acct_graph_member_accepted(self):
        claims = {k: v for k, v in MEMBER_CLAIMS.items() if k != "acct"}
        claims["_graph_user_type"] = "Member"
        self.assertTrue(self.backend.verify_claims(claims))

    def test_no_acct_graph_guest_rejected(self):
        claims = {k: v for k, v in MEMBER_CLAIMS.items() if k != "acct"}
        claims["_graph_user_type"] = "Guest"
        self.assertFalse(self.backend.verify_claims(claims))

    def test_no_membership_signal_fails_closed(self):
        claims = {k: v for k, v in MEMBER_CLAIMS.items() if k != "acct"}
        self.assertFalse(self.backend.verify_claims(claims))


@override_settings(
    OIDC_RP_CLIENT_ID="test-client",
    OIDC_RP_CLIENT_SECRET="test-secret",
    ADMIN_APP_ROLE="Admin",
)
class UserProvisioningTests(TestCase):
    def setUp(self):
        self.backend = EntraOIDCBackend()

    def test_create_user_keyed_on_oid(self):
        user = self.backend.create_user(MEMBER_CLAIMS)
        self.assertEqual(user.entra_oid, MEMBER_CLAIMS["oid"])
        self.assertEqual(user.username, MEMBER_CLAIMS["oid"])
        self.assertEqual(user.email, "jane@org.example")
        self.assertEqual(user.display_name, "Jane Lawyer")
        self.assertFalse(user.is_staff)
        self.assertEqual(user.digest_cadence, User.DigestCadence.WEEKLY)

    def test_admin_role_maps_to_staff(self):
        claims = {**MEMBER_CLAIMS, "roles": ["Admin"]}
        user = self.backend.create_user(claims)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    def test_admin_role_revoked_on_next_login(self):
        user = self.backend.create_user({**MEMBER_CLAIMS, "roles": ["Admin"]})
        user = self.backend.update_user(user, MEMBER_CLAIMS)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_filter_matches_on_oid_not_email(self):
        self.backend.create_user(MEMBER_CLAIMS)
        same_email_other_oid = {**MEMBER_CLAIMS, "oid": "2" * 32}
        self.assertEqual(
            self.backend.filter_users_by_claims(MEMBER_CLAIMS).count(), 1
        )
        self.assertEqual(
            self.backend.filter_users_by_claims(same_email_other_oid).count(), 0
        )

    def test_email_falls_back_to_upn(self):
        claims = {k: v for k, v in MEMBER_CLAIMS.items() if k != "email"}
        claims["preferred_username"] = "jane.upn@org.example"
        user = self.backend.create_user(claims)
        self.assertEqual(user.email, "jane.upn@org.example")


@override_settings(
    OIDC_RP_CLIENT_ID="test-client",
    OIDC_RP_CLIENT_SECRET="test-secret",
)
class GetUserinfoTests(TestCase):
    def setUp(self):
        self.backend = EntraOIDCBackend()

    def test_id_token_claims_win_and_no_graph_call_when_acct_present(self):
        payload = dict(MEMBER_CLAIMS)
        with (
            patch.object(
                EntraOIDCBackend,
                "get_userinfo",
                wraps=self.backend.get_userinfo,
            ),
            patch(
                "mozilla_django_oidc.auth.OIDCAuthenticationBackend.get_userinfo",
                return_value={"email": "stale@org.example", "sub": "abc"},
            ),
            patch.object(EntraOIDCBackend, "_fetch_user_type") as fetch,
        ):
            claims = self.backend.get_userinfo("at", "it", payload)
        self.assertEqual(claims["email"], "jane@org.example")
        self.assertEqual(claims["sub"], "abc")
        fetch.assert_not_called()

    def test_graph_fallback_used_when_acct_missing(self):
        payload = {k: v for k, v in MEMBER_CLAIMS.items() if k != "acct"}
        with (
            patch(
                "mozilla_django_oidc.auth.OIDCAuthenticationBackend.get_userinfo",
                return_value={},
            ),
            patch.object(
                EntraOIDCBackend, "_fetch_user_type", return_value="Member"
            ) as fetch,
        ):
            claims = self.backend.get_userinfo("at", "it", payload)
        fetch.assert_called_once_with("at")
        self.assertEqual(claims["_graph_user_type"], "Member")
