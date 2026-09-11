import random
from django.test import SimpleTestCase

from corporate_risk.services import _simulate_metric


class RollingSMAMonthlyForecastV412Test(SimpleTestCase):
    def test_recursive_sma3_monthly_baseline(self):
        values = [
            3_779_932.2101,
            3_787_683.9930,
            3_993_785.7629,
        ]

        random.seed(20260911)

        result = _simulate_metric(
            values=values,
            months_ahead=4,
            n_simulations=1000,
            actual_total=27_993_983.08,
            distribution_type="normal",
            sma_window=3,
        )

        rows = result["projection_rows"]
        actual = [row["p50"] for row in rows]

        expected = [
            3_853_800.655333333,
            3_878_423.470411111,
            3_908_669.962881481,
            3_880_298.029541975,
        ]

        self.assertEqual(len(actual), 4)

        for got, want in zip(actual, expected):
            self.assertAlmostEqual(got, want, places=3)

        self.assertGreater(len(set(round(x, 3) for x in actual)), 1)

        self.assertAlmostEqual(
            result["future_mean_total"],
            sum(expected),
            places=3,
        )
        self.assertAlmostEqual(
            result["full_year_expected"],
            27_993_983.08 + sum(expected),
            places=3,
        )

        self.assertEqual(
            result["descriptive_stats"]["forecast_method"],
            "rolling_sma_recursive_baseline",
        )
        self.assertTrue(
            all(row["source"] == "history_rolling_sma" for row in rows)
        )

    def test_first_month_equals_legacy_sma3(self):
        values = [100.0, 120.0, 150.0, 180.0]

        random.seed(123)

        result = _simulate_metric(
            values=values,
            months_ahead=3,
            n_simulations=1000,
            sma_window=3,
        )

        first = result["projection_rows"][0]["p50"]
        self.assertAlmostEqual(first, (120.0 + 150.0 + 180.0) / 3.0)

    def test_annual_percentiles_come_from_total_distribution(self):
        random.seed(456)

        result = _simulate_metric(
            values=[100.0, 110.0, 120.0, 130.0],
            months_ahead=4,
            n_simulations=2000,
            actual_total=460.0,
            sma_window=3,
        )

        self.assertLessEqual(result["p5_total"], result["p50_total"])
        self.assertLessEqual(result["p50_total"], result["p95_total"])
        self.assertEqual(len(result["simulation_totals"]), 2000)
