"""Entra ID OIDC authentication backend.

Policy:

- Users are keyed on the immutable Entra object id (``oid`` claim), never email.
- Tenant *members* only: the ``acct`` claim must be 0. Guests (``acct`` == 1)
  are rejected. If ``acct`` is absent from the token, fall back to a Graph
  ``/me`` ``userType`` check; if that is also unavailable, fail closed.
- Admin: presence of the configured app role (``roles`` claim) maps to Django
  ``is_staff``/``is_superuser`` on every login, so privilege is managed in
  Entra and revocation takes effect at next sign-in.
"""

import logging

import requests
from django.conf import settings
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

logger = logging.getLogger(__name__)

GRAPH_ME_URL = "https://graph.microsoft.com/v1.0/me?$select=userType"


class EntraOIDCBackend(OIDCAuthenticationBackend):
    def get_userinfo(self, access_token, id_token, payload):
        """Merge userinfo-endpoint claims with verified ID-token claims.

        Entra puts ``oid``, ``acct`` and ``roles`` in the ID token; the Graph
        userinfo endpoint only returns basic profile fields. The verified
        ID-token payload wins on conflicts.
        """
        claims = dict(super().get_userinfo(access_token, id_token, payload))
        claims.update(payload)

        if "acct" not in claims:
            user_type = self._fetch_user_type(access_token)
            if user_type is not None:
                claims["_graph_user_type"] = user_type
        return claims

    def _fetch_user_type(self, access_token):
        """Defense-in-depth guest check when the token lacks ``acct``."""
        try:
            response = requests.get(
                GRAPH_ME_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("userType")
        except requests.RequestException:
            logger.warning("Graph /me userType lookup failed", exc_info=True)
            return None

    def verify_claims(self, claims):
        oid = claims.get("oid")
        if not oid:
            logger.warning("OIDC login rejected: no oid claim present")
            return False

        # Digests need a deliverable address; UPN is a valid fallback when the
        # account has no mail attribute.
        if not (claims.get("email") or claims.get("preferred_username")):
            logger.warning("OIDC login rejected: no email or UPN claim")
            return False

        return self._is_tenant_member(claims)

    def _is_tenant_member(self, claims):
        acct = claims.get("acct")
        if acct is not None:
            if str(acct) == "0":
                return True
            logger.warning("OIDC login rejected: guest account (acct=%r)", acct)
            return False

        user_type = claims.get("_graph_user_type")
        if user_type is not None:
            if user_type.lower() == "member":
                return True
            logger.warning(
                "OIDC login rejected: guest account (userType=%r)", user_type
            )
            return False

        # Fail closed: we could not establish member status at all.
        logger.error(
            "OIDC login rejected: neither acct claim nor Graph userType "
            "available; check the app registration's optional claims"
        )
        return False

    def filter_users_by_claims(self, claims):
        return self.UserModel.objects.filter(entra_oid=claims["oid"])

    def create_user(self, claims):
        user = self.UserModel.objects.create_user(username=claims["oid"])
        return self._apply_claims(user, claims)

    def update_user(self, user, claims):
        return self._apply_claims(user, claims)

    def _apply_claims(self, user, claims):
        is_admin = settings.ADMIN_APP_ROLE in claims.get("roles", [])
        user.entra_oid = claims["oid"]
        user.email = (
            claims.get("email") or claims.get("preferred_username") or user.email
        )
        user.display_name = claims.get("name", user.display_name)
        user.is_staff = is_admin
        user.is_superuser = is_admin
        user.save()
        return user
