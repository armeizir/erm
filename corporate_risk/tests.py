from datetime import date

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from corporate_risk.admin import MultiMetricMonteCarloResultForm
from corporate_risk.models import MonteCarloMetricHistory, MultiMetricMonteCarloResult, RiskMetric
from corporate_risk.services import recommend_monte_carlo_distribution
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

    def test_add_form_blocks_metric_with_less_than_three_history_periods(self):
        form = MultiMetricMonteCarloResultForm(data={
            "corporate_risk_item": self.item.pk,
            "forecast_periode": self.forecast_periode.pk,
            "scenario_percentile": 80,
            "forecasting_method": "best_fit_normal_growth",
            "forecast_periods": 9,
            "prediction_interval": "5_95",
            "n_simulations": 10000,
            "distribution_type": "empirical",
        })

        self.assertFalse(form.is_valid())
        errors = form.errors.as_text()
        self.assertIn("Data histori belum cukup", errors)
        self.assertIn("Jumlah Breach Cyber IT/OT: 0/3 periode", errors)

    def test_add_form_allows_metric_with_three_history_periods(self):
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

        form = MultiMetricMonteCarloResultForm(data={
            "corporate_risk_item": self.item.pk,
            "forecast_periode": self.forecast_periode.pk,
            "scenario_percentile": 80,
            "forecasting_method": "best_fit_normal_growth",
            "forecast_periods": 9,
            "prediction_interval": "5_95",
            "n_simulations": 10000,
            "distribution_type": "empirical",
        })

        self.assertNotIn("Data histori belum cukup", form.errors.as_text())
