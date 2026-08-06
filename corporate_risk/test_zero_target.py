from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from corporate_risk.models import RiskMetric


class RiskMetricZeroTargetTests(SimpleTestCase):
    def test_zero_target_is_valid(self):
        metric = RiskMetric(target_value=Decimal("0"))

        metric.clean()

        self.assertEqual(
            metric.effective_target_value,
            Decimal("0"),
        )

    def test_negative_target_is_rejected(self):
        metric = RiskMetric(target_value=Decimal("-1"))

        with self.assertRaises(ValidationError) as context:
            metric.clean()

        self.assertIn(
            "Target RKAP tidak boleh lebih kecil dari 0",
            str(context.exception),
        )

    def test_positive_target_remains_valid(self):
        metric = RiskMetric(target_value=Decimal("100"))

        metric.clean()

        self.assertEqual(
            metric.effective_target_value,
            Decimal("100"),
        )
