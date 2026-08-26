from types import SimpleNamespace

from django.test import SimpleTestCase

from risk.services.profile_completeness import _risk_cause_identity


def row(no_item, no_risiko, event, no_cause, cause):
    return SimpleNamespace(
        no_item=no_item,
        no_risiko=no_risiko,
        peristiwa_risiko=event,
        no_penyebab_risiko=no_cause,
        penyebab_risiko=cause,
    )


class ProfileCompletenessCauseIdentityTests(SimpleTestCase):

    def test_same_item_multiple_causes_are_not_identical(self):
        a = row(1, 1, "Risiko Audit", "a", "Cause A")
        b = row(1, 1, "Risiko Audit", "b", "Cause B")
        self.assertNotEqual(_risk_cause_identity(a), _risk_cause_identity(b))

    def test_same_item_multiple_events_are_not_identical(self):
        a = row(6, 1, "Risiko GCG", "a", "Cause A")
        b = row(6, 2, "Risiko HSSE", "a", "Cause A")
        self.assertNotEqual(_risk_cause_identity(a), _risk_cause_identity(b))

    def test_exact_same_risk_and_cause_is_identical(self):
        a = row(1, 1, "Risiko Audit", "a", "Cause A")
        b = row(1, 1, "  risiko   audit ", "a", " cause a ")
        self.assertEqual(_risk_cause_identity(a), _risk_cause_identity(b))
