# BOD_EXECUTIVE_DASHBOARD_PHASE2 tests
from django.test import SimpleTestCase

from risk.bod_phase2 import classify_kri, classify_level, is_complete, is_overdue


class BoDPhase2SignalTests(SimpleTestCase):
    def test_kri_classification(self):
        self.assertEqual(classify_kri("Hijau"), "green")
        self.assertEqual(classify_kri("Hati-Hati"), "yellow")
        self.assertEqual(classify_kri("Bahaya"), "red")
        self.assertEqual(classify_kri("Merah"), "red")

    def test_risk_level_classification(self):
        self.assertEqual(classify_level("High", 20), "high")
        self.assertEqual(classify_level("Moderate to High", 18), "moderate_high")
        self.assertEqual(classify_level("", 20), "high")
        self.assertEqual(classify_level("", 13), "moderate")

    def test_mitigation_status(self):
        self.assertTrue(is_overdue("Terlambat"))
        self.assertTrue(is_overdue("Overdue"))
        self.assertTrue(is_complete("Selesai", None))
        self.assertTrue(is_complete("", 100))
        self.assertFalse(is_complete("", 75))



class BoDPhase3V3SmokeTests(SimpleTestCase):
    def test_phase3_v3_api_callable(self):
        import risk.bod_phase2 as module
        self.assertTrue(callable(module.bod_phase2_api))
