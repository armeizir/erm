from datetime import date

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from masterdata.models import PeriodeLaporan, TahunBuku
from risk.models import KontrakManajemen, ReAssessmentSummary

from .admin import MonthlyRiskReportAdmin, MonthlyRiskReportGroupFilter
from .models import MonthlyRiskReport


class MonthlyRiskReportAdminTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin_user = User.objects.create_superuser(username="admin", password="secret")
        self.prepared_by = User.objects.create_user(username="prepared", password="secret")
        self.tahun_buku = TahunBuku.objects.create(tahun=2026)
        self.periode = PeriodeLaporan.objects.create(
            tahun_buku=self.tahun_buku,
            kode_periode="2026-02",
            nama_periode="Februari 2026",
            jenis_periode="bulanan",
            tanggal_mulai=date(2026, 2, 1),
            tanggal_selesai=date(2026, 2, 28),
        )

    def _report(self, group_name):
        group = Group.objects.create(name=group_name)
        kontrak = KontrakManajemen.objects.create(
            judul=f"KM {group_name}",
            tahun=2026,
            unit_bisnis=group,
        )
        reassessment = ReAssessmentSummary.objects.create(
            judul=f"Profil Risiko {group_name}",
            tahun=2026,
            unit_bisnis=group,
            kontrak_manajemen=kontrak,
        )
        return MonthlyRiskReport.objects.create(
            tahun_buku=self.tahun_buku,
            periode=self.periode,
            reassessment=reassessment,
            prepared_by=self.prepared_by,
        )

    def test_group_filter_limits_monthly_reports_by_reassessment_group(self):
        report_aga = self._report("BID AGA")
        self._report("SEKPER")
        request = RequestFactory().get(
            "/admin/monthly_report/monthlyriskreport/",
            {"group": str(report_aga.reassessment.unit_bisnis_id)},
        )
        request.user = self.admin_user
        report_admin = MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite())
        group_filter = MonthlyRiskReportGroupFilter(
            request,
            {"group": str(report_aga.reassessment.unit_bisnis_id)},
            MonthlyRiskReport,
            report_admin,
        )

        queryset = group_filter.queryset(request, report_admin.get_queryset(request))

        self.assertEqual(list(queryset), [report_aga])
        self.assertIn(
            (str(report_aga.reassessment.unit_bisnis_id), "BID AGA"),
            list(group_filter.lookups(request, report_admin)),
        )
