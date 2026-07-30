from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from django.contrib.admin import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import RequestFactory, TestCase

from risk.admin import ReAssessmentItemAdmin, ReAssessmentItemInline
from risk.models import (
    ItemKontrakManajemen,
    KontrakManajemen,
    MasterBagianKM,
    MasterLevelRisiko,
    MasterSkalaDampak,
    MasterSkalaProbabilitas,
    MasterTemplateKM,
    ReAssessmentItem,
    ReAssessmentSummary,
    RiskMatrix,
    RiskMatrixCell,
)
from risk.services.risk_level import (
    assign_item_quarterly_risk_levels,
    classify_risk_level,
)


class RiskLevelDomainTests(TestCase):
    def test_official_boundaries_and_labels(self):
        cases = {
            1: ("LOW", "Rendah"),
            5: ("LOW", "Rendah"),
            6: ("LOW_TO_MODERATE", "Rendah ke Moderat"),
            11: ("LOW_TO_MODERATE", "Rendah ke Moderat"),
            12: ("MODERATE", "Moderat"),
            15: ("MODERATE", "Moderat"),
            16: ("MODERATE_TO_HIGH", "Moderat ke Tinggi"),
            19: ("MODERATE_TO_HIGH", "Moderat ke Tinggi"),
            20: ("HIGH", "Tinggi"),
            25: ("HIGH", "Tinggi"),
        }
        for scale, expected in cases.items():
            with self.subTest(scale=scale):
                level = classify_risk_level(scale)
                self.assertEqual((level.code, level.display_label), expected)

    def test_blank_is_blank_and_integer_decimals_are_supported(self):
        self.assertIsNone(classify_risk_level(None))
        self.assertIsNone(classify_risk_level(""))
        self.assertEqual(classify_risk_level("13").code, "MODERATE")
        self.assertEqual(classify_risk_level("13.0").code, "MODERATE")

    def test_invalid_scales_are_rejected(self):
        for value in (0, 26, -1, "13.5", "Tinggi", True):
            with self.subTest(value=value), self.assertRaisesMessage(
                ValidationError,
                "Skala Risiko harus berupa bilangan bulat antara 1 dan 25.",
            ):
                classify_risk_level(value)

    def test_workbook_characterization_and_quarters_are_independent(self):
        item = SimpleNamespace(
            skala_risiko_q1="22",
            skala_risiko_q2="19",
            skala_risiko_q3="14",
            skala_risiko_q4="13",
        )
        assign_item_quarterly_risk_levels(item)
        self.assertEqual(item.level_nilai_risiko_q1, "High")
        self.assertEqual(item.level_nilai_risiko_q2, "Moderate To High")
        self.assertEqual(item.level_nilai_risiko_q3, "Moderate")
        self.assertEqual(item.level_nilai_risiko_q4, "Moderate")

    def test_clearing_scale_clears_stale_level(self):
        item = SimpleNamespace(
            skala_risiko_q1=None,
            skala_risiko_q2="6",
            skala_risiko_q3="12",
            skala_risiko_q4="20",
            level_nilai_risiko_q1="High",
        )
        assign_item_quarterly_risk_levels(item)
        self.assertIsNone(item.level_nilai_risiko_q1)


