from django.contrib.auth import get_user_model
from django.test import TestCase


class KongRemoteUserTests(TestCase):
    sub = "auth0|abc123"
    kong = {"x-authenticated-user": sub}

    def test_kong_user_is_logged_in_and_created(self):
        resp = self.client.get("/items/", headers=self.kong)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(get_user_model().objects.filter(username=self.sub).exists())
        self.assertContains(resp, self.sub)
        self.assertContains(resp, 'href="/items/logout"')

    def test_without_header_django_login_is_required(self):
        resp = self.client.get("/items/")
        self.assertRedirects(resp, "/login/?next=/items/", fetch_redirect_response=False)

    def test_header_switches_user(self):
        self.client.get("/items/", headers=self.kong)
        resp = self.client.get("/items/", headers={"x-authenticated-user": "auth0|other"})
        self.assertContains(resp, "auth0|other")

    def csrf_post(self, origin, sku):
        client = self.client_class(enforce_csrf_checks=True)
        client.get("/items/add/", headers=self.kong)
        token = client.cookies["csrftoken"].value
        return client.post(
            "/items/add/",
            {"name": "Widget", "sku": sku, "quantity": 1, "unit_price": "1.00", "csrfmiddlewaretoken": token},
            headers={**self.kong, "origin": origin},
        )

    def test_csrf_accepts_kong_origin(self):
        resp = self.csrf_post("https://localhost:8443", "W-1")
        self.assertRedirects(resp, "/items/", fetch_redirect_response=False)

    def test_csrf_rejects_foreign_origin(self):
        resp = self.csrf_post("https://evil.example", "W-2")
        self.assertEqual(resp.status_code, 403)
