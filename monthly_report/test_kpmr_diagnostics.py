from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from risk.services.kpmr_aggregation import (
    _aggregate_exposure_for_i1,
    normalize_no_item,
)
from risk.services.kpmr_diagnostics import build_kpmr_diagnostics
from risk.services.kpmr_assembly import finalize_kpmr_result


@dataclass(frozen=True)
class FakeScale:
    pk: int
    urutan: int
    label: str

    def __str__(self):
        return self.label


class FakeMatrix:
    pk = 99

    def get_cell(self, impact, likelihood):
        if impact is None or likelihood is None:
            return None
        return SimpleNamespace(skor=impact.urutan * likelihood.urutan)

    def __str__(self):
        return "MATRIX-TEST"


class KPMRDiagnosticsTests(SimpleTestCase):
    def _item(
        self,
        *,
        pk=1,
        no_item=1,
        no_risiko=1,
        target_impact=3,
        target_likelihood=3,
        actual_impact=3,
        actual_likelihood=3,
        target_exposure=Decimal("100"),
        actual_exposure=Decimal("90"),
    ):
        matrix = FakeMatrix()

        def scale(rank, pk_offset):
            return None if rank is None else FakeScale(pk_offset + rank, rank, f"S{rank}")

        risk = SimpleNamespace(
            pk=pk + 100,
            no_item=no_item,
            no_risiko=no_risiko,
            peristiwa_risiko=f"Risiko {no_risiko}",
            summary=SimpleNamespace(risk_matrix=matrix, risk_matrix_id=matrix.pk),
            skala_dampak_q1=scale(target_impact, 1000),
            skala_probabilitas_q1=scale(target_likelihood, 2000),
            eksposur_risiko_q1=target_exposure,
        )
        return SimpleNamespace(
            pk=pk,
            risk_event=risk,
            target_residual_level=1,
            realisasi_skala_dampak=scale(actual_impact, 9000),
            realisasi_skala_probabilitas=scale(actual_likelihood, 8000),
            realisasi_skor_risiko=25,
            realisasi_eksposur=actual_exposure,
        )

    def _diagnostics(self, items):
        report = SimpleNamespace()
        return build_kpmr_diagnostics(report, report_items=items, quarter=1)

    def test_complete_target_and_actual_are_compared_from_matrix_scores(self):
        row = self._diagnostics([self._item()])["rows"][0]

        self.assertTrue(row["is_complete"])
        self.assertEqual(row["target_score"], 9)
        self.assertEqual(row["actual_score"], 9)

    def test_actual_below_target(self):
        row = self._diagnostics([
            self._item(target_impact=4, target_likelihood=4, actual_impact=2, actual_likelihood=3)
        ])["rows"][0]

        self.assertEqual(row["comparison"], "below")

    def test_actual_same_as_target(self):
        row = self._diagnostics([self._item()])["rows"][0]

        self.assertEqual(row["comparison"], "same")

    def test_actual_above_target(self):
        row = self._diagnostics([
            self._item(target_impact=2, target_likelihood=2, actual_impact=4, actual_likelihood=3)
        ])["rows"][0]

        self.assertEqual(row["comparison"], "above")

    def test_missing_target_is_incomplete_not_above(self):
        row = self._diagnostics([
            self._item(target_impact=None, target_likelihood=None)
        ])["rows"][0]

        self.assertEqual(row["comparison"], "incomplete")
        self.assertIn("target score/matrix cell", row["missing"])

    def test_missing_actual_is_incomplete(self):
        row = self._diagnostics([
            self._item(actual_impact=None, actual_likelihood=None)
        ])["rows"][0]

        self.assertEqual(row["comparison"], "incomplete")
        self.assertIn("aktual score/matrix cell", row["missing"])

    def test_comparison_does_not_use_database_ids_or_legacy_scalars(self):
        item = self._item(
            target_impact=4,
            target_likelihood=4,
            actual_impact=2,
            actual_likelihood=2,
        )
        item.target_residual_level = 1
        item.realisasi_skor_risiko = 25

        row = self._diagnostics([item])["rows"][0]

        self.assertEqual(row["comparison"], "below")
        self.assertEqual(row["target_score"], 16)
        self.assertEqual(row["actual_score"], 4)

    def test_no_item_normalization_handles_number_string_space_and_leading_zero(self):
        self.assertEqual(normalize_no_item(9), "9")
        self.assertEqual(normalize_no_item("9"), "9")
        self.assertEqual(normalize_no_item(" 009 "), "9")

    def test_complete_groups_and_missing_exposure_are_counted_correctly(self):
        complete = self._item(pk=1, no_item=" 01 ")
        same_group = self._item(pk=2, no_item=1)
        incomplete = self._item(
            pk=3, no_item="2", target_exposure=None, actual_exposure=None
        )

        result = _aggregate_exposure_for_i1([complete, same_group, incomplete], 1)

        self.assertEqual(result["group_count"], 2)
        self.assertEqual(result["comparable_group_count"], 1)
        self.assertEqual(result["incomplete_group_count"], 1)

    def test_diagnostic_rows_do_not_duplicate_report_items(self):
        item = self._item()

        diagnostics = self._diagnostics([item, item])

        self.assertEqual(len(diagnostics["rows"]), 1)

    def test_unassessed_required_indicator_is_not_treated_as_zero_final_score(self):
        indicators = [
            {"kode": "I1", "hasil": None, "skor": Decimal("0"), "bobot": Decimal("30")},
            {"kode": "I2", "hasil": 100, "skor": Decimal("20"), "bobot": Decimal("20")},
            {"kode": "I3", "hasil": 80, "skor": Decimal("16"), "bobot": Decimal("20")},
            {"kode": "I4", "hasil": 80, "skor": Decimal("24"), "bobot": Decimal("30")},
        ]

        result = finalize_kpmr_result(
            year=2026, quarter=3, unit=SimpleNamespace(), report_count=1,
            item_count=22, indicators=indicators, notes=[], month=7,
            diagnostics={"needs_verification": True},
        )

        self.assertFalse(result.is_complete)
        self.assertTrue(result.requires_verification)
        self.assertEqual(result.provisional_score, Decimal("60.00"))
        self.assertEqual(result.assessed_weight, Decimal("70.00"))
        self.assertEqual(result.unassessed_weight, Decimal("30.00"))
        self.assertIsNone(result.final_score)
        self.assertIsNone(result.final_rating)
        self.assertEqual(result.normalized_indicative_score, Decimal("85.71"))

    def test_complete_kpmr_has_final_score_and_rating(self):
        indicators = [
            {"kode": code, "hasil": 90, "skor": score, "bobot": weight}
            for code, score, weight in (
                ("I1", Decimal("27"), Decimal("30")),
                ("I2", Decimal("20"), Decimal("20")),
                ("I3", Decimal("16"), Decimal("20")),
                ("I4", Decimal("27"), Decimal("30")),
            )
        ]

        result = finalize_kpmr_result(
            year=2026, quarter=3, unit=SimpleNamespace(), report_count=1,
            item_count=22, indicators=indicators, notes=[], month=7,
        )

        self.assertTrue(result.is_complete)
        self.assertFalse(result.requires_verification)
        self.assertEqual(result.final_score, Decimal("90.00"))
        self.assertEqual(result.final_rating, "SATISFACTORY")
        self.assertIsNone(result.normalized_indicative_score)

    def test_incomplete_exposure_group_has_explicit_reason_and_sources(self):
        diagnostics = self._diagnostics([
            self._item(target_exposure=None, actual_exposure=None)
        ])

        group = diagnostics["exposure_groups"][0]
        self.assertFalse(group["is_complete"])
        self.assertFalse(group["assessable"])
        self.assertIn("target", group["missing"])
        self.assertIn("residual", group["missing"])
        self.assertIn("ReAssessmentItem.eksposur_risiko_q1", group["reason"])
        self.assertIn("MonthlyRiskReportItem.realisasi_eksposur", group["reason"])
