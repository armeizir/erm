from datetime import date
from decimal import Decimal
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
    KPMRIndikatorResmi,
    KPMRPeriode,
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

    def _assign_pairing_officer(self, report, username="pairing", email="pairing@example.com"):
        User = get_user_model()
        pairing = User.objects.create_user(username=username, email=email)
        PenugasanUnitBisnis.objects.create(
            unit_bisnis=report.reassessment.unit_bisnis,
            user=pairing,
            peran=PenugasanUnitBisnis.ROLE_PAIRING_OFFICER,
        )
        return pairing

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
        self.assertIn("web_button", MonthlyRiskReportAdmin.list_display)
        self.assertNotIn("pdf_button", MonthlyRiskReportAdmin.list_display)

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

    def test_monthly_report_status_is_readonly_after_saved(self):
        report_infra = self._report("INFRA")
        request = RequestFactory().get(
            f"/admin/monthly_report/monthlyriskreport/{report_infra.pk}/change/"
        )
        request.user = self.admin_user
        report_admin = MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite())

        readonly_fields = report_admin.get_readonly_fields(request, report_infra)

        self.assertIn("status", readonly_fields)

    def test_monthly_report_flow_moves_draft_to_submitted_to_under_review_to_approved(self):
        User = get_user_model()
        reviewer = User.objects.create_user(username="reviewer")
        approver = User.objects.create_user(username="approver")
        report_infra = self._report("INFRA")
        report_infra.reviewed_by = reviewer
        report_infra.approved_by = approver
        report_infra.save(update_fields=["reviewed_by", "approved_by"])
        report_admin = MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite())

        report_admin._apply_flow_action(report_infra, "submit", self.admin_user)
        report_infra.refresh_from_db()
        self.assertEqual(report_infra.status, "submitted")
        self.assertIsNotNone(report_infra.submitted_at)

        report_admin._apply_flow_action(report_infra, "review", reviewer)
        report_infra.refresh_from_db()
        self.assertEqual(report_infra.status, "under_review")

        report_admin._apply_flow_action(report_infra, "approve", approver)
        report_infra.refresh_from_db()
        self.assertEqual(report_infra.status, "approved")
        self.assertIsNotNone(report_infra.approved_at)
        self.assertEqual(
            list(report_infra.submission_logs.order_by("action_at").values_list("action", flat=True)),
            ["submit", "review", "approve"],
        )

    def test_monthly_report_flow_button_matches_current_status(self):
        report_admin = MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite())

        self.assertEqual(report_admin._flow_action_for_status("draft"), ("submit", "Submit Laporan"))
        self.assertEqual(report_admin._flow_action_for_status("revision"), ("submit", "Submit Ulang"))
        self.assertEqual(report_admin._flow_action_for_status("submitted"), ("review", "Review & Paraf"))
        self.assertEqual(report_admin._flow_action_for_status("under_review"), ("approve", "Approve"))
        self.assertIsNone(report_admin._flow_action_for_status("approved"))

    def test_monthly_report_admin_loads_select2_for_inline_risk_event_dropdown(self):
        media = str(MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite()).media)

        self.assertIn("admin/js/vendor/select2/select2.full.js", media)
        self.assertIn("monthly_report_items_searchable.js", media)

    def test_monthly_report_web_view_returns_report_context(self):
        report_infra = self._report("INFRA")
        risk_item = self._risk_item(
            report_infra,
            no_item=1,
            no_risiko=1,
            no_penyebab_risiko="a",
        )
        MonthlyRiskReportItem.objects.create(report=report_infra, risk_event=risk_item)
        request = RequestFactory().get(
            f"/admin/monthly_report/monthlyriskreport/{report_infra.pk}/web/"
        )
        request.user = self.admin_user
        report_admin = MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite())

        response = report_admin.web_report_view(request, str(report_infra.pk))
        response.render()

        self.assertEqual(response.context_data["report"], report_infra)
        self.assertEqual(len(response.context_data["iiia_rows"]), 1)
        self.assertEqual(len(response.context_data["iiib_rows"]), 1)
        self.assertIn(b"LAPORAN REALISASI MANAJEMEN RISIKO", response.content)
        self.assertIn(b"III.A. FORMAT TABEL REALISASI RISIKO RESIDUAL BULANAN", response.content)

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

    def test_peta_risiko_iiic_calculates_kpmr_from_monthly_data_even_when_saved_result_exists(self):
        report_infra = self._report("INFRA")
        period = KPMRPeriode.objects.create(
            tahun=2026,
            triwulan=1,
            unit_bisnis=report_infra.reassessment.unit_bisnis,
            skor_total=Decimal("81.00"),
            rating="FAIR",
        )
        KPMRIndikatorResmi.objects.create(
            periode=period,
            kode="I1",
            nama="Pencapaian Nilai Eksposur Risiko dibandingkan target Risiko Residual",
            bobot=Decimal("30.00"),
            jawaban="b",
            hasil=Decimal("60.00"),
            skor=Decimal("18.00"),
        )
        request = RequestFactory().get(
            f"/admin/monthly_report/monthlyriskreport/{report_infra.pk}/peta-risiko-iiic/"
        )
        request.user = self.admin_user
        report_admin = MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite())

        response = report_admin.peta_risiko_iiic_view(request, str(report_infra.pk))

        self.assertNotEqual(response.context_data["kpmr_calculation"].score_total, Decimal("81.00"))
        self.assertIn(
            "Belum ada item dengan realisasi risiko dan target residual yang lengkap.",
            response.context_data["kpmr_calculation"].notes,
        )

    def test_monthly_report_notification_sends_prepare_stage_to_risk_office_and_cc_pairing(self):
        self.prepared_by.email = "risk.office@example.com"
        self.prepared_by.save(update_fields=["email"])
        report_infra = self._report("INFRA")
        self._assign_pairing_officer(report_infra)

        sent = send_monthly_report_notification(report_infra, base_url="https://erm.plnbatam.com")

        self.assertEqual(sent, 1)
        self.assertEqual(mail.outbox[0].to, ["risk.office@example.com"])
        self.assertEqual(mail.outbox[0].cc, ["pairing@example.com"])
        self.assertNotIn("[MODE UJI COBA]", mail.outbox[0].body)
        self.assertIn("Pairing Officer", mail.outbox[0].body)
        self.assertIn("Input Laporan Risiko Bulanan", mail.outbox[0].subject)
        self.assertIn("Februari 2026", mail.outbox[0].body)
        self.assertIn("5 Maret 2026", mail.outbox[0].body)
        self.assertIn(
            "https://erm.plnbatam.com/admin/monthly_report/monthlyriskreport/",
            mail.outbox[0].body,
        )

    def test_monthly_report_review_notification_still_uses_test_email_when_configured(self):
        app_setting = AppSetting.get_solo()
        app_setting.monthly_report_notification_test_email = "armeizir@plnbatam.com"
        app_setting.save(update_fields=["monthly_report_notification_test_email"])
        User = get_user_model()
        reviewer = User.objects.create_user(username="reviewer", email="reviewer@example.com")
        report_infra = self._report("INFRA")
        report_infra.status = "submitted"
        report_infra.reviewed_by = reviewer
        report_infra.save(update_fields=["status", "reviewed_by"])

        sent = send_monthly_report_notification(report_infra, base_url="https://erm.plnbatam.com")

        self.assertEqual(sent, 1)
        self.assertEqual(mail.outbox[0].to, ["armeizir@plnbatam.com"])
        self.assertIn("[MODE UJI COBA]", mail.outbox[0].body)
        self.assertIn("Paraf / Review Laporan Risiko Bulanan", mail.outbox[0].subject)
        self.assertIn("Februari 2026", mail.outbox[0].body)
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