class QuarterlyRiskLevelIntegrationTests(TestCase):
    def setUp(self):
        template = MasterTemplateKM.objects.create(tahun=2026, nama="KM Level 2026")
        section = MasterBagianKM.objects.create(
            template=template,
            kode_bagian="A",
            nama_bagian="Kinerja Utama",
            urutan=1,
        )
        self.unit = Group.objects.create(name="BID TEST LEVEL")
        contract = KontrakManajemen.objects.create(
            judul="KM LEVEL",
            tahun=2026,
            unit_bisnis=self.unit,
            template=template,
        )
        self.km_item = ItemKontrakManajemen.objects.create(
            kontrak=contract,
            master_bagian=section,
            no_urut=1,
            indikator_kinerja_kunci="KPI Level",
        )
        self.summary = ReAssessmentSummary.objects.create(
            judul="Profil Risiko Level",
            tahun=2026,
            unit_bisnis=self.unit,
            kontrak_manajemen=contract,
        )

    def item(self):
        return ReAssessmentItem.objects.create(
            summary=self.summary,
            no_item=1,
            km_item=self.km_item,
            no_risiko=1,
            peristiwa_risiko="Risiko level",
            deskripsi_peristiwa_risiko="Deskripsi",
        )

    def test_level_post_fields_are_readonly_in_admin_and_inline(self):
        user = get_user_model().objects.create_superuser(
            username="level-admin", password="secret"
        )
        request = RequestFactory().get("/")
        request.user = user
        model_admin = ReAssessmentItemAdmin(ReAssessmentItem, AdminSite())
        readonly = model_admin.get_readonly_fields(request)
        inline = ReAssessmentItemInline(ReAssessmentSummary, AdminSite())
        for quarter in range(1, 5):
            self.assertIn(f"level_nilai_risiko_q{quarter}", readonly)
            self.assertIn(
                f"level_nilai_risiko_q{quarter}", inline.readonly_fields
            )
            self.assertNotIn(
                f"skala_risiko_q{quarter}", inline.readonly_fields
            )

    def test_model_save_ignores_stale_level_when_scale_source_is_blank(self):
        item = self.item()
        ReAssessmentItem.objects.filter(pk=item.pk).update(
            level_nilai_risiko_q1="High"
        )
        item.refresh_from_db()
        item.save()
        item.refresh_from_db()
        self.assertIsNone(item.level_nilai_risiko_q1)

    def test_model_save_classifies_matrix_score_not_master_level_name(self):
        impact = MasterSkalaDampak.objects.create(nama="Dampak test", urutan=1)
        probability = MasterSkalaProbabilitas.objects.create(
            nama="Probabilitas test", urutan=1
        )
        misleading_level = MasterLevelRisiko.objects.create(
            kode="TEST-MODERATE",
            nama="Moderate",
        )
        matrix = RiskMatrix.objects.create(
            kode="TEST-LEVEL-MATRIX",
            nama="Test level matrix",
            aktif=True,
        )
        cell = RiskMatrixCell.objects.create(
            matrix=matrix,
            skala_dampak=impact,
            skala_probabilitas=probability,
            skor=22,
            level_risiko=misleading_level,
        )
        self.summary.risk_matrix = matrix
        self.summary.save(update_fields=["risk_matrix"])

        item = self.item()
        item.skala_dampak_q1 = impact
        item.skala_probabilitas_q1 = probability
        item.level_nilai_risiko_q1 = "Moderate"
        item.save()
        self.assertEqual(item.skala_risiko_q1, "22")
        self.assertEqual(item.level_nilai_risiko_q1, "High")

        cell.skor = 19
        cell.save(update_fields=["skor"])
        item.level_nilai_risiko_q1 = "High"
        item.save()
        self.assertEqual(item.level_nilai_risiko_q1, "Moderate To High")

    def test_command_dry_run_and_apply_are_idempotent(self):
        item = self.item()
        ReAssessmentItem.objects.filter(pk=item.pk).update(
            skala_risiko_q1="22",
            level_nilai_risiko_q1="Moderate",
        )
        output = StringIO()
        call_command(
            "audit_quarterly_risk_levels",
            "--profile-id",
            str(self.summary.pk),
            stdout=output,
        )
        item.refresh_from_db()
        self.assertEqual(item.level_nilai_risiko_q1, "Moderate")
        self.assertIn("Level berbeda: 1", output.getvalue())

        call_command(
            "audit_quarterly_risk_levels",
            "--apply",
            "--profile-id",
            str(self.summary.pk),
            stdout=StringIO(),
        )
        item.refresh_from_db()
        self.assertEqual(item.level_nilai_risiko_q1, "High")

        output = StringIO()
        call_command(
            "audit_quarterly_risk_levels",
            "--profile-id",
            str(self.summary.pk),
            stdout=output,
        )
        self.assertIn("Level berbeda: 0", output.getvalue())

    def test_preview_and_shared_css_exist(self):
        static = Path(__file__).parent / "static/risk"
        script = (static / "js/reassessment_risk_level.js").read_text()
        css = (static / "css/risk_level.css").read_text()
        self.assertIn("Rendah ke Moderat", script)
        self.assertIn("Number.isInteger", script)
        self.assertIn(".risk-level-high", css)
        self.assertIn("@media print", css)
