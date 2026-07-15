from datetime import date
import json

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from masterdata.models import PeriodeLaporan, TahunBuku
from risk.admin import ReAssessmentItemAdmin
from risk.models import (
    BagianKontrakManajemen,
    ItemKontrakManajemen,
    KontrakManajemen,
    MasterBagianKM,
    MasterTemplateKM,
    ReAssessmentItem,
    ReAssessmentSummary,
)

from .admin import MonthlyRiskReportAdmin, MonthlyRiskReportGroupFilter, MonthlyRiskReportItemInline
from .models import MonthlyRiskReport, MonthlyRiskReportItem


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

    def _risk_item(
        self,
        report,
        no_item=1,
        no_risiko=None,
        no_penyebab_risiko=None,
        peristiwa_risiko=None,
    ):
        item_suffix = f"{no_item}-{no_risiko or no_item}-{no_penyebab_risiko or 'x'}"
        template, _ = MasterTemplateKM.objects.get_or_create(
            tahun=2026,
            defaults={"nama": "Template 2026"},
        )
        master_bagian = MasterBagianKM.objects.create(
            template=template,
            kode_bagian=f"B{report.pk}-{item_suffix}",
            nama_bagian="Keuangan",
            urutan=1,
        )
        bagian = BagianKontrakManajemen.objects.create(
            kontrak=report.reassessment.kontrak_manajemen,
            kode_bagian=f"B{report.pk}-{item_suffix}",
            nama_bagian="Keuangan",
        )
        km_item = ItemKontrakManajemen.objects.create(
            kontrak=report.reassessment.kontrak_manajemen,
            bagian=bagian,
            master_bagian=master_bagian,
            no_urut=1,
            indikator_kinerja_kunci=f"KPI {report.reassessment.unit_bisnis.name}",
            satuan="%",
            bobot=10,
            target="100",
        )
        return ReAssessmentItem.objects.create(
            summary=report.reassessment,
            no_item=no_item,
            km_item=km_item,
            no_risiko=no_risiko or no_item,
            no_penyebab_risiko=no_penyebab_risiko,
            peristiwa_risiko=peristiwa_risiko or f"Risiko {report.reassessment.unit_bisnis.name}",
            deskripsi_peristiwa_risiko="Deskripsi risiko",
            penyebab_risiko="Penyebab",
            rencana_perlakuan_risiko="Mitigasi",
            output_perlakuan_risiko="Output",
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

    def test_monthly_report_form_uses_searchable_autocomplete_fields(self):
        self.assertEqual(getattr(MonthlyRiskReportItemInline, "autocomplete_fields", ()), ())
        self.assertEqual(
            MonthlyRiskReportAdmin.autocomplete_fields,
            (
                "reassessment",
                "prepared_by",
                "reviewed_by",
                "approved_by",
            ),
        )

    def test_risk_item_autocomplete_is_limited_by_selected_reassessment(self):
        report_infra = self._report("INFRA")
        report_bes = self._report("BES")
        infra_item = self._risk_item(report_infra, no_item=1)
        self._risk_item(report_bes, no_item=2)
        request = RequestFactory().get(
            "/admin/autocomplete/",
            {"reassessment": str(report_infra.reassessment_id), "term": "Risiko"},
        )
        request.user = self.admin_user
        item_admin = ReAssessmentItemAdmin(ReAssessmentItem, AdminSite())

        queryset = item_admin.get_queryset(request)

        self.assertEqual(list(queryset), [infra_item])

    def test_inline_risk_event_field_is_limited_by_parent_report(self):
        report_infra = self._report("INFRA")
        report_bes = self._report("BES")
        infra_item = self._risk_item(report_infra, no_item=1)
        self._risk_item(report_bes, no_item=2)
        request = RequestFactory().get(
            f"/admin/monthly_report/monthlyriskreport/{report_infra.pk}/change/"
        )
        request.user = self.admin_user
        request._monthly_report_reassessment_id = report_infra.reassessment_id
        inline = MonthlyRiskReportItemInline(MonthlyRiskReport, AdminSite())

        formfield = inline.formfield_for_foreignkey(
            MonthlyRiskReportItem._meta.get_field("risk_event"),
            request,
        )

        self.assertEqual(list(formfield.queryset), [infra_item])

    def test_inline_risk_event_label_includes_item_number_and_event(self):
        report_infra = self._report("INFRA")
        infra_item = self._risk_item(report_infra, no_item=1)
        request = RequestFactory().get(
            f"/admin/monthly_report/monthlyriskreport/{report_infra.pk}/change/"
        )
        request.user = self.admin_user
        request._monthly_report_reassessment_id = report_infra.reassessment_id
        inline = MonthlyRiskReportItemInline(MonthlyRiskReport, AdminSite())

        formfield = inline.formfield_for_foreignkey(
            MonthlyRiskReportItem._meta.get_field("risk_event"),
            request,
        )

        label = formfield.label_from_instance(infra_item)
        self.assertIn("INFRA-1.a", label)
        self.assertIn("Item 1", label)
        self.assertIn("Penyebab a", label)
        self.assertIn("Risiko INFRA", label)

    def test_risk_items_endpoint_uses_informative_labels(self):
        report_infra = self._report("INFRA")
        self._risk_item(report_infra, no_item=1, no_risiko=1, no_penyebab_risiko="a")
        request = RequestFactory().get(
            "/admin/monthly_report/monthlyriskreport/risk-items/",
            {"reassessment": str(report_infra.reassessment_id)},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = self.admin_user
        report_admin = MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite())

        response = report_admin.risk_items_for_reassessment(request)
        payload = json.loads(response.content)
        label = payload["items"][0]["text"]

        self.assertIn("INFRA-1.a", label)
        self.assertIn("Item 1", label)
        self.assertIn("Penyebab a", label)
        self.assertIn("Risiko INFRA", label)

    def test_risk_items_endpoint_orders_by_item_then_cause_code(self):
        report_infra = self._report("INFRA")
        self._risk_item(
            report_infra,
            no_item=1,
            no_risiko=3,
            no_penyebab_risiko="c",
            peristiwa_risiko="Risiko pertama",
        )
        self._risk_item(
            report_infra,
            no_item=1,
            no_risiko=1,
            no_penyebab_risiko="a",
            peristiwa_risiko="Risiko pertama",
        )
        self._risk_item(
            report_infra,
            no_item=1,
            no_risiko=2,
            no_penyebab_risiko="b",
            peristiwa_risiko="Risiko pertama",
        )
        request = RequestFactory().get(
            "/admin/monthly_report/monthlyriskreport/risk-items/",
            {"reassessment": str(report_infra.reassessment_id)},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = self.admin_user
        report_admin = MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite())

        response = report_admin.risk_items_for_reassessment(request)
        payload = json.loads(response.content)
        labels = [item["text"] for item in payload["items"]]

        self.assertIn("INFRA-1.a", labels[0])
        self.assertIn("INFRA-1.b", labels[1])
        self.assertIn("INFRA-1.c", labels[2])

    def test_risk_items_endpoint_uses_display_sequence_when_internal_item_number_jumps(self):
        report_infra = self._report("INFRA")
        self._risk_item(
            report_infra,
            no_item=10,
            no_risiko=26,
            no_penyebab_risiko="p",
            peristiwa_risiko="Risiko urutan kesatu",
        )
        self._risk_item(
            report_infra,
            no_item=28,
            no_risiko=11,
            no_penyebab_risiko="q",
            peristiwa_risiko="Risiko urutan kedua",
        )
        request = RequestFactory().get(
            "/admin/monthly_report/monthlyriskreport/risk-items/",
            {"reassessment": str(report_infra.reassessment_id)},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = self.admin_user
        report_admin = MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite())

        response = report_admin.risk_items_for_reassessment(request)
        payload = json.loads(response.content)
        labels = [item["text"] for item in payload["items"]]

        self.assertIn("INFRA-1.p", labels[0])
        self.assertIn("INFRA-2.q", labels[1])
        self.assertNotIn("INFRA-28.q", labels[1])
