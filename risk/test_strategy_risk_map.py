from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class StrategyRiskMapTests(TestCase):
    def setUp(self):
        self.url = reverse("strategy_risk_map:home")

    def test_requires_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_renders_as_separate_page(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="strategy-map-test",
            password="test-pass-123",
        )
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ERM Strategy")
        self.assertContains(response, "Target Tidak Tercapai")

    def test_route_name(self):
        self.assertEqual(self.url, "/strategy-risk-map/")
