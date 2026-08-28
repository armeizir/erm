from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from risk.services.risk_exposure import assign_item_quarterly_exposures


class QualitativeExposureServiceTests(SimpleTestCase):
    def test_quantitative_exposure_is_calculated(self):
        item = SimpleNamespace(
            jenis_risiko="kuantitatif",
            nilai_dampak_q1=Decimal("1000"),
            nilai_probabilitas_q1=Decimal("25"),
            nilai_dampak_q2=None,
            nilai_probabilitas_q2=None,
            nilai_dampak_q3=None,
            nilai_probabilitas_q3=None,
            nilai_dampak_q4=None,
            nilai_probabilitas_q4=None,
            eksposur_risiko_q1=None,
            eksposur_risiko_q2=None,
            eksposur_risiko_q3=None,
            eksposur_risiko_q4=None,
        )
        assign_item_quarterly_exposures(item)
        self.assertEqual(item.eksposur_risiko_q1, Decimal("250.00"))

    def test_qualitative_manual_exposure_is_preserved(self):
        item = SimpleNamespace(
            jenis_risiko="kualitatif",
            nilai_dampak_q1=None,
            nilai_probabilitas_q1=None,
            nilai_dampak_q2=None,
            nilai_probabilitas_q2=None,
            nilai_dampak_q3=None,
            nilai_probabilitas_q3=None,
            nilai_dampak_q4=None,
            nilai_probabilitas_q4=None,
            eksposur_risiko_q1=Decimal("417340650"),
            eksposur_risiko_q2=None,
            eksposur_risiko_q3=None,
            eksposur_risiko_q4=None,
        )
        assign_item_quarterly_exposures(item)
        self.assertEqual(item.eksposur_risiko_q1, Decimal("417340650"))
