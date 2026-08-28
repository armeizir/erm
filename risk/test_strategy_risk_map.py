# STRATEGY_RISK_RELATIONSHIP_V4
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from .strategy_risk_map import _nko_status, _risk_status_from_level


class StrategyRiskMapHelperTests(SimpleTestCase):
    def test_risk_level_summary_mapping(self):
        self.assertEqual(_risk_status_from_level("Low")["label"], "Aman")
        self.assertEqual(_risk_status_from_level("Low to Moderate")["label"], "Aman")
        self.assertEqual(_risk_status_from_level("Moderate")["label"], "Perlu Perhatian")
        self.assertEqual(_risk_status_from_level("Moderate to High")["label"], "Tidak Aman")
        self.assertEqual(_risk_status_from_level("High")["label"], "Tidak Aman")
        self.assertEqual(_risk_status_from_level(None)["label"], "Belum Ada Data")

    def test_nko_status_mapping(self):
        self.assertEqual(_nko_status("101")["label"], "Tercapai")
        self.assertEqual(_nko_status("97")["label"], "Hampir Tercapai")
        self.assertEqual(_nko_status("94.9")["label"], "Perlu Peningkatan")
        self.assertEqual(_nko_status(None)["label"], "Belum Ada Data")


class StrategyRiskMapPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="strategy-map-user",
            password="test-pass-123",
        )
        self.url = "/strategy-risk-map/"

    def test_requires_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_renders_new_executive_relationship_page(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Executive Risk Relationship Map")
        self.assertContains(response, "Profil Risiko Korporat")
        self.assertContains(response, "Bidang / Unit Bisnis")
        self.assertContains(response, "KM (NKO)")
        self.assertNotContains(response, "Arsitektur Integrasi")
