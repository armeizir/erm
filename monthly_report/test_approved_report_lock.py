from types import SimpleNamespace

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, SimpleTestCase

from monthly_report.admin import (
    MonthlyRiskReportAdmin,
    MonthlyRiskReportItemInline,
)
from monthly_report.models import MonthlyRiskReport


class ApprovedMonthlyReportLockTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get(
            "/admin/monthly_report/monthlyriskreport/1/change/"
        )
        self.request.user = SimpleNamespace(
            is_active=True,
            is_staff=True,
            is_superuser=True,
            has_perm=lambda *args, **kwargs: True,
        )
        self.report = SimpleNamespace(status="approved")

    def test_approved_report_cannot_be_changed_or_deleted(self):
        report_admin = MonthlyRiskReportAdmin(
            MonthlyRiskReport,
            AdminSite(),
        )

        self.assertFalse(
            report_admin.has_change_permission(
                self.request,
                self.report,
            )
        )
        self.assertFalse(
            report_admin.has_delete_permission(
                self.request,
                self.report,
            )
        )

    def test_approved_report_inline_is_fully_locked(self):
        inline = MonthlyRiskReportItemInline(
            MonthlyRiskReport,
            AdminSite(),
        )

        self.assertFalse(
            inline.has_change_permission(
                self.request,
                self.report,
            )
        )
        self.assertFalse(
            inline.has_add_permission(
                self.request,
                self.report,
            )
        )
        self.assertFalse(
            inline.has_delete_permission(
                self.request,
                self.report,
            )
        )
        self.assertEqual(
            inline.get_extra(
                self.request,
                self.report,
            ),
            0,
        )
