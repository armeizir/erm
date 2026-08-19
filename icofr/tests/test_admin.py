from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from icofr.admin import CSAAssessmentAdmin, ICoFRWorkItemAdmin
from icofr.models import CSAAssessment, ICoFRWorkItem
from riskproject.admin_site import risk_admin_site


User = get_user_model()


class ICoFRAdminSmokeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("admin", "admin@example.com", "x")
        self.client.force_login(self.user)

    def test_rcm_admin_and_import_route_are_registered(self):
        response = self.client.get(reverse("risk_admin:icofr_rcmset_changelist"))
        self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse("risk_admin:icofr_rcm_import"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Import RCM Excel")


class ICoFRCSAAdminGuardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("admin-csa", "admin-csa@example.com", "x")
        self.client.force_login(self.user)

    def test_csa_cannot_be_added_manually(self):
        model_admin = CSAAssessmentAdmin(CSAAssessment, risk_admin_site)
        request = type("Request", (), {"user": self.user})()
        self.assertFalse(model_admin.has_add_permission(request))

    def test_work_item_is_distribution_managed_and_read_only(self):
        model_admin = ICoFRWorkItemAdmin(ICoFRWorkItem, risk_admin_site)
        request = type("Request", (), {"user": self.user})()

        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))

    def test_work_item_changelist_uses_compact_workspace_filter(self):
        response = self.client.get(reverse("risk_admin:icofr_icofrworkitem_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Semua RCM")
        self.assertContains(response, "Semua Periode")
        self.assertNotContains(response, "By Organization Unit")
