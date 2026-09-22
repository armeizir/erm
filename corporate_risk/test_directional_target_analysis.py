from django.test import SimpleTestCase

from corporate_risk.models import RiskMetric
from corporate_risk.services import _build_target_analysis


class DirectionalTargetAnalysisTests(SimpleTestCase):
    def test_decrease_risk_uses_p5_as_worst_case(self):
        totals = list(range(1, 101))
        result = _build_target_analysis(
            totals,
            target_value=60,
            direction=RiskMetric.DIRECTION_DECREASE,
        )
        self.assertEqual(result["worst_case_percentile"], "P5")
        self.assertLess(result["worst_case_value"], result["baseline_value"])
        self.assertAlmostEqual(result["probability_not_achieve_target"], 59.0)

    def test_increase_risk_uses_p95_as_worst_case(self):
        totals = list(range(1, 101))
        result = _build_target_analysis(
            totals,
            target_value=60,
            direction=RiskMetric.DIRECTION_INCREASE,
        )
        self.assertEqual(result["worst_case_percentile"], "P95")
        self.assertGreater(result["worst_case_value"], result["baseline_value"])
        self.assertAlmostEqual(result["probability_not_achieve_target"], 40.0)
        self.assertGreater(result["var_95"], 0)

from types import SimpleNamespace
from corporate_risk.services import _analytical_normal_sum_percentiles


class AnalyticalNormalSumValidationTests(SimpleTestCase):
    def test_returns_expected_normal_sum_percentiles_when_floor_is_immaterial(self):
        assumptions = [
            SimpleNamespace(distribution_type="normal", mean_value=100.0, stddev_value=10.0),
            SimpleNamespace(distribution_type="normal", mean_value=120.0, stddev_value=12.0),
        ]
        result = _analytical_normal_sum_percentiles(actual_total=1000.0, assumptions=assumptions)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["p50"], 1220.0)
        self.assertLess(result["p5"], result["p50"])
        self.assertGreater(result["p95"], result["p50"])

    def test_declines_analytical_validation_when_zero_floor_is_material(self):
        assumptions = [
            SimpleNamespace(distribution_type="normal", mean_value=10.0, stddev_value=10.0),
        ]
        result = _analytical_normal_sum_percentiles(actual_total=100.0, assumptions=assumptions)
        self.assertIsNone(result)

from corporate_risk.services import (
    _analytical_normal_rate_percentiles,
    _analytical_normal_probability_risk,
    _simulate_rate_from_imported_assumptions,
)


class ImportedRateValidationTests(SimpleTestCase):
    def _assumptions(self):
        from datetime import date
        return [
            SimpleNamespace(
                distribution_type="normal",
                mean_value=7.50,
                stddev_value=0.20,
                p15_value=7.30,
                forecast_date=date(2026, 9, 1),
            ),
            SimpleNamespace(
                distribution_type="normal",
                mean_value=7.60,
                stddev_value=0.30,
                p15_value=7.30,
                forecast_date=date(2026, 10, 1),
            ),
        ]

    def test_analytical_rate_is_monthly_arithmetic_mean(self):
        assumptions = self._assumptions()
        result = _analytical_normal_rate_percentiles(
            actual_sum=14.0,
            actual_count=2,
            assumptions=assumptions,
        )
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["p50"], (14.0 + 7.50 + 7.60) / 4.0)
        self.assertLess(result["p5"], result["p50"])
        self.assertGreater(result["p95"], result["p50"])

    def test_stochastic_rate_centers_near_analytical_p50(self):
        assumptions = self._assumptions()
        analytical = _analytical_normal_rate_percentiles(
            actual_sum=14.0,
            actual_count=2,
            assumptions=assumptions,
        )
        simulation = _simulate_rate_from_imported_assumptions(
            actual_values=[7.0, 7.0],
            assumptions=assumptions,
            n_simulations=10000,
            rng_seed=20260909,
        )
        self.assertAlmostEqual(simulation["p50_total"], analytical["p50"], delta=0.02)
        self.assertEqual(simulation["descriptive_stats"]["aggregation_method"], "arithmetic_mean_monthly")

    def test_probability_increase_uses_upper_tail(self):
        analytical = {
            "mean": 7.36863724077534,
            "sigma": 0.06243731930079,
        }
        probability = _analytical_normal_probability_risk(
            analytical=analytical,
            target_value=7.47,
            direction=RiskMetric.DIRECTION_INCREASE,
        )
        self.assertAlmostEqual(probability, 5.22485, places=3)

from datetime import date
from corporate_risk.services import _simulate_metric_from_imported_assumptions


class ImportedCorrelatedNormalSumTests(SimpleTestCase):
    def _assumptions(self):
        dependency = {
            "dependency_model": {
                "type": "equicorrelation",
                "rho": 0.15,
                "truncate_at_zero": False,
            }
        }
        return [
            SimpleNamespace(
                distribution_type="normal",
                mean_value=30.0,
                stddev_value=20.0,
                p15_value=10.0,
                forecast_date=date(2026, month, 1),
                source_metadata=dependency,
            )
            for month in range(9, 13)
        ]

    def test_correlated_analytical_sigma_includes_covariance(self):
        assumptions = self._assumptions()
        result = _analytical_normal_sum_percentiles(actual_total=100.0, assumptions=assumptions)
        self.assertIsNotNone(result)
        independent_sigma = (4 * 20.0 * 20.0) ** 0.5
        self.assertGreater(result["sigma"], independent_sigma)
        self.assertEqual(result["validation_basis"], "analytical_correlated_normal_sum")
        self.assertAlmostEqual(result["correlation_rho"], 0.15)
        self.assertFalse(result["truncate_at_zero"])

    def test_correlated_simulation_does_not_apply_zero_floor(self):
        assumptions = self._assumptions()
        simulation = _simulate_metric_from_imported_assumptions(
            actual_total=100.0,
            assumptions=assumptions,
            n_simulations=10000,
            rng_seed=20260909,
        )
        self.assertEqual(simulation["descriptive_stats"]["dependency_type"], "equicorrelation")
        self.assertAlmostEqual(simulation["descriptive_stats"]["correlation_rho"], 0.15)
        self.assertFalse(simulation["descriptive_stats"]["truncate_at_zero"])
        analytical = _analytical_normal_sum_percentiles(actual_total=100.0, assumptions=assumptions)
        self.assertAlmostEqual(simulation["p50_total"], analytical["p50"], delta=3.0)
