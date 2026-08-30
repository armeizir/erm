from decimal import Decimal

from django.test import SimpleTestCase

from risk.strategy_risk_map import (
    _enrich_kpi_rows,
    _format_number_id,
    _kpi_performance_status,
    _next_month_label,
)


class StrategyRiskMapKPIPerformanceTests(SimpleTestCase):
    def test_indonesian_number_format(self):
        self.assertEqual(
            _format_number_id(Decimal("4430.99")),
            "4.430,99",
        )

    def test_kpi_status_thresholds(self):
        self.assertEqual(
            _kpi_performance_status(
                Decimal("110"),
            )["label"],
            "Tercapai",
        )
        self.assertEqual(
            _kpi_performance_status(
                Decimal("95.49"),
            )["label"],
            "Hampir Tercapai",
        )
        self.assertEqual(
            _kpi_performance_status(
                Decimal("94.99"),
            )["label"],
            "Perlu Peningkatan",
        )

    def test_compliance_is_not_percentage_status(self):
        status = _kpi_performance_status(
            None,
            is_deduction=True,
        )

        self.assertEqual(
            status["label"],
            "Nilai Pengurang",
        )

    def test_next_month_crosses_year_boundary(self):
        self.assertEqual(
            _next_month_label(2026, 12),
            "Januari 2027",
        )

    def test_enrich_kpi_rows_keeps_relationship(self):
        kpis = [
            {
                "id": 101,
                "no": 1,
                "name": "EBIT",
                "esg": "C",
            }
        ]

        performance = {
            101: {
                "available": True,
                "target_display": "541,34",
            }
        }

        result = _enrich_kpi_rows(
            kpis,
            performance,
            2026,
            7,
        )

        self.assertEqual(
            result[0]["name"],
            "EBIT",
        )
        self.assertEqual(
            result[0]["performance"]["target_display"],
            "541,34",
        )
