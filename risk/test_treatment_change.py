from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from risk.models import RiskTreatmentChangeRequest
from risk.services.treatment_change import (
    normalize_proposed_changes,
)


class RiskTreatmentChangeServiceTests(SimpleTestCase):

    def test_allowed_fields_include_treatment_only(self):
        allowed = (
            RiskTreatmentChangeRequest
            .ALLOWED_CHANGE_KEYS
        )

        self.assertIn(
            "rencana_perlakuan_risiko",
            allowed,
        )
        self.assertIn(
            "timeline_12",
            allowed,
        )

        self.assertNotIn(
            "km_item_id",
            allowed,
        )
        self.assertNotIn(
            "risk_event_id",
            allowed,
        )
        self.assertNotIn(
            "nilai_dampak",
            allowed,
        )

    def test_unknown_field_is_rejected(self):
        with self.assertRaises(ValidationError):
            normalize_proposed_changes(
                {
                    "km_item_id": 999,
                }
            )

    def test_timeline_must_be_zero_or_one(self):
        with self.assertRaises(ValidationError):
            normalize_proposed_changes(
                {
                    "timeline_1": 2,
                }
            )

    def test_ids_are_normalized(self):
        value = normalize_proposed_changes(
            {
                "pic_organization_unit_id": "6",
            }
        )

        self.assertEqual(
            value["pic_organization_unit_id"],
            6,
        )

    def test_cost_is_json_safe(self):
        value = normalize_proposed_changes(
            {
                "biaya_perlakuan_risiko":
                    "1250000.50",
            }
        )

        self.assertEqual(
            value["biaya_perlakuan_risiko"],
            "1250000.50",
        )

    def test_m2m_is_sorted_and_unique(self):
        value = normalize_proposed_changes(
            {
                "jenis_rencana_perlakuan_risiko_ids":
                    [5, 2, 5, 3],
            }
        )

        self.assertEqual(
            value[
                "jenis_rencana_perlakuan_risiko_ids"
            ],
            [2, 3, 5],
        )
