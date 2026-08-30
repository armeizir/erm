from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from risk.km_scoring import (
    calculate_km_score,
    compliance_deduction,
    truncate_two,
    weighted_score,
)


def item(*, no, bobot, polaritas="positif", corporate=False):
    unit = SimpleNamespace(
        name="KORPORAT" if corporate else "BID TEST"
    )
    kontrak = SimpleNamespace(unit_bisnis=unit)

    return SimpleNamespace(
        no_urut=no,
        bobot=Decimal(str(bobot)),
        polaritas=polaritas,
        kontrak=kontrak,
    )


class KMScoringTests(SimpleTestCase):

    def test_legacy_unit_positive_formula_is_unchanged(self):
        km_item = item(
            no=1,
            bobot=10,
            polaritas="positif",
            corporate=False,
        )

        achievement, score = calculate_km_score(
            km_item,
            Decimal("80"),
            Decimal("81"),
        )

        self.assertEqual(
            achievement.quantize(Decimal("0.01")),
            Decimal("101.25"),
        )
        self.assertEqual(
            score,
            Decimal("10.1250"),
        )

    def test_legacy_unit_negative_formula_is_unchanged(self):
        km_item = item(
            no=1,
            bobot=10,
            polaritas="negatif",
            corporate=False,
        )

        achievement, _score = calculate_km_score(
            km_item,
            Decimal("80"),
            Decimal("100"),
        )

        self.assertEqual(
            achievement,
            Decimal("80"),
        )

    def test_corporate_positive_is_capped_at_110(self):
        km_item = item(
            no=1,
            bobot=12,
            corporate=True,
        )

        achievement, score = calculate_km_score(
            km_item,
            Decimal("541.34"),
            Decimal("702.74"),
        )

        self.assertEqual(achievement, Decimal("110"))
        self.assertEqual(score, Decimal("13.20"))

    def test_electricity_losses_uses_inverse_deviation(self):
        km_item = item(
            no=7,
            bobot=10,
            polaritas="negatif",
            corporate=True,
        )

        achievement, score = calculate_km_score(
            km_item,
            Decimal("3.35"),
            Decimal("3.38"),
        )

        self.assertEqual(
            achievement.quantize(Decimal("0.01")),
            Decimal("99.10"),
        )
        self.assertEqual(score, Decimal("9.91"))

    def test_compliance_is_direct_deduction(self):
        km_item = item(
            no=10,
            bobot=0,
            polaritas="negatif",
            corporate=True,
        )

        achievement, score = calculate_km_score(
            km_item,
            None,
            Decimal("3"),
        )

        self.assertIsNone(achievement)
        self.assertEqual(score, Decimal("-3.00"))
        self.assertEqual(
            compliance_deduction(Decimal("-12")),
            Decimal("-10.00"),
        )

    def test_corporate_weighted_values_match_july_nko(self):
        # Pencapaian resmi Juli 2026.
        rows = [
            (12, "110.00"),
            (12, "94.70"),
            (10, "95.49"),
            (16, "107.15"),
            (10, "104.38"),
            (10, "110.00"),
            (10, "99.10"),
            (10, "96.49"),
            (10, "106.69"),
        ]

        scores = [
            weighted_score(
                Decimal(str(weight)),
                Decimal(achievement),
                truncate=True,
            )
            for weight, achievement in rows
        ]

        self.assertEqual(
            scores,
            [
                Decimal("13.20"),
                Decimal("11.36"),
                Decimal("9.54"),
                Decimal("17.14"),
                Decimal("10.43"),
                Decimal("11.00"),
                Decimal("9.91"),
                Decimal("9.64"),
                Decimal("10.66"),
            ],
        )

        self.assertEqual(
            sum(scores, Decimal("0")),
            Decimal("102.88"),
        )

    def test_truncate_is_not_rounding(self):
        self.assertEqual(
            truncate_two(Decimal("9.649")),
            Decimal("9.64"),
        )


class KMScoringBoundaryTests(SimpleTestCase):

    def test_corporate_positive_has_zero_floor(self):
        km_item = item(
            no=1,
            bobot=12,
            corporate=True,
        )

        achievement, score = calculate_km_score(
            km_item,
            Decimal("100"),
            Decimal("-20"),
        )

        self.assertEqual(achievement, Decimal("0"))
        self.assertEqual(score, Decimal("0.00"))

    def test_corporate_inverse_has_zero_floor(self):
        km_item = item(
            no=7,
            bobot=10,
            polaritas="negatif",
            corporate=True,
        )

        achievement, score = calculate_km_score(
            km_item,
            Decimal("3"),
            Decimal("9"),
        )

        self.assertEqual(achievement, Decimal("0"))
        self.assertEqual(score, Decimal("0.00"))
