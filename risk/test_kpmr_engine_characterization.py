from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from risk.services import kpmr_automation as facade
from risk.services.kpmr_aggregation import (
    _aggregate_budget_absorption,
    _aggregate_exposure_for_i1,
)
from risk.services.kpmr_scoring import (
    _score_budget_absorption,
    _score_output_progress,
    rating_for_score,
)


class KPMREngineCharacterizationTests(SimpleTestCase):
    def test_facade_keeps_legacy_import_surface(self):
        self.assertIs(facade._aggregate_exposure_for_i1, _aggregate_exposure_for_i1)
        self.assertIs(facade._aggregate_budget_absorption, _aggregate_budget_absorption)
        self.assertIs(facade.rating_for_score, rating_for_score)

    def test_rating_boundaries_are_unchanged(self):
        cases = [
            (Decimal("90.01"), "STRONG"),
            (Decimal("90.00"), "SATISFACTORY"),
            (Decimal("85.00"), "SATISFACTORY"),
            (Decimal("84.00"), "FAIR"),
            (Decimal("80.00"), "FAIR"),
            (Decimal("79.00"), "MARGINAL"),
            (Decimal("75.00"), "MARGINAL"),
            (Decimal("74.99"), "UNSATISFACTORY"),
        ]
        for score, expected in cases:
            with self.subTest(score=score):
                self.assertEqual(rating_for_score(score), expected)

    def test_i2_progress_scoring_boundaries_are_unchanged(self):
        cases = [
            (None, None),
            (Decimal("90"), Decimal("100")),
            (Decimal("89.99"), Decimal("80")),
            (Decimal("80"), Decimal("80")),
            (Decimal("79.99"), Decimal("60")),
            (Decimal("70"), Decimal("60")),
            (Decimal("69.99"), Decimal("40")),
            (Decimal("60"), Decimal("40")),
            (Decimal("59.99"), Decimal("20")),
        ]
        for progress, expected in cases:
            with self.subTest(progress=progress):
                raw, _ = _score_output_progress(progress)
                self.assertEqual(raw, expected)

    def test_i3_budget_scoring_boundaries_are_unchanged(self):
        cases = [
            (None, None),
            (Decimal("0"), Decimal("80")),
            (Decimal("100"), Decimal("80")),
            (Decimal("100.01"), Decimal("40")),
        ]
        for absorption, expected in cases:
            with self.subTest(absorption=absorption):
                raw, _ = _score_budget_absorption(absorption)
                self.assertEqual(raw, expected)

    def test_i1_deduplication_behavior_is_unchanged(self):
        def item(no_item, target, residual, pk):
            return SimpleNamespace(
                risk_event=SimpleNamespace(
                    no_item=no_item,
                    pk=pk,
                    eksposur_risiko_q2=target,
                ),
                realisasi_eksposur=residual,
            )

        result = _aggregate_exposure_for_i1(
            [
                item(1, Decimal("100"), Decimal("80"), 1),
                item(1, Decimal("100"), Decimal("80"), 2),
                item(2, Decimal("200"), Decimal("180"), 3),
            ],
            2,
        )
        self.assertEqual(result["group_count"], 2)
        self.assertEqual(result["total_target"], Decimal("300"))
        self.assertEqual(result["total_residual"], Decimal("260"))
        self.assertEqual(result["incomplete_group_count"], 0)

    def test_i3_aggregate_budget_behavior_is_unchanged(self):
        def item(budget, actual):
            return SimpleNamespace(
                risk_event=SimpleNamespace(biaya_perlakuan_risiko=budget),
                realisasi_biaya_perlakuan=actual,
            )

        result = _aggregate_budget_absorption(
            [
                item(Decimal("100"), Decimal("100")),
                item(Decimal("900"), Decimal("0")),
            ]
        )
        self.assertEqual(result["total_budget"], Decimal("1000"))
        self.assertEqual(result["total_actual"], Decimal("100"))
        self.assertEqual(result["ratio"], Decimal("10"))
        self.assertFalse(result["is_over_budget"])
