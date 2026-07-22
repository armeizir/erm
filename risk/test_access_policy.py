from django.test import SimpleTestCase, TestCase

from risk.access_policy import (
    is_organizational_group_name,
    permission_specs_for_level,
)


class SimpleAccessPolicyTests(SimpleTestCase):

    def test_bid_and_ub_are_organizational_groups(self):
        self.assertTrue(
            is_organizational_group_name(
                "BID BIS"
            )
        )

        self.assertTrue(
            is_organizational_group_name(
                "UB INFRA"
            )
        )

        self.assertFalse(
            is_organizational_group_name(
                "ROLE - ACCESS - READ"
            )
        )

        self.assertTrue(
            is_organizational_group_name(
                "SETPER"
            )
        )

        self.assertTrue(is_organizational_group_name("KSPI"))

    def test_read_has_only_view_permissions(self):
        specs = permission_specs_for_level(
            "READ"
        )

        self.assertTrue(specs)

        for _, codename in specs:
            self.assertTrue(
                codename.startswith("view_"),
                codename,
            )

    def test_edit_has_no_delete_permissions(self):
        specs = permission_specs_for_level(
            "EDIT"
        )

        self.assertTrue(
            any(
                codename.startswith("change_")
                for _, codename in specs
            )
        )

        self.assertFalse(
            any(
                codename.startswith("delete_")
                for _, codename in specs
            )
        )

    def test_admin_has_delete_permissions(self):
        specs = permission_specs_for_level(
            "ADMIN"
        )

        self.assertTrue(
            any(
                codename.startswith("delete_")
                for _, codename in specs
            )
        )

    def test_strategic_corporate_risk_not_allowed(self):
        for level in (
            "READ",
            "EDIT",
            "ADMIN",
        ):
            specs = permission_specs_for_level(
                level
            )

            forbidden = {
                (
                    "risk",
                    "view_profilrisikokorporatsummary",
                ),
                (
                    "risk",
                    "add_profilrisikokorporatsummary",
                ),
                (
                    "risk",
                    "change_profilrisikokorporatsummary",
                ),
                (
                    "risk",
                    "delete_profilrisikokorporatsummary",
                ),
            }

            self.assertTrue(
                forbidden.isdisjoint(specs)
            )

    def test_audit_log_stays_read_only_even_for_admin(self):
        specs = permission_specs_for_level(
            "ADMIN"
        )

        self.assertIn(
            (
                "monthly_report",
                "view_monthlyriskreportsubmissionlog",
            ),
            specs,
        )

        self.assertNotIn(
            (
                "monthly_report",
                "delete_monthlyriskreportsubmissionlog",
            ),
            specs,
        )

        self.assertNotIn(
            (
                "monthly_report",
                "change_monthlyriskreportsubmissionlog",
            ),
            specs,
        )



class SimpleAccessRoleCommandTests(TestCase):
    """Pastikan mode dry-run benar-benar tidak mengubah database."""

    def test_dry_run_does_not_create_access_role_groups(self):
        from io import StringIO

        from django.contrib.auth.models import Group
        from django.core.management import call_command

        from risk.access_policy import SIMPLE_ACCESS_ROLES

        role_names = list(SIMPLE_ACCESS_ROLES.values())

        Group.objects.filter(
            name__in=role_names
        ).delete()

        before_count = Group.objects.count()

        out = StringIO()

        call_command(
            "sync_simple_access_roles",
            stdout=out,
        )

        self.assertEqual(
            Group.objects.count(),
            before_count,
        )

        self.assertFalse(
            Group.objects.filter(
                name__in=role_names
            ).exists()
        )



