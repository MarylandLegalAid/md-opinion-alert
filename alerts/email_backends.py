"""Microsoft-native email backends.

- ``ACSEmailBackend`` (primary): Azure Communication Services Email via the
  ``azure-communication-email`` SDK, authenticated with a service principal
  through ``DefaultAzureCredential`` (AZURE_CLIENT_ID / AZURE_TENANT_ID /
  AZURE_CLIENT_SECRET env vars). No SMTP Basic Auth anywhere.
- ``GraphEmailBackend`` (documented alternative): Graph ``sendMail`` from a
  shared mailbox using an app registration with application ``Mail.Send``.

Selection is one config switch: ``EMAIL_BACKEND_CHOICE`` env var
(console | smtp | acs | graph). Azure SDKs are imported lazily so local
dev/test never needs them installed or configured.
"""

import logging

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

GRAPH_SENDMAIL_URL = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"


def _html_alternative(message):
    for content, mimetype in getattr(message, "alternatives", []):
        if mimetype == "text/html":
            return content
    return None


class ACSEmailBackend(BaseEmailBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from azure.communication.email import EmailClient
            from azure.identity import DefaultAzureCredential

            self._client = EmailClient(
                settings.ACS_ENDPOINT, DefaultAzureCredential()
            )
        return self._client

    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages:
            payload = {
                "senderAddress": settings.ACS_SENDER_ADDRESS,
                "recipients": {
                    "to": [{"address": addr} for addr in message.to],
                },
                "content": {
                    "subject": message.subject,
                    "plainText": message.body,
                },
            }
            html = _html_alternative(message)
            if html:
                payload["content"]["html"] = html
            try:
                poller = self.client.begin_send(payload)
                result = poller.result()
            except Exception:
                if not self.fail_silently:
                    raise
                logger.exception("ACS send failed")
                continue
            message.provider_message_id = result.get("id", "")
            sent += 1
        return sent


class GraphEmailBackend(BaseEmailBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._credential = None

    def _token(self):
        if self._credential is None:
            from azure.identity import ClientSecretCredential

            self._credential = ClientSecretCredential(
                tenant_id=settings.AZURE_TENANT_ID,
                client_id=settings.AZURE_CLIENT_ID,
                client_secret=settings.AZURE_CLIENT_SECRET,
            )
        return self._credential.get_token(GRAPH_SCOPE).token

    def send_messages(self, email_messages):
        sent = 0
        url = GRAPH_SENDMAIL_URL.format(sender=settings.GRAPH_SENDER_ADDRESS)
        for message in email_messages:
            html = _html_alternative(message)
            payload = {
                "message": {
                    "subject": message.subject,
                    "body": {
                        "contentType": "HTML" if html else "Text",
                        "content": html or message.body,
                    },
                    "toRecipients": [
                        {"emailAddress": {"address": addr}} for addr in message.to
                    ],
                },
                "saveToSentItems": True,
            }
            try:
                response = requests.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._token()}"},
                    timeout=30,
                )
                response.raise_for_status()
            except Exception:
                if not self.fail_silently:
                    raise
                logger.exception("Graph sendMail failed")
                continue
            sent += 1
        return sent
