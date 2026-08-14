from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from risk.services.kpmr_i1 import (
    _aggregate_hybrid_i1,
    calculate_i1,
)


def make_item(
    *,
    no_item,
    kind,
    target_exposure=None,
    actual_exposure=None,
    target_impact=None,
    target_probability=None,
    actual_impact=None,
    actual_probability=None,
    target_score=None,
    actual_score=None,
    pk=1,
):
    risk_event = SimpleNamespace(
        pk=pk,
        no_item=no_item,
        eksposur_risiko_q3=target_exposure,
        nilai_dampak_q3=target_impact,
        nilai_probabilitas_q3=target_probability,
        skala_risiko_q3=target_score,
    )
    return SimpleNamespace(
        pk=pk,
        jenis_risiko=kind,
        risk_event=risk_event,
        risk_event_id=pk,
        target_residual_level=None,
        realisasi_eksposur=actual_exposure,
        realisasi_nilai_dampak=actual_impact,
        realisasi_nilai_probabilitas=actual_probability,
        realisasi_skor_risiko=actual_score,
        residual_level=None,
    )


class KPMRI1HybridTests(SimpleTestCase):
    def test_qualitative_uses_matrix_score(self):
        item = make_item(
            no_item=1,
            kind="kualitatif",
            target_score=8,
            actual_score=6,
        )
        summary = _aggregate_hybrid_i1([item], 3)
        self.assertEqual(summary["qualitative_count"], 1)
        self.assertEqual(summary["below_target"], 1)
        self.assertEqual(summary["incomplete_group_count"], 0)

    def test_quantitative_can_derive_exposure(self):
        item = make_item(
            no_item=1,
            kind="kuantitatif",
            target_impact=Decimal("1000"),
            target_probability=Decimal("0.20"),
            actual_impact=Decimal("1000"),
            actual_probability=Decimal("10"),
        )
        summary = _aggregate_hybrid_i1([item], 3)
        row = summary["groups"][0]
        self.assertEqual(row["target"], Decimal("200.00"))
        self.assertEqual(row["actual"], Decimal("100"))
        self.assertEqual(row["comparison"], "below")

    def test_qualitative_multi_cause_uses_worst_case(self):
        items = [
            make_item(
                no_item=13,
                kind="kualitatif",
                target_score=6,
                actual_score=5,
                pk=1,
            ),
            make_item(
                no_item=13,
                kind="kualitatif",
                target_score=8,
                actual_score=9,
                pk=2,
            ),
        ]
        summary = _aggregate_hybrid_i1(items, 3)
        row = summary["groups"][0]
        self.assertEqual(row["target"], Decimal("8"))
        self.assertEqual(row["actual"], Decimal("9"))
        self.assertEqual(row["comparison"], "above")
        self.assertEqual(summary["group_count"], 1)

    def test_mixed_hybrid_keeps_existing_90_60_40_policy(self):
        items = [
            make_item(
                no_item=1,
                kind="kuantitatif",
                target_exposure=Decimal("100"),
                actual_exposure=Decimal("80"),
                pk=1,
            ),
            make_item(
                no_item=2,
                kind="kualitatif",
                target_score=8,
                actual_score=8,
                pk=2,
            ),
        ]
        raw, option, _, _ = calculate_i1(
            report_items=items,
            quarter=3,
            unit=SimpleNamespace(name="TEST"),
            year=2026,
            reports=[],
            comparable=[],
            above_target=0,
            same_target=0,
            below_target=0,
            notes=[],
        )
        self.assertEqual(raw, Decimal("60"))
        self.assertEqual(option, "b")

    def test_pure_quantitative_preserves_legacy_total_exposure_method(self):
        items = [
            make_item(
                no_item=1,
                kind="kuantitatif",
                target_exposure=Decimal("100"),
                actual_exposure=Decimal("150"),
                pk=1,
            ),
            make_item(
                no_item=2,
                kind="kuantitatif",
                target_exposure=Decimal("1000"),
                actual_exposure=Decimal("100"),
                pk=2,
            ),
        ]
        raw, option, _, _ = calculate_i1(
            report_items=items,
            quarter=3,
            unit=SimpleNamespace(name="TEST"),
            year=2026,
            reports=[],
            comparable=[],
            above_target=0,
            same_target=0,
            below_target=0,
            notes=[],
        )
        self.assertEqual(raw, Decimal("90"))
        self.assertEqual(option, "a")

    def test_incomplete_group_returns_none(self):
        item = make_item(
            no_item=1,
            kind="kualitatif",
            target_score=8,
            actual_score=None,
        )
        raw, option, _, detail = calculate_i1(
            report_items=[item],
            quarter=3,
            unit=SimpleNamespace(name="TEST"),
            year=2026,
            reports=[],
            comparable=[],
            above_target=0,
            same_target=0,
            below_target=0,
            notes=[],
        )
        self.assertIsNone(raw)
        self.assertEqual(option, "")
        self.assertIn("belum semua top-risk", detail)
