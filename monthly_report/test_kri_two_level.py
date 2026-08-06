from decimal import Decimal
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .kri_services import evaluate_kri_threshold


def make_risk(*, green, yellow, red, unit=""):
    return SimpleNamespace(
        key_risk_indicators="KRI pengujian",
        unit_satuan_kri=unit,
        kri_threshold_direction="higher_better",
        threshold_aman=green,
        threshold_hati_hati=yellow,
        threshold_bahaya=red,
    )


class KRITwoLevelThresholdTest(SimpleTestCase):
    def test_binary_one_is_green(self):
        risk = make_risk(
            green="Ada",
            yellow="Tidak",
            red="Tidak",
            unit="Ada/Tidak",
        )

        result = evaluate_kri_threshold(
            risk,
            Decimal("1"),
        )

        self.assertEqual(result.status, "green")
        self.assertEqual(result.threshold_range, "Ada")

    def test_binary_zero_is_red(self):
        risk = make_risk(
            green="Ada",
            yellow="Tidak",
            red="Tidak",
            unit="Ada/Tidak",
        )

        result = evaluate_kri_threshold(
            risk,
            Decimal("0"),
        )

        self.assertEqual(result.status, "red")
        self.assertEqual(result.threshold_range, "Tidak")

    def test_percentage_100_is_green(self):
        risk = make_risk(
            green="100%",
            yellow="<100%",
            red="<100%",
            unit="%",
        )

        result = evaluate_kri_threshold(
            risk,
            Decimal("100"),
        )

        self.assertEqual(result.status, "green")
        self.assertEqual(result.threshold_range, "100%")

    def test_percentage_below_100_is_red(self):
        risk = make_risk(
            green="100%",
            yellow="<100%",
            red="<100%",
            unit="%",
        )

        result = evaluate_kri_threshold(
            risk,
            Decimal("99"),
        )

        self.assertEqual(result.status, "red")
        self.assertEqual(result.threshold_range, "<100%")

    def test_different_overlapping_ranges_remain_invalid(self):
        risk = make_risk(
            green=">90%",
            yellow="80%-95%",
            red="<80%",
            unit="%",
        )

        with self.assertRaisesMessage(
            ValidationError,
            "tumpang tindih",
        ):
            evaluate_kri_threshold(
                risk,
                Decimal("92"),
            )
