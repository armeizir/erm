from decimal import Decimal

from django.test import SimpleTestCase

from monthly_report.kri_services import _matches


class KRISignedRangeTests(SimpleTestCase):
    def test_negative_range_is_parsed_correctly(self):
        expr = "-5--1.0001"
        self.assertFalse(_matches(expr, Decimal("-6")))
        self.assertTrue(_matches(expr, Decimal("-5")))
        self.assertTrue(_matches(expr, Decimal("-4")))
        self.assertTrue(_matches(expr, Decimal("-1.0001")))
        self.assertFalse(_matches(expr, Decimal("-1")))
        self.assertFalse(_matches(expr, Decimal("0")))

    def test_negative_range_with_spaces_is_supported(self):
        expr = "-5 - -1.0001"
        self.assertTrue(_matches(expr, Decimal("-3")))
        self.assertFalse(_matches(expr, Decimal("-6")))

    def test_positive_range_remains_supported(self):
        self.assertTrue(_matches("99-99.9999", Decimal("99")))
        self.assertTrue(_matches("99-99.9999", Decimal("99.5")))
        self.assertFalse(_matches("99-99.9999", Decimal("100")))

    def test_single_boundaries_still_work_with_negative_numbers(self):
        self.assertTrue(_matches(">=-1", Decimal("0")))
        self.assertTrue(_matches(">=-1", Decimal("-1")))
        self.assertFalse(_matches(">=-1", Decimal("-2")))
        self.assertTrue(_matches("<-5", Decimal("-6")))
        self.assertFalse(_matches("<-5", Decimal("-5")))

    def test_plain_numeric_threshold_still_means_equal(self):
        self.assertTrue(_matches("100%", Decimal("100")))
        self.assertFalse(_matches("100%", Decimal("99")))
