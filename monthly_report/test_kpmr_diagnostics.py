from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from risk.services.kpmr_aggregation import (
    _aggregate_exposure_for_i1,
    normalize_no_item,
)
from risk.services.kpmr_diagnostics import build_kpmr_diagnostics


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
