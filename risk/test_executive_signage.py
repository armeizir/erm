from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse


class ExecutiveRiskDashboardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="exec.viewer", password="pass123")
        perm = Permission.objects.get(codename="view_profilrisikokorporatitem")
        self.user.user_permissions.add(perm)

    def test_requires_login(self):
        response = self.client.get(reverse("executive_risk_dashboard"), secure=True)
        self.assertEqual(response.status_code, 302)

    def test_renders_as_separate_page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("executive_risk_dashboard"), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "executive_risk_dashboard.html")
        self.assertContains(response, "Executive Risk Dashboard")

    def test_tv_mode_is_supported(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("executive_risk_dashboard"), {"tv": "1"}, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<body class="tv">')
