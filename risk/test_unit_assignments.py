from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase

from risk.models import PenugasanUnitBisnis


class UnitAssignmentTests(TestCase):
    def setUp(self):
        self.unit = Group.objects.create(name="BID STRADA")
        self.first_user = get_user_model().objects.create_user(username="champion1")
        self.second_user = get_user_model().objects.create_user(username="champion2")

    def assignment(self, user, role):
        return PenugasanUnitBisnis(
            user=user, unit_bisnis=self.unit, peran=role, aktif=True
        )

    def test_multiple_active_risk_champions_are_allowed(self):
        for user in (self.first_user, self.second_user):
            assignment = self.assignment(user, PenugasanUnitBisnis.ROLE_RISK_CHAMPION)
            assignment.full_clean()
            assignment.save()
        self.assertEqual(self.unit.penugasan_pengguna.filter(aktif=True).count(), 2)

    def test_same_user_cannot_have_duplicate_role_in_unit(self):
        self.assignment(self.first_user, PenugasanUnitBisnis.ROLE_RISK_CHAMPION).save()
        duplicate = self.assignment(self.first_user, PenugasanUnitBisnis.ROLE_RISK_CHAMPION)
        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_only_one_active_pairing_officer_is_allowed(self):
        self.assignment(self.first_user, PenugasanUnitBisnis.ROLE_PAIRING_OFFICER).save()
        second = self.assignment(self.second_user, PenugasanUnitBisnis.ROLE_PAIRING_OFFICER)
        with self.assertRaisesMessage(ValidationError, "sudah memiliki Pairing Officer aktif"):
            second.full_clean()
