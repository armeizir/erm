from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from risk.models import ProfilRisikoKorporatItem, ProfilRisikoKorporatSummary


class CorporateRiskItemLabelTests(SimpleTestCase):
    def test_string_contains_item_number_and_risk_event(self):
        summary = ProfilRisikoKorporatSummary(judul="Profil Risiko Korporat 2026", tahun=2026)
        item = ProfilRisikoKorporatItem(
            summary=summary,
            no_item=11,
            peristiwa_risiko="Serangan cyber pada sistem IT/OT",
        )

        label = str(item)

        self.assertIn("#11", label)
        self.assertIn("Serangan cyber pada sistem IT/OT", label)

    def test_string_falls_back_when_risk_event_empty(self):
        item = ProfilRisikoKorporatItem(no_item=11, peristiwa_risiko="")

        label = str(item)

        self.assertIn("#11", label)
        self.assertIn("Peristiwa risiko belum diisi", label)

    def test_dropdown_label_uses_display_label(self):
        summary = ProfilRisikoKorporatSummary(judul="Profil Risiko Korporat 2026", tahun=2026)
        item = ProfilRisikoKorporatItem(
            summary=summary,
            no_item=11,
            peristiwa_risiko="Gangguan operasional sistem",
        )

        class RiskItemChoiceField(forms.ModelChoiceField):
            def label_from_instance(self, obj):
                return obj.get_display_label()

        field = RiskItemChoiceField(queryset=ProfilRisikoKorporatItem.objects.none())

        self.assertIn("Gangguan operasional sistem", field.label_from_instance(item))


class SensitiveEndpointSecurityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="risk-user", password="unused")
        self.user.user_permissions.add(
            Permission.objects.get(codename="view_profilrisikokorporatitem"),
            Permission.objects.get(codename="change_kpmritem"),
        )

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_rcc_export_requires_login(self):
        response = self.client.get(reverse("rcc_export_excel"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_kpmr_review_requires_login(self):
        response = self.client.get(reverse("kpmr_review", args=[1]))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_kpmr_update_is_post_only_for_authenticated_user(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("kpmr_update_item"))

        self.assertEqual(response.status_code, 405)

    def test_kpmr_update_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(
            reverse("kpmr_update_item"),
            data='{"id": 1, "field": "catatan", "value": "ok"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
