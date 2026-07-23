from datetime import date
from types import SimpleNamespace

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core import mail
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from corporate_risk.admin import MultiMetricMonteCarloResultAdmin, MultiMetricMonteCarloResultForm
from corporate_risk.models import MonteCarloMetricHistory, MultiMetricMonteCarloResult, RiskMetric
from corporate_risk.services import (
    _build_target_analysis,
    _select_descriptive_metric,
    recommend_monte_carlo_distribution,
)
from corporate_risk.history_services import duplicate_metric_history_to_next_month
from corporate_risk.history_notifications import send_metric_history_assignment_notification
from masterdata.models import MasterBUMN, PeriodeLaporan, TahunBuku
from risk.models import ProfilRisikoKorporatItem, ProfilRisikoKorporatSummary


class DistributionRecommendationAnalysisTests(SimpleTestCase):
    def test_recommendation_contains_analysis_fields(self):
        recommendation = recommend_monte_carlo_distribution([10, 12, 15, 19, 28, 43])

        self.assertIn("reason_summary", recommendation)
        self.assertIn("reason_detail", recommendation)
        self.assertIn("limitations", recommendation)
        self.assertIn("confidence", recommendation)
        self.assertIn("data_quality_warnings", recommendation)

    def test_history_count_under_24_warns_limited_data(self):
        recommendation = recommend_monte_carlo_distribution([10, 11, 13, 17, 23, 31])

        warnings = recommendation["data_quality_warnings"]

        self.assertTrue(any("kurang dari 24 periode" in warning for warning in warnings))

    def test_non_negative_skewed_data_gets_tail_or_bounded_recommendation(self):
        recommendation = recommend_monte_carlo_distribution([1, 1, 2, 3, 5, 9, 20, 55])

        self.assertIn(recommendation["recommended"], {"lognormal", "gamma", "beta", "weibull"})

    def test_distribution_override_requires_user_justification(self):
        result = MultiMetricMonteCarloResult(
            recommended_distribution="lognormal",
            selected_distribution="normal",
            distribution_type="normal",
            selected_distribution_justification="",
        )

        with self.assertRaises(ValidationError):
            result.clean()


