from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from masterdata.models import (
    OrganizationUnit,
    OrganizationUnitAccessGroup,
    OrganizationUnitUserAssignment,
)


class OrganizationUnitAccessGroupTests(TestCase):
    def setUp(self):
        self.organization_unit = OrganizationUnit.objects.create(
            code="TEST-ORG",
            name="BID TEST",
        )
        self.group = Group.objects.create(name="BID TEST")

    def test_organization_group_can_be_mapped(self):
        mapping = OrganizationUnitAccessGroup.objects.create(
            organization_unit=self.organization_unit,
            group=self.group,
        )

        self.assertEqual(
            list(self.group.organization_unit_mappings.all()),
            [mapping],
        )
        self.assertEqual(
            list(self.organization_unit.access_group_mappings.all()),
            [mapping],
        )

    def test_same_mapping_cannot_be_duplicated(self):
        OrganizationUnitAccessGroup.objects.create(
            organization_unit=self.organization_unit,
            group=self.group,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            OrganizationUnitAccessGroup.objects.create(
                organization_unit=self.organization_unit,
                group=self.group,
            )

    def test_permission_role_is_rejected_by_validation(self):
        role = Group.objects.create(name="ROLE - ACCESS - READ")
        mapping = OrganizationUnitAccessGroup(
            organization_unit=self.organization_unit,
            group=role,
        )

        with self.assertRaises(ValidationError):
            mapping.full_clean()


class OrganizationUnitUserAssignmentTests(TestCase):
    def setUp(self):
        self.organization_unit = OrganizationUnit.objects.create(
            code="TEST-USERS",
            name="SBID TEST",
        )
        User = self.organization_unit._meta.apps.get_model("auth", "User")
        self.first_user = User.objects.create_user(username="first.head")
        self.second_user = User.objects.create_user(username="second.head")

    def test_only_one_active_head_is_allowed_per_organization_unit(self):
        OrganizationUnitUserAssignment.objects.create(
            user=self.first_user,
            organization_unit=self.organization_unit,
            is_unit_head=True,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            OrganizationUnitUserAssignment.objects.create(
                user=self.second_user,
                organization_unit=self.organization_unit,
                is_unit_head=True,
            )

    def test_inactive_historical_head_can_coexist(self):
        OrganizationUnitUserAssignment.objects.create(
            user=self.first_user,
            organization_unit=self.organization_unit,
            is_unit_head=True,
            aktif=False,
        )
        current = OrganizationUnitUserAssignment.objects.create(
            user=self.second_user,
            organization_unit=self.organization_unit,
            is_unit_head=True,
        )

        self.assertTrue(current.aktif)
