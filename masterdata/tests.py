from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

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


class OrganizationAssignmentDashboardTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="organization.dashboard.admin",
            email="organization.admin@example.com",
            password="secret",
        )
        self.staff = User.objects.create_user(
            username="organization.dashboard.staff",
            email="organization.staff@example.com",
            password="secret",
            is_staff=True,
        )
        self.dashboard_url = reverse("risk_admin:index")
        self.assignment_url = reverse(
            "risk_admin:masterdata_organizationunituserassignment_changelist"
        )

    def _grant_view_permission(self, user):
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="masterdata",
                codename="view_organizationunituserassignment",
            ),
            Permission.objects.get(
                content_type__app_label="masterdata",
                codename="view_organizationunit",
            ),
        )

    def _master_organization_items(self, response):
        sections = response.context["dashboard_sections"]
        section = next(
            item for item in sections if item["title"] == "Master Organisasi"
        )
        return section["items"]

    def test_staff_with_permission_sees_ordered_assignment_menu_and_can_open_it(self):
        self._grant_view_permission(self.staff)
        self.client.force_login(self.staff)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        items = self._master_organization_items(response)
        assignment_items = [
            item for item in items if item["label"] == "Penugasan User"
        ]
        self.assertEqual(len(assignment_items), 1)
        self.assertEqual(assignment_items[0]["url"], self.assignment_url)
        labels = [item["label"] for item in items]
        self.assertEqual(
            labels.index("Penugasan User"),
            labels.index("Organization Unit") + 1,
        )
        self.assertContains(response, "Master Organisasi")
        self.assertContains(response, "Penugasan User")

        changelist = self.client.get(self.assignment_url)
        self.assertEqual(changelist.status_code, 200)

    def test_staff_without_permission_does_not_see_assignment_menu(self):
        self.client.force_login(self.staff)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Penugasan User")
        self.assertEqual(self.client.get(self.assignment_url).status_code, 403)

    def test_superuser_sees_assignment_once_and_other_organization_menu_remains(self):
        self.client.force_login(self.superuser)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        items = self._master_organization_items(response)
        labels = [item["label"] for item in items]
        self.assertEqual(labels.count("Penugasan User"), 1)
        self.assertEqual(
            labels,
            [
                "Company Code",
                "Business Area",
                "Personnel Area",
                "Personnel Sub Area",
                "Directorate",
                "Division",
                "Organization Unit",
                "Penugasan User",
            ],
        )
        self.assertEqual(self.client.get(self.assignment_url).status_code, 200)
