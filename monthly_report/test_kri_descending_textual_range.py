from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from monthly_report.kri_services import (
    _matches,
    evaluate_kri_threshold,
)


class KRIDescendingTextualRangeTests(SimpleTestCase):
    def test_strada_green_descending_range(self):
        expression = "0 s.d. -10"
        unit = "Nilai / Skor"

        self.assertTrue(_matches(expression, Decimal("0"), unit))
        self.assertTrue(_matches(expression, Decimal("-5"), unit))
        self.assertTrue(_matches(expression, Decimal("-10"), unit))
        self.assertFalse(_matches(expression, Decimal("1"), unit))
        self.assertFalse(_matches(expression, Decimal("-10.01"), unit))

    def test_strada_yellow_descending_range(self):
        expression = "< -10 s.d. -15"
        unit = "Nilai / Skor"

        self.assertFalse(_matches(expression, Decimal("-10"), unit))
        self.assertTrue(_matches(expression, Decimal("-10.01"), unit))
        self.assertTrue(_matches(expression, Decimal("-12"), unit))
        self.assertTrue(_matches(expression, Decimal("-15"), unit))
        self.assertFalse(_matches(expression, Decimal("-15.01"), unit))

    def test_keu_descending_range(self):
        expression = "<100 s.d 90"

        self.assertTrue(_matches(expression, Decimal("90"), "%"))
        self.assertTrue(_matches(expression, Decimal("95"), "%"))
        self.assertFalse(_matches(expression, Decimal("100"), "%"))
        self.assertFalse(_matches(expression, Decimal("89"), "%"))

    def test_ascending_range_with_endpoint_operators(self):
        self.assertTrue(
            _matches(">=90 s.d <100", Decimal("90"), "%")
        )
        self.assertTrue(
            _matches(">=90 s.d <100", Decimal("95"), "%")
        )
        self.assertFalse(
            _matches(">=90 s.d <100", Decimal("100"), "%")
        )

        self.assertFalse(
            _matches(">45 s.d <=50", Decimal("45"), "%")
        )
        self.assertTrue(
            _matches(">45 s.d <=50", Decimal("46"), "%")
        )
        self.assertTrue(
            _matches(">45 s.d <=50", Decimal("50"), "%")
        )

    def test_old_signed_hyphen_range_still_works(self):
        self.assertTrue(
            _matches("-5--1.0001", Decimal("-3"), "")
        )
        self.assertFalse(
            _matches("-5--1.0001", Decimal("-6"), "")
        )

    def test_single_negative_boundary_still_works(self):
        self.assertTrue(_matches(">=-1", Decimal("0"), ""))
        self.assertTrue(_matches(">=-1", Decimal("-1"), ""))
        self.assertFalse(_matches(">=-1", Decimal("-2"), ""))

        self.assertTrue(_matches("<-5", Decimal("-6"), ""))
        self.assertFalse(_matches("<-5", Decimal("-5"), ""))

    def test_indonesian_thousands_regression(self):
        self.assertTrue(
            _matches(">203.582", Decimal("204000"), "kVA")
        )
        self.assertFalse(
            _matches(">203.582", Decimal("145306"), "kVA")
        )

    def test_strada_complete_threshold_evaluation(self):
        risk = SimpleNamespace(
            kri_threshold_direction="lower_better",
            unit_satuan_kri="Nilai / Skor",
            threshold_aman="0 s.d. -10",
            threshold_hati_hati="< -10 s.d. -15",
            threshold_bahaya="< -15",
        )

        expected = {
            Decimal("0"): "green",
            Decimal("-5"): "green",
            Decimal("-10"): "green",
            Decimal("-12"): "yellow",
            Decimal("-15"): "yellow",
            Decimal("-16"): "red",
        }

        for value, status in expected.items():
            with self.subTest(value=value):
                result = evaluate_kri_threshold(risk, value)
                self.assertEqual(result.status, status)
