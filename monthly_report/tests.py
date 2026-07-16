from datetime import date
import json

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.test import RequestFactory, TestCase

from masterdata.models import PeriodeLaporan, TahunBuku
from risk.admin import ReAssessmentItemAdmin
from risk.models import (
    AppSetting,
    BagianKontrakManajemen,
    ItemKontrakManajemen,
    KontrakManajemen,
    MasterBagianKM,
    MasterTemplateKM,
    PenugasanUnitBisnis,
    ReAssessmentItem,
    ReAssessmentSummary,
)

from .admin import MonthlyRiskReportAdmin, MonthlyRiskReportAdminForm, MonthlyRiskReportGroupFilter, MonthlyRiskReportItemInline, _monthly_risk_item_label
from .models import MonthlyRiskReport, MonthlyRiskReportItem
from .notifications import send_monthly_report_notification


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
            ("reassessment",),
        )
        self.assertIn("pdf_button", MonthlyRiskReportAdmin.list_display)

    def test_monthly_report_admin_loads_select2_for_inline_risk_event_dropdown(self):
        media = str(MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite()).media)

        self.assertIn("admin/js/vendor/select2/select2.full.js", media)
        self.assertIn("monthly_report_items_searchable.js", media)

    def test_monthly_report_signer_fields_are_limited_by_report_unit_and_role(self):
        User = get_user_model()
        report_infra = self._report("UB INFRA")
        report_bes = self._report("UB BES")
        infra_ro = User.objects.create_user(username="infra_ro")
        infra_rc = User.objects.create_user(username="infra_rc")
        infra_member = User.objects.create_user(username="infra_member")
        bes_ro = User.objects.create_user(username="bes_ro")
        bes_rc = User.objects.create_user(username="bes_rc")
        outsider = User.objects.create_user(username="outsider")
        report_infra.reassessment.unit_bisnis.user_set.add(infra_member)
        report_bes.reassessment.unit_bisnis.user_set.add(outsider)
        PenugasanUnitBisnis.objects.create(
            unit_bisnis=report_infra.reassessment.unit_bisnis,
            user=infra_ro,
            peran=PenugasanUnitBisnis.ROLE_RISK_OFFICER,
        )
        PenugasanUnitBisnis.objects.create(
            unit_bisnis=report_infra.reassessment.unit_bisnis,
            user=infra_rc,
            peran=PenugasanUnitBisnis.ROLE_RISK_CHAMPION,
        )
        PenugasanUnitBisnis.objects.create(
            unit_bisnis=report_bes.reassessment.unit_bisnis,
            user=bes_ro,
            peran=PenugasanUnitBisnis.ROLE_RISK_OFFICER,
        )
        PenugasanUnitBisnis.objects.create(
            unit_bisnis=report_bes.reassessment.unit_bisnis,
            user=bes_rc,
            peran=PenugasanUnitBisnis.ROLE_RISK_CHAMPION,
        )

        form = MonthlyRiskReportAdminForm(instance=report_infra)

        self.assertEqual(list(form.fields["prepared_by"].queryset), [infra_ro])
        self.assertEqual(list(form.fields["reviewed_by"].queryset), [infra_rc])
        self.assertEqual(list(form.fields["approved_by"].queryset), [infra_member])

    def test_monthly_report_pdf_view_returns_pdf(self):
        report_infra = self._report("INFRA")
        risk_item = self._risk_item(
            report_infra,
            no_item=1,
            no_risiko=1,
            no_penyebab_risiko="a",
        )
        MonthlyRiskReportItem.objects.create(report=report_infra, risk_event=risk_item)
        request = RequestFactory().get(
            f"/admin/monthly_report/monthlyriskreport/{report_infra.pk}/pdf/"
        )
        request.user = self.admin_user
        report_admin = MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite())

        response = report_admin.pdf_view(request, str(report_infra.pk))

        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_peta_risiko_iiic_includes_automatic_kpmr_calculation(self):
        report_infra = self._report("INFRA")
        request = RequestFactory().get(
            f"/admin/monthly_report/monthlyriskreport/{report_infra.pk}/peta-risiko-iiic/"
        )
        request.user = self.admin_user
        report_admin = MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite())

        response = report_admin.peta_risiko_iiic_view(request, str(report_infra.pk))

        self.assertEqual(response.context_data["kpmr_quarter"], 1)
        self.assertEqual(response.context_data["kpmr_calculation"].unit, report_infra.reassessment.unit_bisnis)
        self.assertEqual(response.context_data["kpmr_calculation"].report_count, 1)

    def test_monthly_report_notification_uses_test_email_when_configured(self):
        self.prepared_by.email = "risk.officer@example.com"
        self.prepared_by.save(update_fields=["email"])
        report_infra = self._report("INFRA")

        sent = send_monthly_report_notification(report_infra, base_url="https://erm.plnbatam.com")

        self.assertEqual(sent, 1)
        self.assertEqual(mail.outbox[0].to, ["armeizir@plnbatam.com"])
        self.assertIn("[MODE UJI COBA]", mail.outbox[0].body)
        self.assertIn("Input Laporan Risiko Bulanan", mail.outbox[0].subject)
        self.assertIn("Februari 2026", mail.outbox[0].body)
        self.assertIn("5 Maret 2026", mail.outbox[0].body)
        self.assertIn(
            "https://erm.plnbatam.com/admin/monthly_report/monthlyriskreport/",
            mail.outbox[0].body,
        )

    def test_monthly_report_notification_sends_to_prepared_by_when_test_email_empty(self):
        app_setting = AppSetting.get_solo()
        app_setting.monthly_report_notification_test_email = ""
        app_setting.save(update_fields=["monthly_report_notification_test_email"])
        self.prepared_by.email = "risk.officer@example.com"
        self.prepared_by.save(update_fields=["email"])
        report_infra = self._report("INFRA")

        sent = send_monthly_report_notification(report_infra, base_url="https://erm.plnbatam.com")

        self.assertEqual(sent, 1)
        self.assertEqual(mail.outbox[0].to, ["risk.officer@example.com"])
        self.assertNotIn("[MODE UJI COBA]", mail.outbox[0].body)
        self.assertIn("Input Laporan Risiko Bulanan", mail.outbox[0].subject)
        self.assertIn("Februari 2026", mail.outbox[0].body)
        self.assertIn("5 Maret 2026", mail.outbox[0].body)
        self.assertIn(
            "https://erm.plnbatam.com/admin/monthly_report/monthlyriskreport/",
            mail.outbox[0].body,
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

    def test_monthly_risk_item_label_uses_excel_risk_number_and_cause_code(self):
        report_infra = self._report("UB INFRA")
        item = self._risk_item(
            report_infra,
            no_item=42,
            no_risiko=25,
            no_penyebab_risiko="ae",
            peristiwa_risiko="Tidak tercapai KPI HCR, OCR dan Produktifitas",
        )

        label = _monthly_risk_item_label(item)

        self.assertIn("UB INFRA-25.ae", label)
        self.assertIn("Risiko 25", label)
        self.assertNotIn("Item 42", label)

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
        self.assertIn("Risiko 1", label)
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
        self.assertIn("Risiko 1", label)
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
        self.assertIn("INFRA-2.b", labels[1])
        self.assertIn("INFRA-3.c", labels[2])

    def test_risk_items_endpoint_uses_excel_risk_number_when_internal_item_number_jumps(self):
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

        self.assertIn("INFRA-26.p", labels[0])
        self.assertIn("INFRA-11.q", labels[1])
        self.assertNotIn("INFRA-28.q", labels[1])
