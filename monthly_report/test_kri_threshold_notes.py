from django.test import SimpleTestCase

from monthly_report.kri_services import _matches


class KriThresholdParentheticalNoteTests(SimpleTestCase):
    def test_parenthetical_note_is_not_part_of_numeric_threshold(self):
        self.assertTrue(_matches(">= 60 MW (n+1)", 60))
        self.assertTrue(_matches(">= 60 MW (n+1)", 61))
        self.assertFalse(_matches(">= 60 MW (n+1)", 59))

    def test_plain_threshold_behaviour_is_preserved(self):
        self.assertTrue(_matches(">= 60 MW", 60))
        self.assertFalse(_matches(">= 60 MW", 59))
