from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase

from risk.management.commands.sync_km_rkm_roles import (
    ROLE_KM_ADMIN,
    ROLE_RKM_ADMIN,
)


class KMRKMRolesTests(TestCase):
    def test_dry_run_does_not_create_groups(self):
        call_command("sync_km_rkm_roles")

        self.assertFalse(
            Group.objects.filter(name=ROLE_KM_ADMIN).exists()
        )
        self.assertFalse(
            Group.objects.filter(name=ROLE_RKM_ADMIN).exists()
        )

    def test_apply_creates_roles_with_expected_permissions(self):
        call_command("sync_km_rkm_roles", apply=True)

        km = Group.objects.get(name=ROLE_KM_ADMIN)
        rkm = Group.objects.get(name=ROLE_RKM_ADMIN)

        self.assertEqual(km.permissions.count(), 8)
        self.assertEqual(rkm.permissions.count(), 8)

        self.assertSetEqual(
            set(km.permissions.values_list("codename", flat=True)),
            {
                "view_kontrakmanajemen",
                "add_kontrakmanajemen",
                "change_kontrakmanajemen",
                "delete_kontrakmanajemen",
                "view_itemkontrakmanajemen",
                "add_itemkontrakmanajemen",
                "change_itemkontrakmanajemen",
                "delete_itemkontrakmanajemen",
            },
        )

        self.assertSetEqual(
            set(rkm.permissions.values_list("codename", flat=True)),
            {
                "view_rkmsummary",
                "add_rkmsummary",
                "change_rkmsummary",
                "delete_rkmsummary",
                "view_rkmitem",
                "add_rkmitem",
                "change_rkmitem",
                "delete_rkmitem",
            },
        )

    def test_apply_is_idempotent(self):
        call_command("sync_km_rkm_roles", apply=True)
        call_command("sync_km_rkm_roles", apply=True)

        self.assertEqual(
            Group.objects.filter(name=ROLE_KM_ADMIN).count(),
            1,
        )
        self.assertEqual(
            Group.objects.filter(name=ROLE_RKM_ADMIN).count(),
            1,
        )