class OrganizationalScopeTests(TestCase):

    def setUp(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group

        User = get_user_model()

        self.bid_bis = Group.objects.create(
            name="BID BIS"
        )

        self.bid_ops = Group.objects.create(
            name="BID OPS"
        )

        self.role_read = Group.objects.create(
            name="ROLE - ACCESS - READ"
        )

        self.user = User.objects.create_user(
            username="scope.test",
            email="scope.test@plnbatam.com",
            password="test-password",
            is_staff=True,
        )

    def test_org_group_is_scope_without_penugasan(self):
        from risk.access_policy import (
            organizational_groups_for_user,
        )

        self.user.groups.add(
            self.bid_bis,
            self.role_read,
        )

        result = list(
            organizational_groups_for_user(
                self.user
            ).values_list(
                "name",
                flat=True,
            )
        )

        self.assertEqual(
            result,
            ["BID BIS"],
        )

    def test_role_group_is_not_data_scope(self):
        from risk.access_policy import (
            organizational_groups_for_user,
        )

        self.user.groups.add(
            self.role_read
        )

        self.assertFalse(
            organizational_groups_for_user(
                self.user
            ).exists()
        )

    def test_user_cannot_inherit_other_unit_scope(self):
        from risk.access_policy import (
            organizational_groups_for_user,
        )

        self.user.groups.add(
            self.bid_bis
        )

        scope = organizational_groups_for_user(
            self.user
        )

        self.assertTrue(
            scope.filter(
                name="BID BIS"
            ).exists()
        )

        self.assertFalse(
            scope.filter(
                name="BID OPS"
            ).exists()
        )

    def test_superuser_is_not_sidebar_limited(self):
        from risk.access_policy import (
            user_has_organizational_scope,
        )

        self.user.groups.add(
            self.bid_bis
        )

        self.user.is_superuser = True
        self.user.save(
            update_fields=["is_superuser"]
        )

        self.assertFalse(
            user_has_organizational_scope(
                self.user
            )
        )


class RiskServiceScopeTests(TestCase):

    def setUp(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group

        User = get_user_model()

        self.bid_bis = Group.objects.create(
            name="BID BIS"
        )

        self.bid_ops = Group.objects.create(
            name="BID OPS"
        )

        self.user = User.objects.create_user(
            username="risk.scope.officer",
            email="risk.scope.officer@plnbatam.com",
            password="test-password",
            is_staff=True,
        )

        self.user.groups.add(
            self.bid_bis
        )

    def test_risk_officer_assignment_is_workflow_role_not_global_scope(self):
        from risk.models import PenugasanUnitBisnis
        from risk.services.permissions import (
            can_view_business_unit,
            is_risk_officer,
        )

        PenugasanUnitBisnis.objects.create(
            user=self.user,
            unit_bisnis=self.bid_bis,
            peran=PenugasanUnitBisnis.ROLE_RISK_OFFICER,
            aktif=True,
        )

        self.assertTrue(
            is_risk_officer(
                self.user
            )
        )

        self.assertTrue(
            can_view_business_unit(
                self.user,
                self.bid_bis,
            )
        )

        self.assertFalse(
            can_view_business_unit(
                self.user,
                self.bid_ops,
            )
        )

    def test_edit_scope_comes_from_organizational_group(self):
        from risk.models import PenugasanUnitBisnis
        from risk.services.permissions import (
            can_edit_business_unit,
        )

        PenugasanUnitBisnis.objects.create(
            user=self.user,
            unit_bisnis=self.bid_bis,
            peran=PenugasanUnitBisnis.ROLE_RISK_OFFICER,
            aktif=True,
        )

        self.assertTrue(
            can_edit_business_unit(
                self.user,
                self.bid_bis,
            )
        )

        self.assertFalse(
            can_edit_business_unit(
                self.user,
                self.bid_ops,
            )
        )

    def test_user_without_assignment_still_has_organizational_scope(self):
        from risk.services.permissions import (
            get_assigned_business_units,
        )

        scope = get_assigned_business_units(
            self.user
        )

        self.assertTrue(
            scope.filter(
                pk=self.bid_bis.pk
            ).exists()
        )

        self.assertFalse(
            scope.filter(
                pk=self.bid_ops.pk
            ).exists()
        )
