from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.contrib.admin import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import RequestFactory, TestCase

from risk.admin import (
    ReAssessmentItemAdmin,
    ReAssessmentItemInline,
    ReAssessmentSummaryAdmin,
)
from risk.models import (
    ItemKontrakManajemen,
    KontrakManajemen,
    MasterBagianKM,
    MasterTemplateKM,
    ReAssessmentItem,
    ReAssessmentSummary,
)
from risk.services.risk_exposure import calculate_quarterly_risk_exposure


class QuarterlyRiskExposureTests(TestCase):
    def setUp(self):
        template = MasterTemplateKM.objects.create(tahun=2026, nama="KM 2026")
        master_bagian = MasterBagianKM.objects.create(
            template=template,
            kode_bagian="A",
            nama_bagian="Kinerja Utama",
            urutan=1,
        )
        self.unit = Group.objects.create(name="BID TEST EXPOSURE")
        contract = KontrakManajemen.objects.create(
            judul="KM EXPOSURE",
            tahun=2026,
            unit_bisnis=self.unit,
            template=template,
        )
        self.km_item = ItemKontrakManajemen.objects.create(
            kontrak=contract,
            master_bagian=master_bagian,
            no_urut=1,
            indikator_kinerja_kunci="KPI Exposure",
        )
        self.summary = ReAssessmentSummary.objects.create(
            judul="Profil Risiko Exposure",
            tahun=2026,
            unit_bisnis=self.unit,
            kontrak_manajemen=contract,
        )

    def item(self, **overrides):
        values = {
            "summary": self.summary,
            "no_item": 1,
            "km_item": self.km_item,
            "no_risiko": 1,
            "peristiwa_risiko": "Risiko exposure",
            "deskripsi_peristiwa_risiko": "Deskripsi",
            "penyebab_risiko": "Penyebab",
            "rencana_perlakuan_risiko": "Mitigasi",
            "output_perlakuan_risiko": "Output",
        }
        values.update(overrides)
        return ReAssessmentItem.objects.create(**values)

    def test_domain_calculation_uses_percent_decimal_and_half_up(self):
        self.assertEqual(
            calculate_quarterly_risk_exposure(
                Decimal("1000000000"), Decimal("25")
            ),
            Decimal("250000000.00"),
        )
        self.assertEqual(
            calculate_quarterly_risk_exposure(
                Decimal("10.05"), Decimal("10")
            ),
            Decimal("1.01"),
        )

    def test_all_quarters_are_calculated_independently(self):
        item = self.item(
            nilai_dampak_q1=Decimal("1000000000"),
            nilai_probabilitas_q1=Decimal("25"),
            nilai_dampak_q2=Decimal("1500000000"),
            nilai_probabilitas_q2=Decimal("40"),
            nilai_dampak_q3=Decimal("2000000000"),
            nilai_probabilitas_q3=Decimal("0"),
            nilai_dampak_q4=None,
            nilai_probabilitas_q4=None,
        )
        self.assertEqual(item.eksposur_risiko_q1, Decimal("250000000.00"))
        self.assertEqual(item.eksposur_risiko_q2, Decimal("600000000.00"))
        self.assertEqual(item.eksposur_risiko_q3, Decimal("0.00"))
        self.assertIsNone(item.eksposur_risiko_q4)

    def test_zero_impact_and_zero_probability_are_not_blank(self):
        self.assertEqual(
            calculate_quarterly_risk_exposure(Decimal("0"), Decimal("40")),
            Decimal("0.00"),
        )
        self.assertEqual(
            calculate_quarterly_risk_exposure(Decimal("1000"), Decimal("0")),
            Decimal("0.00"),
        )
        self.assertIsNone(
            calculate_quarterly_risk_exposure(None, Decimal("40"))
        )

    def test_large_decimal_does_not_lose_precision_or_overflow(self):
        self.assertEqual(
            calculate_quarterly_risk_exposure(
                Decimal("9999999999999999.99"), Decimal("99.99")
            ),
            Decimal("9998999999999999.99"),
        )

    def test_probability_outside_zero_to_one_hundred_is_rejected(self):
        for probability in (Decimal("-0.01"), Decimal("100.01")):
            with self.subTest(probability=probability), self.assertRaises(
                ValidationError
            ):
                calculate_quarterly_risk_exposure(
                    Decimal("100"), probability
                )

        with self.assertRaisesMessage(
            ValidationError,
            "Nilai Probabilitas Q2 harus berada antara 0% dan 100%.",
        ):
            self.item(
                nilai_dampak_q2=Decimal("100"),
                nilai_probabilitas_q2=Decimal("100.01"),
            )

    def test_save_recalculates_manipulated_exposure_and_clears_stale_value(self):
        item = self.item(
            nilai_dampak_q1=Decimal("1000"),
            nilai_probabilitas_q1=Decimal("25"),
            eksposur_risiko_q1=Decimal("999999"),
        )
        self.assertEqual(item.eksposur_risiko_q1, Decimal("250.00"))

        item.nilai_dampak_q1 = Decimal("2000")
        item.eksposur_risiko_q1 = Decimal("1")
        item.save(update_fields=["nilai_dampak_q1", "eksposur_risiko_q1"])
        item.refresh_from_db()
        self.assertEqual(item.eksposur_risiko_q1, Decimal("500.00"))

        item.nilai_probabilitas_q1 = None
        item.save(update_fields=["nilai_probabilitas_q1"])
        item.refresh_from_db()
        self.assertIsNone(item.eksposur_risiko_q1)

    def test_copy_style_create_does_not_preserve_incorrect_exposure(self):
        source = self.item(
            nilai_dampak_q2=Decimal("1200"),
            nilai_probabilitas_q2=Decimal("50"),
        )
        copied = self.item(
            no_item=2,
            no_risiko=2,
            nilai_dampak_q2=source.nilai_dampak_q2,
            nilai_probabilitas_q2=source.nilai_probabilitas_q2,
            eksposur_risiko_q2=Decimal("1"),
        )
        self.assertEqual(copied.eksposur_risiko_q2, Decimal("600.00"))

    def test_admin_exposure_is_readonly_but_quarter_inputs_are_editable(self):
        admin_user = get_user_model().objects.create_superuser(
            username="exposure-admin", password="secret"
        )
        request = RequestFactory().get("/")
        request.user = admin_user
        model_admin = ReAssessmentItemAdmin(ReAssessmentItem, AdminSite())
        readonly = model_admin.get_readonly_fields(request)
        for quarter in range(1, 5):
            self.assertIn(f"eksposur_risiko_q{quarter}", readonly)
            self.assertNotIn(f"nilai_dampak_q{quarter}", readonly)
            self.assertNotIn(f"nilai_probabilitas_q{quarter}", readonly)

        inline = ReAssessmentItemInline(ReAssessmentSummary, AdminSite())
        for quarter in range(1, 5):
            self.assertIn(
                f"eksposur_risiko_q{quarter}", inline.readonly_fields
            )
        self.assertEqual(
            ReAssessmentSummaryAdmin(
                ReAssessmentSummary, AdminSite()
            ).format_decimal_id(Decimal("346141693939")),
            "346.141.693.939,00",
        )

    def test_javascript_preview_uses_percent_formula(self):
        path = (
            Path(__file__).parent
            / "static/risk/js/reassessment_exposure.js"
        )
        script = path.read_text()
        self.assertIn("probabilityValue / 100", script)
        self.assertIn("Intl.NumberFormat(\"id-ID\"", script)
        self.assertIn("nilai_dampak_q${quarter}", script)
        self.assertIn("nilai_probabilitas_q${quarter}", script)
        self.assertIn('closest("tr.form-row")', script)

    def test_recalculation_command_dry_run_and_apply_are_idempotent(self):
        item = self.item(
            nilai_dampak_q1=Decimal("1000"),
            nilai_probabilitas_q1=Decimal("25"),
        )
        ReAssessmentItem.objects.filter(pk=item.pk).update(
            eksposur_risiko_q1=Decimal("999")
        )

        output = StringIO()
        call_command(
            "recalculate_quarterly_risk_exposure",
            "--dry-run",
            "--profile-id",
            str(self.summary.pk),
            stdout=output,
        )
        item.refresh_from_db()
        self.assertEqual(item.eksposur_risiko_q1, Decimal("999.00"))
        self.assertIn("Exposure berbeda: 1", output.getvalue())

        call_command(
            "recalculate_quarterly_risk_exposure",
            "--apply",
            "--profile-id",
            str(self.summary.pk),
            stdout=StringIO(),
        )
        item.refresh_from_db()
        self.assertEqual(item.eksposur_risiko_q1, Decimal("250.00"))

        output = StringIO()
        call_command(
            "recalculate_quarterly_risk_exposure",
            "--dry-run",
            "--profile-id",
            str(self.summary.pk),
            stdout=output,
        )
        self.assertIn("Exposure berbeda: 0", output.getvalue())
