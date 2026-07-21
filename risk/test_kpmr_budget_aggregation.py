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

from risk.services.kpmr_automation import _aggregate_exposure_for_i1


class KPMRExposureAggregationTest(SimpleTestCase):
    def _item(self, no_item, target, residual, pk):
        return SimpleNamespace(
            risk_event=SimpleNamespace(
                no_item=no_item,
                pk=pk,
                eksposur_risiko_q2=target,
            ),
            realisasi_eksposur=residual,
        )

    def test_deduplicates_multiple_treatments_in_same_top_risk(self):
        result = _aggregate_exposure_for_i1(
            [
                self._item(1, Decimal("100"), Decimal("80"), 1),
                self._item(1, Decimal("100"), Decimal("80"), 2),
                self._item(2, Decimal("200"), Decimal("180"), 3),
            ],
            2,
        )
        self.assertEqual(result["group_count"], 2)
        self.assertEqual(result["total_target"], Decimal("300"))
        self.assertEqual(result["total_residual"], Decimal("260"))
        self.assertEqual(result["incomplete_group_count"], 0)
        self.assertEqual(result["conflicts"], [])

    def test_detects_conflicting_exposure_inside_same_top_risk(self):
        result = _aggregate_exposure_for_i1(
            [
                self._item(1, Decimal("100"), Decimal("80"), 1),
                self._item(1, Decimal("110"), Decimal("80"), 2),
            ],
            2,
        )
        self.assertEqual(len(result["conflicts"]), 1)