class MultiMetricMonteCarloResultFormTests(TestCase):
    def setUp(self):
        bumn = MasterBUMN.objects.create(nama="PT PLN Batam", kode="PLNBATAM")
        summary = ProfilRisikoKorporatSummary.objects.create(
            judul="Profil Risiko Korporat 2026",
            tahun=2026,
        )
        self.item = ProfilRisikoKorporatItem.objects.create(
            summary=summary,
            no_item=1,
            bumn=bumn,
            sasaran_korporat="Menjaga layanan andal",
            peristiwa_risiko="Gangguan keamanan siber IT/OT",
        )
        self.metric = RiskMetric.objects.create(
            corporate_risk_item=self.item,
            name="Jumlah Breach Cyber IT/OT",
            unit="kejadian",
            is_active=True,
        )
        tahun_buku = TahunBuku.objects.create(tahun=2026)
        self.forecast_periode = PeriodeLaporan.objects.create(
            tahun_buku=tahun_buku,
            kode_periode="2026-03",
            nama_periode="Maret 2026",
            jenis_periode="bulanan",
            tanggal_mulai=date(2026, 3, 1),
            tanggal_selesai=date(2026, 3, 31),
        )

    def _form_data(self, **overrides):
        data = {
            "corporate_risk_item": self.item.pk,
            "forecast_periode": self.forecast_periode.pk,
            "scenario_percentile": 80,
            "forecasting_method": "best_fit_normal_growth",
            "forecast_periods": 9,
            "prediction_interval": "5_95",
            "n_simulations": 10000,
            "distribution_type": "empirical",
        }
        data.update(overrides)
        return data

    def _add_three_history_periods(self):
        periods = [
            ("2026-01", "Januari 2026", date(2026, 1, 1), date(2026, 1, 31), 1),
            ("2026-02", "Februari 2026", date(2026, 2, 1), date(2026, 2, 28), 2),
            ("2026-03-H", "Maret 2026 Histori", date(2026, 3, 1), date(2026, 3, 31), 3),
        ]
        tahun_buku = self.forecast_periode.tahun_buku
        for kode, nama, mulai, selesai, value in periods:
            periode = PeriodeLaporan.objects.create(
                tahun_buku=tahun_buku,
                kode_periode=kode,
                nama_periode=nama,
                jenis_periode="bulanan",
                tanggal_mulai=mulai,
                tanggal_selesai=selesai,
            )
            MonteCarloMetricHistory.objects.create(
                metric=self.metric,
                periode=periode,
                tanggal_data=selesai,
                metric_value=value,
            )

    def test_add_form_blocks_metric_with_less_than_three_history_periods(self):
        form = MultiMetricMonteCarloResultForm(data=self._form_data())

        self.assertFalse(form.is_valid())
        errors = form.errors.as_text()
        self.assertIn("Data histori belum cukup", errors)
        self.assertIn("Jumlah Breach Cyber IT/OT: 0/3 periode", errors)

    def test_add_form_allows_metric_with_three_history_periods(self):
        self._add_three_history_periods()
        form = MultiMetricMonteCarloResultForm(data=self._form_data())

        self.assertNotIn("Data histori belum cukup", form.errors.as_text())

    def test_add_form_requires_minimum_one_thousand_trials(self):
        self._add_three_history_periods()

        form = MultiMetricMonteCarloResultForm(data=self._form_data(n_simulations=999))

        self.assertFalse(form.is_valid())
        self.assertIn("minimal 1,000", form.errors.as_text())

    def test_duplicate_metric_history_creates_unupdated_next_month_with_lineage(self):
        user = get_user_model().objects.create_user(username="adminerm")
        source = MonteCarloMetricHistory.objects.create(
            metric=self.metric,
            periode=self.forecast_periode,
            tanggal_data=date(2026, 3, 1),
            metric_value=70,
            target_value=75,
            status=MonteCarloMetricHistory.STATUS_VERIFIED,
        )

        target = duplicate_metric_history_to_next_month(source, user)

        self.assertEqual(target.periode.kode_periode, "2026-04")
        self.assertEqual(target.periode.nama_periode, "April 2026")
        self.assertEqual(target.tanggal_data, date(2026, 4, 1))
        self.assertEqual(target.metric_value, source.metric_value)
        self.assertEqual(target.target_value, source.target_value)
        self.assertEqual(target.status, MonteCarloMetricHistory.STATUS_UNUPDATED)
        self.assertEqual(target.copied_from, source)
        self.assertEqual(target.copied_by, user)
        self.assertIsNotNone(target.copied_at)

        with self.assertRaisesMessage(ValidationError, "sudah pernah dibuat"):
            duplicate_metric_history_to_next_month(source, user)

    def test_unupdated_copy_cannot_create_following_month(self):
        user = get_user_model().objects.create_user(username="adminerm")
        source = MonteCarloMetricHistory.objects.create(
            metric=self.metric,
            periode=self.forecast_periode,
            tanggal_data=date(2026, 3, 1),
            metric_value=70,
            status=MonteCarloMetricHistory.STATUS_UPDATED,
        )
        april = duplicate_metric_history_to_next_month(source, user)

        with self.assertRaisesMessage(ValidationError, "harus diperbarui"):
            duplicate_metric_history_to_next_month(april, user)

    def test_assignment_email_contains_restricted_input_link(self):
        user = get_user_model().objects.create_user(
            username="data.owner", email="owner@example.com"
        )
        history = MonteCarloMetricHistory.objects.create(
            metric=self.metric,
            periode=self.forecast_periode,
            tanggal_data=date(2026, 3, 1),
            metric_value=70,
            status=MonteCarloMetricHistory.STATUS_UNUPDATED,
            assigned_to=user,
        )
        request = RequestFactory().get("/")

        recipient = send_metric_history_assignment_notification(history, request=request)

        history.refresh_from_db()
        self.assertEqual(recipient, "owner@example.com")
        self.assertEqual(history.notification_count, 1)
        self.assertIsNotNone(history.notification_sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(
            reverse("metric_history_assigned_input", args=[history.pk]),
            mail.outbox[0].body,
        )

    def test_only_assigned_user_can_submit_history_data(self):
        owner = get_user_model().objects.create_user(username="owner", password="secret")
        other = get_user_model().objects.create_user(username="other", password="secret")
        history = MonteCarloMetricHistory.objects.create(
            metric=self.metric,
            periode=self.forecast_periode,
            tanggal_data=date(2026, 3, 1),
            metric_value=70,
            status=MonteCarloMetricHistory.STATUS_UNUPDATED,
            assigned_to=owner,
        )
        url = reverse("metric_history_assigned_input", args=[history.pk])
        self.client.force_login(other)
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_login(owner)
        response = self.client.post(
            url,
            {"metric_value": "72.5", "target_value": "75", "keterangan": "Realisasi Maret"},
        )
        self.assertEqual(response.status_code, 302)
        history.refresh_from_db()
        self.assertEqual(history.status, history.STATUS_UPDATED)
        self.assertEqual(str(history.metric_value), "72.5000")
        self.assertEqual(history.completed_by, owner)
        self.assertIsNotNone(history.completed_at)


class MultiMetricMonteCarloTrialsDisplayTests(SimpleTestCase):
    def test_target_analysis_keeps_actual_trial_count_and_full_distribution(self):
        analysis = _build_target_analysis(
            simulation_totals=list(range(10000)),
            target_value=5000,
        )

        self.assertEqual(analysis["total_simulation"], 10000)
        self.assertEqual(len(analysis["distribution_sample"]), 10000)

    def test_output_distribution_chart_uses_total_simulation_for_trials_label(self):
        admin = MultiMetricMonteCarloResultAdmin(MultiMetricMonteCarloResult, AdminSite())
        obj = SimpleNamespace(
            id=1,
            n_simulations=10000,
            target_value=50,
            baseline_value=50,
            probability_achieve_target=50,
            simulation_snapshot={
                "target_analysis": {
                    "distribution_sample": [45, 48, 50, 52, 55],
                    "total_simulation": 10000,
                    "target_value": 50,
                }
            },
        )

        html = str(admin.target_distribution_chart_html(obj))

        self.assertIn("10,000", html)
        self.assertIn("const totalTrials = 10000", html)

    def test_descriptive_prediction_rows_use_month_name_fallback(self):
        admin = MultiMetricMonteCarloResultAdmin(MultiMetricMonteCarloResult, AdminSite())
        obj = SimpleNamespace(
            forecast_periode=SimpleNamespace(tanggal_selesai=date(2026, 5, 31)),
            simulation_snapshot={
                "descriptive_projection_rows": [
                    {"bulan_index": 1, "f_p50": 10, "f_p15": 8, "std_dev": 2},
                ],
                "descriptive_stats": {},
            },
        )

        html = str(admin.multi_metric_descriptive_projection_rows_html(obj))

        self.assertIn("Juni 2026", html)
        self.assertNotIn("Bulan-1", html)

    def test_descriptive_metric_selection_skips_all_zero_target_metric(self):
        zero_target_metric = {
            "metric_name": "Jumlah Breach Cyber IT/OT",
            "descriptive_stats": {"f_p50": 0, "f_p15": 0, "std_dev": 0, "max": 0},
            "projection_rows": [{"p50": 0, "p15": 0, "stdev_f": 0, "mean": 0}],
            "history_rows": [{"actual": 0}, {"actual": 0}, {"actual": 0}],
        }
        meaningful_metric = {
            "metric_name": "Jumlah Threat Cyber IT/OT",
            "descriptive_stats": {"f_p50": 25000, "f_p15": 18000, "std_dev": 7000, "max": 100000},
            "projection_rows": [{"p50": 25000, "p15": 18000, "stdev_f": 7000, "mean": 25000}],
            "history_rows": [{"actual": 18659}, {"actual": 99429}, {"actual": 17569}],
        }

        selected = _select_descriptive_metric(
            [zero_target_metric, meaningful_metric],
            target_metric_row=zero_target_metric,
        )

        self.assertEqual(selected["metric_name"], "Jumlah Threat Cyber IT/OT")


class MultiMetricMonteCarloPDFExportTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_superuser(
            username="pdf-admin",
            email="pdf-admin@example.com",
            password="secret",
        )
        self.client.force_login(self.user)
        bumn = MasterBUMN.objects.create(nama="PT PLN Batam", kode="PLNBATAM")
        summary = ProfilRisikoKorporatSummary.objects.create(
            judul="Profil Risiko Korporat 2026",
            tahun=2026,
        )
        self.item = ProfilRisikoKorporatItem.objects.create(
            summary=summary,
            no_item=11,
            bumn=bumn,
            sasaran_korporat="Menjaga operasional perusahaan",
            peristiwa_risiko="Serangan Cyber terhadap IT dan OT",
        )
        tahun_buku = TahunBuku.objects.create(tahun=2026)
        self.period = PeriodeLaporan.objects.create(
            tahun_buku=tahun_buku,
            kode_periode="2026-05",
            nama_periode="May 2026",
            jenis_periode="bulanan",
            tanggal_mulai=date(2026, 5, 1),
            tanggal_selesai=date(2026, 5, 31),
        )
        self.quarter_period = PeriodeLaporan.objects.create(
            tahun_buku=tahun_buku,
            kode_periode="2026-TW2",
            nama_periode="Triwulan II 2026",
            jenis_periode="triwulan",
            tanggal_mulai=date(2026, 4, 1),
            tanggal_selesai=date(2026, 6, 30),
        )

    def _result(self, **overrides):
        data = {
            "corporate_risk_item": self.item,
            "forecast_periode": self.period,
            "n_simulations": 10000,
            "forecast_periods": 8,
            "prediction_interval": "5_95",
            "distribution_type": "empirical",
            "recommended_distribution": "empirical",
            "scenario_percentile": 80,
            "baseline_value": 5000,
            "var_95": 750,
            "target_value": 4500,
            "probability_achieve_target": 82.5,
            "requires_mitigation": False,
            "target_status": "Tercapai",
            "simulation_snapshot": {
                "n_simulations": 10000,
                "target_analysis": {
                    "distribution_sample": [4200, 4500, 4900, 5100, 5300, 5600],
                    "total_simulation": 10000,
                    "target_value": 4500,
                    "forecast_total": 5000,
                    "probability_achieve_target": 82.5,
                    "var_95": 750,
                    "target_status": "Tercapai",
                },
            },
            "metric_snapshot": {
                "metrics": [
                    {
                        "metric_id": 1,
                        "metric_name": "Jumlah Threat Cyber IT/OT",
                        "unit": "kejadian",
                        "direction": "Semakin besar semakin berisiko",
                        "weight": 1,
                        "history_rows": [
                            {"tanggal": "2026-01-31", "actual": 10},
                            {"tanggal": "2026-02-28", "actual": 12},
                            {"tanggal": "2026-03-31", "actual": 15},
                        ],
                        "distribution_recommendation": {
                            "recommended_label": "Empirical Distribution",
                            "confidence": "Medium",
                            "reason_summary": "Data digunakan langsung dari pola histori.",
                            "reason_detail": "Histori terbatas sehingga empirical menjadi pilihan konservatif.",
                            "limitations": "Perlu tambahan data bulanan.",
                            "data_quality_warnings": ["Data histori kurang dari 24 periode."],
                        },
                    }
                ]
            },
        }
        data.update(overrides)
        return MultiMetricMonteCarloResult.objects.create(**data)

    def test_export_pdf_url_returns_pdf_for_superuser(self):
        result = self._result()
        url = reverse(
            "risk_admin:corporate_risk_multimetricmontecarloresult_export_pdf",
            args=[result.pk],
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(
            f'multi_metric_monte_carlo_result_{result.pk}.pdf',
            response["Content-Disposition"],
        )
        self.assertGreater(len(response.content), 1000)
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_export_pdf_handles_incomplete_result_without_500(self):
        result = self._result(simulation_snapshot={}, metric_snapshot={})
        url = reverse(
            "risk_admin:corporate_risk_multimetricmontecarloresult_export_pdf",
            args=[result.pk],
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertGreater(len(response.content), 1000)

    def test_change_form_shows_management_pdf_export_button(self):
        result = self._result()
        url = reverse(
            "risk_admin:corporate_risk_multimetricmontecarloresult_change",
            args=[result.pk],
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Export PDF Laporan Manajemen")

    def test_quarterly_lmr_pdf_url_returns_pdf_for_superuser(self):
        self._result(forecast_periode=self.quarter_period)
        url = reverse(
            "risk_admin:risk_profilrisikokorporatsummary_lmr_quarterly_pdf",
            args=[self.item.summary_id, self.quarter_period.pk],
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("LMR_Profil_Risiko_Monte_Carlo", response["Content-Disposition"])
        self.assertGreater(len(response.content), 1000)
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_lmr_pdf_fallback_url_returns_pdf_without_quarter_period(self):
        self._result()
        self.quarter_period.delete()
        url = reverse(
            "risk_admin:risk_profilrisikokorporatsummary_lmr_pdf",
            args=[self.item.summary_id],
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("SEMUA_PERIODE", response["Content-Disposition"])
        self.assertGreater(len(response.content), 1000)
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_profile_list_shows_lmr_pdf_button_without_quarter_period(self):
        self.quarter_period.delete()
        url = reverse("risk_admin:risk_profilrisikokorporatsummary_changelist")

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "LMR PDF")
        self.assertNotContains(response, "<td class=\"field-lmr_button\">-</td>", html=True)

    def test_profile_change_form_shows_quarterly_lmr_export(self):
        url = reverse(
            "risk_admin:risk_profilrisikokorporatsummary_change",
            args=[self.item.summary_id],
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Generate LMR Triwulan")
        self.assertContains(response, "Export LMR Profil Risiko + Monte Carlo")
