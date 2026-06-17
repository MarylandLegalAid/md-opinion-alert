from django.contrib.auth import get_user_model
from django.test import TestCase


class HealthzTests(TestCase):
    def test_healthz_ok(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["database"], "ok")
        self.assertIn("last_ingestion_at", body)


class HomeTests(TestCase):
    def test_home_requires_login(self):
        response = self.client.get("/", secure=True)
        self.assertEqual(response.status_code, 302)

    def test_home_renders_for_authenticated_user(self):
        user = get_user_model().objects.create_user(username="dev", password="x")
        self.client.force_login(user)
        response = self.client.get("/", secure=True)
        self.assertContains(response, "Maryland Appellate Opinion Alert")
