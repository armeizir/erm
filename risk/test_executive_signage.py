from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from risk.models import RKAPItem


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

    def test_financial_posture_uses_rkap_profit_loss_data(self):
        section = RKAPItem.objects.create(
            tahun=2026,
            jenis_rkap="LABA_RUGI",
            tipe_baris="GROUP",
            kode="LR.2",
            sasaran="Pendapatan Usaha",
            urutan=22000,
        )
        RKAPItem.objects.create(
            tahun=2026,
            jenis_rkap="LABA_RUGI",
            tipe_baris="SUBTOTAL",
            parent=section,
            kode="LR.2.0",
            sasaran="Pendapatan Usaha",
            nilai_audited_2024=Decimal("8707506"),
            nilai_unaudited_2025=Decimal("10418383"),
            target=Decimal("10977367"),
            satuan="Rp Jt",
            urutan=22001,
        )

        self.client.force_login(self.user)
        response = self.client.get(
            reverse("executive_risk_dashboard"),
            {"year": "2026", "finance": "1"},
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["financial_mode"])
        self.assertContains(response, "Postur Keuangan RKAP 2026")
        self.assertContains(response, "Rugi Laba PSAK")
        self.assertContains(response, "10.977.367")
        self.assertNotContains(response, '<label for="risk">')
