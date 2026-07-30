from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from django.contrib.admin import AdminSite
from django.contrib.admin.utils import flatten_fieldsets
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from risk.admin import (
    REASSESSMENT_ITEM_FIELDS,
    REASSESSMENT_ITEM_QUARTERLY_FIELD_GROUPS,
    ReAssessmentItemAdmin,
    ReAssessmentItemInline,
)
from risk.models import ReAssessmentItem, ReAssessmentSummary
from risk.services.risk_exposure import calculate_quarterly_risk_exposure


class QuarterlyRiskFieldLayoutTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="quarter-layout-admin",
            password="secret",
        )
        self.request = RequestFactory().get("/")
        self.request.user = self.user
        self.request.resolver_match = SimpleNamespace(kwargs={})
        self.model_admin = ReAssessmentItemAdmin(
            ReAssessmentItem,
            AdminSite(),
        )

    def test_required_quarterly_order_is_explicit_for_admin_and_inline(self):
        expected = (
            *(f"skala_probabilitas_q{quarter}" for quarter in range(1, 5)),
            *(f"eksposur_risiko_q{quarter}" for quarter in range(1, 5)),
            *(f"skala_risiko_q{quarter}" for quarter in range(1, 5)),
            *(f"level_nilai_risiko_q{quarter}" for quarter in range(1, 5)),
        )
        positions = [REASSESSMENT_ITEM_FIELDS.index(field) for field in expected]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(
            REASSESSMENT_ITEM_FIELDS[
                REASSESSMENT_ITEM_FIELDS.index("skala_probabilitas_q4") + 1
            ],
            "eksposur_risiko_q1",
        )
        self.assertEqual(
            REASSESSMENT_ITEM_FIELDS[
                REASSESSMENT_ITEM_FIELDS.index("eksposur_risiko_q4") + 1
            ],
            "skala_risiko_q1",
        )
        self.assertEqual(
            ReAssessmentItemInline.fields,
            REASSESSMENT_ITEM_FIELDS,
        )

    def test_add_and_change_forms_use_the_same_complete_order(self):
        add_fields = tuple(
            flatten_fieldsets(
                self.model_admin.get_fieldsets(self.request, obj=None)
            )
        )
        change_fields = tuple(
            flatten_fieldsets(
                self.model_admin.get_fieldsets(
                    self.request,
                    obj=SimpleNamespace(),
                )
            )
        )
        self.assertEqual(add_fields, REASSESSMENT_ITEM_FIELDS)
        self.assertEqual(change_fields, REASSESSMENT_ITEM_FIELDS)
        for quarter in range(1, 5):
            self.assertIn(f"eksposur_risiko_q{quarter}", add_fields)

    def test_exposure_has_dedicated_four_quarter_fieldset(self):
        groups = dict(REASSESSMENT_ITEM_QUARTERLY_FIELD_GROUPS)
        self.assertEqual(
            groups["EKSPOSUR RISIKO"],
            tuple(f"eksposur_risiko_q{quarter}" for quarter in range(1, 5)),
        )
        exposure_fieldset = next(
            options
            for title, options in self.model_admin.fieldsets
            if title == "EKSPOSUR RISIKO"
        )
        self.assertEqual(
            exposure_fieldset["fields"],
            (groups["EKSPOSUR RISIKO"],),
        )
        self.assertIn(
            "quarterly-exposure-group",
            exposure_fieldset["classes"],
        )
        self.assertIn(
            "Dihitung otomatis dari Nilai Dampak × Nilai Probabilitas.",
            exposure_fieldset["description"],
        )

    def test_exposure_is_readonly_and_cannot_be_posted(self):
        readonly = self.model_admin.get_readonly_fields(self.request)
        form_class = self.model_admin.get_form(self.request)
        inline = ReAssessmentItemInline(ReAssessmentSummary, AdminSite())
        for quarter in range(1, 5):
            field = f"eksposur_risiko_q{quarter}"
            self.assertIn(field, readonly)
            self.assertIn(field, inline.readonly_fields)
            self.assertNotIn(field, form_class.base_fields)

    def test_layout_does_not_change_exposure_calculation(self):
        cases = (
            (Decimal("34614169393900"), Decimal("1"), Decimal("346141693939.00")),
            (Decimal("19470470284050"), Decimal("1"), Decimal("194704702840.50")),
            (Decimal("7301426356519"), Decimal("1"), Decimal("73014263565.19")),
            (Decimal("3833475992663"), Decimal("1"), Decimal("38334759926.63")),
        )
        for impact, probability, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    calculate_quarterly_risk_exposure(impact, probability),
                    expected,
                )

    def test_quarterly_css_is_responsive_and_keeps_q4_readable(self):
        css_path = (
            Path(__file__).parent
            / "static/risk/css/reassessment_quarterly_fields.css"
        )
        css = css_path.read_text()
        self.assertIn(".quarterly-field-group", css)
        self.assertIn("repeat(4, minmax(0, 1fr))", css)
        self.assertIn("repeat(2, minmax(0, 1fr))", css)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", css)
        self.assertIn("overflow-wrap: anywhere", css)
        self.assertIn("overflow-x: auto", css)
