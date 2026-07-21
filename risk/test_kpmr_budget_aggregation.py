from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from risk.services.kpmr_automation import _aggregate_budget_absorption


class KPMRBudgetAggregationTest(SimpleTestCase):
    def _item(self, budget, actual):
        return SimpleNamespace(
            risk_event=SimpleNamespace(biaya_perlakuan_risiko=budget),
            realisasi_biaya_perlakuan=actual,
        )

    def test_uses_total_actual_divided_by_total_budget_not_average_percentages(self):
        result = _aggregate_budget_absorption([
            self._item(Decimal("100"), Decimal("100")),
            self._item(Decimal("900"), Decimal("0")),
        ])
        self.assertEqual(result["total_budget"], Decimal("1000"))
        self.assertEqual(result["total_actual"], Decimal("100"))
        self.assertEqual(result["ratio"], Decimal("10"))
        self.assertFalse(result["is_over_budget"])

    def test_actual_without_budget_is_flagged_over_budget(self):
        result = _aggregate_budget_absorption([
            self._item(Decimal("1000"), Decimal("100")),
            self._item(None, Decimal("1")),
        ])
        self.assertEqual(result["unbudgeted_actual"], Decimal("1"))
        self.assertTrue(result["is_over_budget"])
class KPMRZeroCostBudgetAggregationV2Test(KPMRBudgetAggregationTest):
    def test_zero_cost_declared_budget_is_valid_and_within_budget(self):
        result = _aggregate_budget_absorption([
            self._item(Decimal("0"), Decimal("0")),
            self._item(Decimal("0"), Decimal("0")),
        ])
        self.assertIsNotNone(result)
        self.assertTrue(result["is_zero_cost"])
        self.assertEqual(result["ratio"], Decimal("0"))
        self.assertFalse(result["is_over_budget"])

    def test_zero_cost_with_actual_spend_is_over_budget(self):
        result = _aggregate_budget_absorption([
            self._item(Decimal("0"), Decimal("1")),
        ])
        self.assertIsNotNone(result)
        self.assertTrue(result["is_zero_cost"])
        self.assertTrue(result["is_over_budget"])
