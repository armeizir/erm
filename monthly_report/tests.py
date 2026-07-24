from datetime import date
from decimal import Decimal
import json
from io import BytesIO
import tempfile

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase
from django.utils import timezone
from openpyxl import Workbook

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
    MasterSkalaDampak,
    MasterSkalaProbabilitas,
    PenugasanUnitBisnis,
    ReAssessmentItem,
    ReAssessmentSummary,
)

from .admin import MonthlyRiskReportAdmin, MonthlyRiskReportAdminForm, MonthlyRiskReportGroupFilter, MonthlyRiskReportItemInline, _monthly_risk_item_label
from .models import (
    MonthlyRiskReport,
    MonthlyRiskReportChange,
    MonthlyRiskReportItem,
    MonthlyRiskReportLossEvent,
    MonthlyRiskReportImportBatch,
)
from .import_services import analyze_import_batch, apply_import_batch
from .notifications import send_monthly_report_notification
from .services import duplicate_approved_report_to_next_month, refresh_monthly_report_summary


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

    def test_duplicate_approved_report_creates_next_month_draft_with_lineage(self):
        User = get_user_model()
        source = self._report("BID BIS")
        source.kode = "MRR-BIS-2026-02"
        source.status = "approved"
        source.approved_by = self.admin_user
        source.approved_at = timezone.now()
        source.is_locked = True
        source.save()

        risk_officer = User.objects.create_user(username="bis.ro")
        risk_champion = User.objects.create_user(username="bis.rc")
        PenugasanUnitBisnis.objects.create(
            unit_bisnis=source.reassessment.unit_bisnis,
            user=risk_officer,
            peran=PenugasanUnitBisnis.ROLE_RISK_OFFICER,
        )
        PenugasanUnitBisnis.objects.create(
            unit_bisnis=source.reassessment.unit_bisnis,
            user=risk_champion,
            peran=PenugasanUnitBisnis.ROLE_RISK_CHAMPION,
        )
        risk_event = self._risk_item(source, no_item=1, no_risiko=1)
        source_item = MonthlyRiskReportItem.objects.create(
            report=source,
            risk_event=risk_event,
            realisasi_nilai_dampak=Decimal("1000"),
            realisasi_nilai_probabilitas=Decimal("50"),
            realisasi_rencana_perlakuan="Realisasi Februari",
            next_action="Lanjutkan mitigasi",
        )
        MonthlyRiskReportChange.objects.create(
            report=source,
            jenis_perubahan=MonthlyRiskReportChange.CHANGE_TYPE_PROFILE,
            penjelasan="Perubahan Februari",
        )
        MonthlyRiskReportLossEvent.objects.create(
            report=source,
            nama_kejadian="Kejadian Februari",
        )

        target = duplicate_approved_report_to_next_month(source, self.admin_user)

        self.assertEqual(target.status, "draft")
        self.assertEqual(target.periode.kode_periode, "2026-03")
        self.assertEqual(target.kode, "MRR-BIS-2026-03")
        self.assertEqual(target.copied_from, source)
        self.assertEqual(target.copied_by, self.admin_user)
        self.assertIsNotNone(target.copied_at)
        self.assertEqual(target.prepared_by, risk_officer)
        self.assertEqual(target.reviewed_by, risk_champion)
        self.assertEqual(target.approved_by, self.admin_user)
        self.assertIsNone(target.submitted_at)
        self.assertIsNone(target.approved_at)
        self.assertFalse(target.is_locked)
        self.assertFalse(target.is_aggregated_to_corporate)
        self.assertEqual(target.display_profile_name, "Profil Risiko BID BIS (copy bulan Februari)")

        copied_item = target.items.get()
        self.assertEqual(copied_item.risk_event, source_item.risk_event)
        self.assertEqual(copied_item.realisasi_nilai_dampak, Decimal("1000"))
        self.assertEqual(copied_item.realisasi_nilai_probabilitas, Decimal("50"))
        self.assertEqual(copied_item.realisasi_rencana_perlakuan, "Realisasi Februari")
        self.assertEqual(copied_item.next_action, "Lanjutkan mitigasi")
        self.assertEqual(target.changes.count(), 1)
        self.assertEqual(target.loss_events.count(), 1)
        self.assertEqual(target.submission_logs.get().action, "duplicate")

        with self.assertRaises(ValidationError):
            duplicate_approved_report_to_next_month(source, self.admin_user)

    def test_duplicate_rejects_report_that_is_not_approved(self):
        source = self._report("BID OPS")

        with self.assertRaisesMessage(
            ValidationError,
            "Hanya laporan berstatus Approved yang dapat disalin.",
        ):
            duplicate_approved_report_to_next_month(source, self.admin_user)

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

    def _import_workbook(self, probability=40, progress=75):
        workbook = Workbook()
        iiia = workbook.active
        iiia.title = "III.A"
        iiib = workbook.create_sheet("III.B")
        iiia.cell(10, 2, "BID BIS-1-a")
        iiia.cell(10, 3, "Risiko BID BIS")
        iiia.cell(10, 12, "Asumsi dampak Februari")
        iiia.cell(10, 13, 1500000)
        iiia.cell(10, 17, 3)
        iiia.cell(10, 25, probability)
        iiia.cell(10, 29, 2)
        iiia.cell(10, 57, "Efektif")
        iiib.cell(10, 6, "BID BIS-1-a")
        iiib.cell(10, 11, "Realisasi mitigasi")
        iiib.cell(10, 12, "Output mitigasi")
        iiib.cell(10, 13, 250000)
        iiib.cell(10, 15, "PIC BIS")
        iiib.cell(10, 28, "Continue")
        iiib.cell(10, 29, "Sesuai jadwal")
        iiib.cell(10, 30, progress)
        iiib.cell(10, 41, "<= 10 hari")
        iiib.cell(10, 42, "Aman")
        stream = BytesIO()
        workbook.save(stream)
        return SimpleUploadedFile(
            "profil_bis_februari.xlsx",
            stream.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_excel_import_is_staged_then_applied_after_confirmation(self):
        report = self._report("BID BIS")
        risk_event = self._risk_item(
            report,
            no_item=1,
            no_risiko=1,
            no_penyebab_risiko="a",
            peristiwa_risiko="Risiko BID BIS",
        )
        item = MonthlyRiskReportItem.objects.create(report=report, risk_event=risk_event)
        MasterSkalaDampak.objects.create(nama="Menengah", urutan=3)
        MasterSkalaProbabilitas.objects.create(nama="Jarang", urutan=2)

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            batch = MonthlyRiskReportImportBatch.objects.create(
                report=report,
                source_file=self._import_workbook(),
                original_filename="profil_bis_februari.xlsx",
                file_sha256="a" * 64,
                uploaded_by=self.admin_user,
            )
            analyze_import_batch(batch)
            row = batch.rows.get()
            self.assertEqual(row.validation_level, row.LEVEL_GREEN)
            self.assertEqual(row.user_decision, row.DECISION_IMPORT)
            item.refresh_from_db()
            self.assertIsNone(item.realisasi_nilai_dampak)

            apply_import_batch(batch, self.admin_user)
            item.refresh_from_db()
            batch.refresh_from_db()

        self.assertEqual(batch.status, batch.STATUS_IMPORTED)
        self.assertEqual(item.realisasi_nilai_dampak, Decimal("1500000"))
        self.assertEqual(item.realisasi_nilai_probabilitas, Decimal("40"))
        self.assertEqual(item.progress_pelaksanaan_percent, Decimal("75"))
        self.assertEqual(item.realisasi_rencana_perlakuan, "Realisasi mitigasi")
        self.assertEqual(report.submission_logs.filter(action="import").count(), 1)

    def test_excel_import_rejects_invalid_value_until_user_skips_row(self):
        report = self._report("BID BIS INVALID")
        risk_event = self._risk_item(
            report, no_item=1, no_risiko=1, no_penyebab_risiko="a",
            peristiwa_risiko="Risiko BID BIS",
        )
        MonthlyRiskReportItem.objects.create(report=report, risk_event=risk_event)
        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            batch = MonthlyRiskReportImportBatch.objects.create(
                report=report,
                source_file=self._import_workbook(probability=140),
                original_filename="invalid.xlsx",
                file_sha256="b" * 64,
                uploaded_by=self.admin_user,
            )
            analyze_import_batch(batch)
            row = batch.rows.get()
            self.assertEqual(row.validation_level, row.LEVEL_RED)
            with self.assertRaisesMessage(ValidationError, "belum dikonfirmasi"):
                apply_import_batch(batch, self.admin_user)
            row.user_decision = row.DECISION_SKIP
            row.save(update_fields=["user_decision"])
            apply_import_batch(batch, self.admin_user)

    def test_group_filter_limits_monthly_reports_by_reassessment_group(self):
        report_aga = self._report("BID AGA")
        self._report("SETPER")
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

    def test_monthly_report_preparer_is_automatic_for_report_unit(self):
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
        report_admin = MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite())

        self.assertNotIn("prepared_by", form.fields)
        self.assertEqual(report_admin.prepared_by_display(report_infra), "infra_ro")
        self.assertEqual(list(form.fields["reviewed_by"].queryset), [infra_rc])
        self.assertEqual(form.fields["reviewed_by"].initial, infra_rc.pk)
        self.assertEqual(form.initial["reviewed_by"], infra_rc.pk)
        self.assertTrue(form.fields["reviewed_by"].disabled)
        self.assertEqual(list(form.fields["approved_by"].queryset), [infra_member])

    def test_monthly_report_form_handles_signer_fields_excluded_by_admin(self):
        report_infra = self._report("UB INFRA")

        class ReadonlySignerForm(MonthlyRiskReportAdminForm):
            class Meta(MonthlyRiskReportAdminForm.Meta):
                exclude = MonthlyRiskReportAdminForm.Meta.exclude + (
                    "prepared_by",
                    "reviewed_by",
                    "approved_by",
                )

        form = ReadonlySignerForm(instance=report_infra)

        self.assertNotIn("prepared_by", form.fields)
        self.assertNotIn("reviewed_by", form.fields)
        self.assertNotIn("approved_by", form.fields)

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
        PenugasanUnitBisnis.objects.create(
            unit_bisnis=report_infra.reassessment.unit_bisnis,
            user=self.prepared_by,
            peran=PenugasanUnitBisnis.ROLE_RISK_OFFICER,
        )
        report_admin = MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite())
        report_infra.evidence_url = (
            "https://brightbox.plnbatam.com/drive/d/f/test-evidence"
        )
        report_infra.save(update_fields=["evidence_url"])
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

    def test_reviewer_can_return_submitted_report_to_drafter_with_required_comment(self):
        User = get_user_model()
        reviewer = User.objects.create_user(
            username="revision.reviewer",
            email="reviewer@example.com",
        )
        report = self._report("INFRA REVISION")
        report.status = "submitted"
        report.reviewed_by = reviewer
        report.save(update_fields=["status", "reviewed_by"])
        report_admin = MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite())

        with self.assertRaisesMessage(ValidationError, "Komentar koreksi wajib diisi"):
            report_admin._apply_flow_action(report, "revise", reviewer)

        report_admin._apply_flow_action(
            report,
            "revise",
            reviewer,
            note="Perbaiki nilai residual dan tambahkan dasar perhitungan.",
        )
        report.refresh_from_db()

        self.assertEqual(report.status, "revision")
        revision_log = report.submission_logs.get(action="revise")
        self.assertEqual(revision_log.action_by, reviewer)
        self.assertIn("Perbaiki nilai residual", revision_log.note)
        rendered_comment = str(report_admin.latest_revision_comment(report))
        self.assertIn("revision.reviewer", rendered_comment)
        self.assertIn("Perbaiki nilai residual", rendered_comment)

    def test_approver_can_return_under_review_report_to_drafter(self):
        User = get_user_model()
        approver = User.objects.create_user(username="revision.approver")
        report = self._report("INFRA APPROVER REVISION")
        report.status = "under_review"
        report.approved_by = approver
        report.approved_at = timezone.now()
        report.save(update_fields=["status", "approved_by", "approved_at"])
        report_admin = MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite())

        report_admin._apply_flow_action(
            report,
            "revise",
            approver,
            note="Lengkapi eviden perlakuan risiko.",
        )
        report.refresh_from_db()

        self.assertEqual(report.status, "revision")
        self.assertIsNone(report.approved_at)

    def test_monthly_report_submit_requires_evidence_on_nas(self):
        report = self._report("BID AGA EVIDENCE")
        PenugasanUnitBisnis.objects.create(
            unit_bisnis=report.reassessment.unit_bisnis,
            user=self.prepared_by,
            peran=PenugasanUnitBisnis.ROLE_RISK_OFFICER,
        )
        report_admin = MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite())

        with self.assertRaisesMessage(ValidationError, "minimal satu link Eviden"):
            report_admin._apply_flow_action(report, "submit", self.admin_user)

    def test_monthly_report_evidence_accepts_any_https_domain(self):
        report = self._report("BID AGA INVALID EVIDENCE")
        report.evidence_url = "https://example.com/evidence.pdf"

        report.full_clean()

    def test_monthly_report_evidence_rejects_http_link(self):
        report = self._report("BID AGA HTTP EVIDENCE")
        report.evidence_url = "http://example.com/evidence.pdf"

        with self.assertRaisesMessage(ValidationError, "menggunakan HTTPS"):
            report.full_clean()

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

    def test_refresh_summary_counts_only_high_scores_from_20(self):
        report_infra = self._report("INFRA")
        moderate_event = self._risk_item(report_infra, no_item=1, no_risiko=1)
        high_event = self._risk_item(report_infra, no_item=2, no_risiko=2)
        moderate_report_item = MonthlyRiskReportItem.objects.create(
            report=report_infra,
            risk_event=moderate_event,
        )
        high_report_item = MonthlyRiskReportItem.objects.create(
            report=report_infra,
            risk_event=high_event,
        )
        MonthlyRiskReportItem.objects.filter(pk=moderate_report_item.pk).update(
            realisasi_skor_risiko=19,
            realisasi_level_risiko="Moderate to High",
        )
        MonthlyRiskReportItem.objects.filter(pk=high_report_item.pk).update(
            realisasi_skor_risiko=20,
            realisasi_level_risiko="High",
        )

        refresh_monthly_report_summary(report_infra)
        report_infra.refresh_from_db()

        self.assertEqual(report_infra.total_risiko, 2)
        self.assertEqual(report_infra.total_high, 1)

    def test_monthly_report_item_inline_cost_absorption_is_read_only(self):
        inline = MonthlyRiskReportItemInline(MonthlyRiskReport, AdminSite())

        self.assertIn("persentase_serapan_biaya", inline.readonly_fields)

    def test_monthly_report_item_calculates_cost_absorption_from_budget_formula(self):
        report_infra = self._report("INFRA")
        risk_item = self._risk_item(report_infra, no_item=1, no_risiko=1)
        risk_item.biaya_perlakuan_risiko = Decimal("100.00")
        risk_item.save()

        report_item = MonthlyRiskReportItem.objects.create(
            report=report_infra,
            risk_event=risk_item,
            realisasi_biaya_perlakuan=Decimal("150.00"),
            persentase_serapan_biaya=Decimal("12.00"),
        )

        self.assertEqual(report_item.persentase_serapan_biaya, Decimal("150.00"))

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

    def test_peta_risiko_iiic_exposes_previous_and_next_month_for_same_profile(self):
        report_infra = self._report("INFRA")
        january = PeriodeLaporan.objects.create(
            tahun_buku=self.tahun_buku,
            kode_periode="2026-01",
            nama_periode="Januari 2026",
            jenis_periode="bulanan",
            tanggal_mulai=date(2026, 1, 1),
            tanggal_selesai=date(2026, 1, 31),
        )
        march = PeriodeLaporan.objects.create(
            tahun_buku=self.tahun_buku,
            kode_periode="2026-03",
            nama_periode="Maret 2026",
            jenis_periode="bulanan",
            tanggal_mulai=date(2026, 3, 1),
            tanggal_selesai=date(2026, 3, 31),
        )
        previous_report = MonthlyRiskReport.objects.create(
            tahun_buku=self.tahun_buku,
            periode=january,
            reassessment=report_infra.reassessment,
            prepared_by=self.prepared_by,
        )
        next_report = MonthlyRiskReport.objects.create(
            tahun_buku=self.tahun_buku,
            periode=march,
            reassessment=report_infra.reassessment,
            prepared_by=self.prepared_by,
        )
        request = RequestFactory().get(
            f"/admin/monthly_report/monthlyriskreport/{report_infra.pk}/peta-risiko-iiic/"
        )
        request.user = self.admin_user
        report_admin = MonthlyRiskReportAdmin(MonthlyRiskReport, AdminSite())

        response = report_admin.peta_risiko_iiic_view(request, str(report_infra.pk))

        self.assertEqual(response.context_data["previous_report"], previous_report)
        self.assertEqual(response.context_data["next_report"], next_report)

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
        report_infra = self._report("INFRA")
        User = get_user_model()
        first_officer = User.objects.create_user(username="risk.office.1", email="risk.office.1@example.com")
        second_officer = User.objects.create_user(username="risk.office.2", email="risk.office.2@example.com")
        first_officer.first_name = "Risk"
        first_officer.last_name = "Officer Satu"
        first_officer.save(update_fields=["first_name", "last_name"])
        second_officer.first_name = "Risk"
        second_officer.last_name = "Officer Dua"
        second_officer.save(update_fields=["first_name", "last_name"])
        for officer in (first_officer, second_officer):
            PenugasanUnitBisnis.objects.create(
                unit_bisnis=report_infra.reassessment.unit_bisnis,
                user=officer,
                peran=PenugasanUnitBisnis.ROLE_RISK_OFFICER,
            )
        self._assign_pairing_officer(report_infra)

        sent = send_monthly_report_notification(report_infra, base_url="https://erm.plnbatam.com")

        self.assertEqual(sent, 1)
        self.assertCountEqual(
            mail.outbox[0].to,
            ["risk.office.1@example.com", "risk.office.2@example.com"],
        )
        self.assertEqual(mail.outbox[0].cc, [])
        self.assertEqual(mail.outbox[0].bcc, ["pairing@example.com"])
        self.assertNotIn("[MODE UJI COBA]", mail.outbox[0].body)
        self.assertIn("Yth. Risk Officer Dua; Risk Officer Satu,", mail.outbox[0].body)
        self.assertIn(
            "Yth. Risk Officer Dua; Risk Officer Satu,",
            mail.outbox[0].alternatives[0].content,
        )
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

    def test_revision_notification_sends_comment_to_all_drafters_and_bcc_pairing(self):
        app_setting = AppSetting.get_solo()
        app_setting.monthly_report_notification_test_email = ""
        app_setting.save(update_fields=["monthly_report_notification_test_email"])
        report = self._report("INFRA CORRECTION EMAIL")
        report.status = "revision"
        report.save(update_fields=["status"])
        User = get_user_model()
        first_officer = User.objects.create_user(
            username="revision.officer.1",
            email="revision.officer.1@example.com",
        )
        second_officer = User.objects.create_user(
            username="revision.officer.2",
            email="revision.officer.2@example.com",
        )
        for officer in (first_officer, second_officer):
            PenugasanUnitBisnis.objects.create(
                unit_bisnis=report.reassessment.unit_bisnis,
                user=officer,
                peran=PenugasanUnitBisnis.ROLE_RISK_OFFICER,
            )
        pairing = self._assign_pairing_officer(
            report,
            username="revision.pairing",
            email="revision.pairing@example.com",
        )

        sent = send_monthly_report_notification(
            report,
            base_url="https://erm.plnbatam.com",
            correction_note="Perbaiki nilai residual dan unggah eviden pendukung.",
        )

        self.assertEqual(sent, 1)
        self.assertCountEqual(
            mail.outbox[-1].to,
            [
                "revision.officer.1@example.com",
                "revision.officer.2@example.com",
            ],
        )
        self.assertEqual(mail.outbox[-1].bcc, [pairing.email])
        self.assertIn("Koreksi Laporan Risiko Bulanan", mail.outbox[-1].subject)
        self.assertIn("Perbaiki nilai residual", mail.outbox[-1].body)
        self.assertIn("Submit Ulang", mail.outbox[-1].body)
        self.assertIn(
            "Perbaiki nilai residual",
            mail.outbox[-1].alternatives[0].content,
        )

    def test_monthly_report_workflow_notifications_include_pairing_kpmr_and_mrk(self):
        User = get_user_model()
        app_setting = AppSetting.get_solo()
        app_setting.monthly_report_notification_test_email = ""
        app_setting.save(update_fields=["monthly_report_notification_test_email"])
        report = self._report("INFRA WORKFLOW")
        reviewer = User.objects.create_user(
            username="workflow.reviewer", email="reviewer@example.com"
        )
        approver = User.objects.create_user(
            username="workflow.approver", email="approver@example.com"
        )
        pairing = self._assign_pairing_officer(
            report, username="workflow.pairing", email="pairing.workflow@example.com"
        )
        mrk_group = Group.objects.create(name="BID MRK")
        mrk_user = User.objects.create_user(
            username="workflow.mrk", email="mrk@example.com"
        )
        mrk_user.groups.add(mrk_group)
        report.reviewed_by = reviewer
        report.approved_by = approver

        report.status = "submitted"
        report.save(update_fields=["status", "reviewed_by", "approved_by"])
        send_monthly_report_notification(report, base_url="https://erm.plnbatam.com")
        self.assertEqual(mail.outbox[-1].to, [reviewer.email])
        self.assertEqual(mail.outbox[-1].cc, [])
        self.assertEqual(mail.outbox[-1].bcc, [pairing.email])
        self.assertIn("Total KPMR", mail.outbox[-1].body)

        report.status = "under_review"
        report.save(update_fields=["status"])
        send_monthly_report_notification(report, base_url="https://erm.plnbatam.com")
        self.assertEqual(mail.outbox[-1].to, [approver.email])
        self.assertEqual(mail.outbox[-1].cc, [])
        self.assertEqual(mail.outbox[-1].bcc, [pairing.email])
        self.assertIn("Total KPMR", mail.outbox[-1].body)

        report.status = "approved"
        report.save(update_fields=["status"])
        send_monthly_report_notification(report, base_url="https://erm.plnbatam.com")
        self.assertEqual(mail.outbox[-1].to, [mrk_user.email])
        self.assertEqual(mail.outbox[-1].cc, [])
        self.assertEqual(mail.outbox[-1].bcc, [])
        self.assertIn("Total KPMR", mail.outbox[-1].body)
        self.assertIn("telah disetujui", mail.outbox[-1].body)

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
