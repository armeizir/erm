from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from masterdata.models import MasterBUMN, PeriodeLaporan, TahunBuku
from risk.models import ProfilRisikoKorporatItem, ProfilRisikoKorporatSummary

from corporate_risk.models import MonteCarloMetricHistory, RiskMetric


class MonteCarloWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(
            username="workspace-admin", email="admin@example.com", password="secret"
        )
        cls.bumn = MasterBUMN.objects.create(nama="PT Workspace", kode="WORKSPACE")
        cls.summary = ProfilRisikoKorporatSummary.objects.create(
            judul="Profil Risiko Korporat Workspace", tahun=2026
        )
        cls.item = ProfilRisikoKorporatItem.objects.create(
            summary=cls.summary,
            no_item=7,
            no_risiko=12,
            bumn=cls.bumn,
            sasaran_korporat="Operasi andal",
            peristiwa_risiko="Gangguan pasokan energi",
        )
        cls.metric = RiskMetric.objects.create(
            corporate_risk_item=cls.item,
            name="Energi tidak tersalur",
            unit="MWh",
            weight=Decimal("1.00"),
            is_target_metric=True,
            target_value=Decimal("100.0000"),
        )
        cls.year = TahunBuku.objects.create(tahun=2026)
        cls.periods = []
        month_ends = (31, 28, 31)
        for month, end_day in enumerate(month_ends, start=1):
            cls.periods.append(PeriodeLaporan.objects.create(
                tahun_buku=cls.year,
                kode_periode=f"2026-{month:02d}",
                nama_periode=f"Bulan {month} 2026",
                jenis_periode="bulanan",
                tanggal_mulai=date(2026, month, 1),
                tanggal_selesai=date(2026, month, end_day),
            ))

    def setUp(self):
        self.client.force_login(self.admin)
        self.url = reverse("risk_admin:corporate_risk_riskmetric_workspace")

    def _history(self, period, value, **kwargs):
        return MonteCarloMetricHistory.objects.create(
            metric=self.metric,
            periode=period,
            tanggal_data=period.tanggal_selesai,
            metric_value=value,
            **kwargs,
        )

    def test_superuser_can_open_workspace_and_selected_risk_and_metric_appear(self):
        response = self.client.get(self.url, {"item": self.item.pk})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Monte Carlo Workspace")
        self.assertContains(response, "Risiko 12")
        self.assertContains(response, "Gangguan pasokan energi")
        self.assertContains(response, "Energi tidak tersalur")

    def test_existing_history_appears_in_matrix(self):
        history = self._history(self.periods[0], Decimal("17.2500"))

        response = self.client.get(self.url, {"item": self.item.pk})

        self.assertContains(response, f'name="history_{self.metric.pk}_{history.periode_id}"')
        self.assertContains(response, "17.2500")

    def test_readiness_is_ready_after_three_valid_histories(self):
        for index, period in enumerate(self.periods, start=1):
            self._history(period, index)

        response = self.client.get(self.url, {"item": self.item.pk})

        self.assertContains(response, "3/3 periode")
        self.assertContains(response, ">SIAP<", html=False)
        self.assertNotContains(response, 'class="button default mc-disabled"')

    def test_post_matrix_creates_new_history(self):
        field_name = f"history_{self.metric.pk}_{self.periods[0].pk}"

        response = self.client.post(self.url, {"item": self.item.pk, field_name: "12.75"})

        self.assertRedirects(response, f"{self.url}?item={self.item.pk}")
        history = MonteCarloMetricHistory.objects.get(metric=self.metric, periode=self.periods[0])
        self.assertEqual(history.metric_value, Decimal("12.7500"))
        self.assertEqual(history.tanggal_data, self.periods[0].tanggal_selesai)
        self.assertEqual(history.status, MonteCarloMetricHistory.STATUS_UPDATED)

    def test_post_matrix_updates_actual_without_overwriting_target_or_notes(self):
        history = self._history(
            self.periods[0],
            Decimal("10"),
            target_value=Decimal("99"),
            keterangan="Catatan khusus tetap ada",
            status=MonteCarloMetricHistory.STATUS_VERIFIED,
        )
        field_name = f"history_{self.metric.pk}_{self.periods[0].pk}"

        self.client.post(self.url, {"item": self.item.pk, field_name: "22.5"})

        history.refresh_from_db()
        self.assertEqual(history.metric_value, Decimal("22.5000"))
        self.assertEqual(history.target_value, Decimal("99.0000"))
        self.assertEqual(history.keterangan, "Catatan khusus tetap ada")
        self.assertEqual(history.status, MonteCarloMetricHistory.STATUS_VERIFIED)

    def test_blank_cell_does_not_delete_or_update_old_history(self):
        history = self._history(self.periods[0], Decimal("10"), keterangan="tetap")

        self.client.post(
            self.url,
            {"item": self.item.pk, f"history_{self.metric.pk}_{self.periods[0].pk}": ""},
        )

        history.refresh_from_db()
        self.assertEqual(history.metric_value, Decimal("10.0000"))
        self.assertEqual(history.keterangan, "tetap")

    def test_view_only_user_cannot_save_history(self):
        viewer = get_user_model().objects.create_user(
            username="workspace-viewer", password="secret", is_staff=True
        )
        viewer.user_permissions.add(Permission.objects.get(
            content_type__app_label="corporate_risk", codename="view_riskmetric"
        ))
        self.client.force_login(viewer)
        field_name = f"history_{self.metric.pk}_{self.periods[0].pk}"

        get_response = self.client.get(self.url, {"item": self.item.pk})
        post_response = self.client.post(self.url, {"item": self.item.pk, field_name: "12"})

        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "Mode lihat saja")
        self.assertEqual(post_response.status_code, 403)
        self.assertFalse(MonteCarloMetricHistory.objects.filter(metric=self.metric).exists())

    def test_workspace_button_is_on_risk_metric_changelist(self):
        response = self.client.get(reverse("risk_admin:corporate_risk_riskmetric_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Monte Carlo Workspace")
        self.assertContains(response, self.url)

    def test_duplicate_calendar_periods_do_not_raise_exception(self):
        PeriodeLaporan.objects.create(
            tahun_buku=self.year,
            kode_periode="2026-01-ALT",
            nama_periode="Januari alternatif",
            jenis_periode="bulanan",
            tanggal_mulai=date(2026, 1, 1),
            tanggal_selesai=date(2026, 1, 31),
        )

        response = self.client.get(self.url, {"item": self.item.pk})

        self.assertEqual(response.status_code, 200)

    def test_risk_without_metric_shows_empty_state(self):
        empty_item = ProfilRisikoKorporatItem.objects.create(
            summary=self.summary,
            no_item=8,
            bumn=self.bumn,
            sasaran_korporat="Operasi andal",
            peristiwa_risiko="Risiko tanpa metric",
        )

        response = self.client.get(self.url, {"item": empty_item.pk})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Belum ada metric aktif")
