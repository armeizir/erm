from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from risk.executive_risk_v2 import _dashboard_data


class ExecutiveRiskV2DashboardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="director-v2-test", password="test-password"
        )

    def test_login_is_required(self):
        response = self.client.get(reverse("executive_risk_v2_dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_uses_august_workbook_values(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("executive_risk_v2_dashboard"), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rp 4,72 M")
        self.assertContains(response, "Rp 6,73 M")
        self.assertContains(response, "Rp 696,6 Juta")
        self.assertContains(response, "Rp 9,75 M")
        self.assertContains(response, "High 24")
        self.assertContains(response, "risk/brand/danantara.svg")
        self.assertContains(response, "risk/brand/pln-batam.jpg")
        self.assertContains(response, 'id="yearSelect"')
        self.assertContains(response, 'id="riskSelect"')

    def test_tv_mode_and_rotation_controls_are_supported(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("executive_risk_v2_dashboard"), {"tv": "1"}, secure=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<body class="tv">')
        self.assertContains(response, 'id="fullscreenBtn"')
        self.assertContains(response, 'id="tvBtn"')

    def test_source_mapping_has_twelve_months_and_eight_actuals(self):
        data = _dashboard_data()
        self.assertEqual(len(data["chart_values"]), 12)
        self.assertEqual(data["actual_month_count"], 8)
        self.assertAlmostEqual(data["chart_values"][7], 0.6966)
        self.assertAlmostEqual(data["chart_values"][11], 0.5419471362428687)
