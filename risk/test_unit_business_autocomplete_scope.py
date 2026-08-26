from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from risk.admin import CustomGroupAdmin


class UnitBusinessAutocompleteScopeTests(TestCase):
    def setUp(self):
        self.hcga = Group.objects.create(name="BID HCGA")
        self.aga = Group.objects.create(name="BID AGA")
        self.role = Group.objects.create(name="ROLE - ACCESS - READ")

        self.user = get_user_model().objects.create_user(
            username="yohannes.test",
            password="test",
            is_staff=True,
        )

        self.superuser = get_user_model().objects.create_superuser(
            username="admin.test",
            email="admin@example.com",
            password="test",
        )

        self.model_admin = CustomGroupAdmin(Group, admin.site)
        self.rf = RequestFactory()

    def _request(self, user, field_name="unit_bisnis"):
        request = self.rf.get(
            "/admin/autocomplete/",
            {
                "app_label": "risk",
                "model_name": "rkmsummary",
                "field_name": field_name,
            },
        )
        request.user = user
        return request

    @patch("risk.admin.assigned_unit_businesses_for_user")
    def test_rkm_unit_autocomplete_is_scoped(self, scoped):
        scoped.return_value = Group.objects.filter(pk=self.hcga.pk)

        qs, _ = self.model_admin.get_search_results(
            self._request(self.user),
            Group.objects.all(),
            "",
        )

        self.assertEqual(
            list(qs.values_list("name", flat=True)),
            ["BID HCGA"],
        )

    @patch("risk.admin.assigned_unit_businesses_for_user")
    def test_other_group_autocomplete_is_not_scoped(self, scoped):
        scoped.return_value = Group.objects.filter(pk=self.hcga.pk)

        qs, _ = self.model_admin.get_search_results(
            self._request(self.user, "groups"),
            Group.objects.all(),
            "",
        )

        self.assertEqual(qs.count(), 3)

    @patch("risk.admin.assigned_unit_businesses_for_user")
    def test_superuser_can_see_all_units(self, scoped):
        scoped.return_value = Group.objects.filter(pk=self.hcga.pk)

        qs, _ = self.model_admin.get_search_results(
            self._request(self.superuser),
            Group.objects.all(),
            "",
        )

        self.assertEqual(qs.count(), 3)
