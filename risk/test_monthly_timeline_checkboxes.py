from pathlib import Path

from django.contrib.admin import AdminSite
from django.contrib.admin.utils import flatten_fieldsets
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from risk.admin import (
    REASSESSMENT_ITEM_FIELDS,
    REASSESSMENT_ITEM_TREATMENT_FIELDS,
    REASSESSMENT_TIMELINE_FIELDS,
    ReAssessmentItemAdmin,
    ReAssessmentItemInline,
    ReAssessmentItemTimelineForm,
)
from risk.models import (
    ItemKontrakManajemen,
    KontrakManajemen,
    MasterBagianKM,
    MasterTemplateKM,
    ReAssessmentItem,
    ReAssessmentSummary,
)


class TimelineOnlyForm(ReAssessmentItemTimelineForm):
    class Meta:
        model = ReAssessmentItem
        fields = ("monthly_timeline",)


class MonthlyTimelineCheckboxTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        unit = Group.objects.create(name="BID TIMELINE")
        template = MasterTemplateKM.objects.create(
            tahun=2026,
            nama="KM Timeline 2026",
        )
        section = MasterBagianKM.objects.create(
            template=template,
            kode_bagian="A",
            nama_bagian="Kinerja Utama",
            urutan=1,
        )
        contract = KontrakManajemen.objects.create(
            judul="Kontrak Timeline",
            tahun=2026,
            unit_bisnis=unit,
            template=template,
        )
        km_item = ItemKontrakManajemen.objects.create(
            kontrak=contract,
            master_bagian=section,
            no_urut=1,
            indikator_kinerja_kunci="KPI Timeline",
        )
        cls.summary = ReAssessmentSummary.objects.create(
            judul="Profil Risiko Timeline",
            tahun=2026,
            unit_bisnis=unit,
            kontrak_manajemen=contract,
        )
        cls.item = ReAssessmentItem.objects.create(
            summary=cls.summary,
            no_item=1,
            km_item=km_item,
            no_risiko=1,
            peristiwa_risiko="Risiko pengujian timeline",
            deskripsi_peristiwa_risiko="Deskripsi risiko timeline",
            timeline_1=1,
            timeline_3=1,
            timeline_12=1,
        )

    def test_model_contract_remains_positive_small_integer(self):
        for field_name in REASSESSMENT_TIMELINE_FIELDS:
            field = ReAssessmentItem._meta.get_field(field_name)
            self.assertEqual(field.get_internal_type(), "PositiveSmallIntegerField")

    def test_twelve_model_fields_remain_available(self):
        self.assertEqual(
            REASSESSMENT_TIMELINE_FIELDS,
            tuple(f"timeline_{month}" for month in range(1, 13)),
        )

    def test_existing_one_values_render_checked(self):
        html = TimelineOnlyForm(instance=self.item).as_p()
        for value in ("1", "3", "12"):
            option = html.split(f'value="{value}"', 1)[1].split(">", 1)[0]
            self.assertIn("checked", option)

    def test_existing_zero_value_renders_unchecked(self):
        html = TimelineOnlyForm(instance=self.item).as_p()
        option = html.split('value="2"', 1)[1].split("</label>", 1)[0]
        self.assertNotIn("checked", option)

    def test_checked_months_are_saved_as_one(self):
        form = TimelineOnlyForm(
            data={"monthly_timeline": ["2", "5", "11"]},
            instance=self.item,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.item.refresh_from_db()
        self.assertEqual(
            [getattr(self.item, f"timeline_{month}") for month in range(1, 13)],
            [0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0],
        )

    def test_unchecked_months_are_saved_as_zero(self):
        form = TimelineOnlyForm(data={}, instance=self.item)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.item.refresh_from_db()
        self.assertTrue(
            all(
                getattr(self.item, field_name) == 0
                for field_name in REASSESSMENT_TIMELINE_FIELDS
            )
        )

    def test_invalid_month_value_is_rejected(self):
        form = TimelineOnlyForm(
            data={"monthly_timeline": ["2", "99"]},
            instance=self.item,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("monthly_timeline", form.errors)

    def test_numeric_value_other_than_choice_is_rejected(self):
        form = TimelineOnlyForm(
            data={"monthly_timeline": ["6.0"]},
            instance=self.item,
        )
        self.assertFalse(form.is_valid())

    def test_month_labels_are_in_calendar_order(self):
        html = TimelineOnlyForm(instance=self.item).as_p()
        labels = (
            "Januari", "Februari", "Maret", "April", "Mei", "Juni",
            "Juli", "Agustus", "September", "Oktober", "November", "Desember",
        )
        positions = [html.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))

    def test_months_are_grouped_by_quarter(self):
        html = TimelineOnlyForm(instance=self.item).as_p()
        for quarter in ("Q1", "Q2", "Q3", "Q4"):
            self.assertIn(f"<legend>{quarter}</legend>", html)
        self.assertEqual(html.count('class="monthly-quarter-group"'), 4)

    def test_quick_action_buttons_are_not_submit_buttons(self):
        html = TimelineOnlyForm(instance=self.item).as_p()
        self.assertIn(
            '<button type="button" class="button monthly-select-all">',
            html,
        )
        self.assertIn(
            '<button type="button" class="button monthly-clear-all">',
            html,
        )

    def test_buttons_are_scoped_to_nearest_timeline(self):
        js = (
            Path(__file__).parent
            / "static/risk/js/monthly_timeline.js"
        ).read_text()
        self.assertIn('button.closest(".monthly-timeline")', js)
        self.assertNotIn("document.querySelectorAll", js)

    def test_checkbox_labels_have_unique_ids_for_inline_prefixes(self):
        first = TimelineOnlyForm(instance=self.item, prefix="items-0")
        second = TimelineOnlyForm(instance=self.item, prefix="items-1")
        first_html = first.as_p()
        second_html = second.as_p()
        first_id = "id_items-0-monthly_timeline_0_0"
        second_id = "id_items-1-monthly_timeline_0_0"
        self.assertIn(f'id="{first_id}"', first_html)
        self.assertIn(f'for="{first_id}"', first_html)
        self.assertIn(f'id="{second_id}"', second_html)
        self.assertNotIn(f'id="{first_id}"', second_html)

    def test_admin_and_inline_use_same_timeline_form(self):
        model_admin = ReAssessmentItemAdmin(ReAssessmentItem, AdminSite())
        inline = ReAssessmentItemInline(ReAssessmentSummary, AdminSite())
        self.assertIs(model_admin.form, ReAssessmentItemTimelineForm)
        self.assertIs(inline.form, ReAssessmentItemTimelineForm)

    def test_admin_and_inline_expose_one_compact_timeline_field(self):
        self.assertIn("monthly_timeline", REASSESSMENT_ITEM_FIELDS)
        self.assertNotIn("timeline_1", REASSESSMENT_ITEM_FIELDS)
        self.assertNotIn("timeline_12", REASSESSMENT_ITEM_FIELDS)
        self.assertNotIn("monthly_timeline", REASSESSMENT_ITEM_TREATMENT_FIELDS)

    def test_admin_has_dedicated_timeline_fieldset(self):
        model_admin = ReAssessmentItemAdmin(ReAssessmentItem, AdminSite())
        timeline = next(
            options
            for title, options in model_admin.fieldsets
            if title == "TIMELINE PELAKSANAAN RENCANA PERLAKUAN"
        )
        self.assertEqual(timeline["fields"], ("monthly_timeline",))
        self.assertIn("monthly-timeline-fieldset", timeline["classes"])
        self.assertIn(
            "monthly_timeline",
            flatten_fieldsets(model_admin.fieldsets),
        )

    def test_saving_timeline_does_not_change_other_item_data(self):
        original_event = self.item.peristiwa_risiko
        original_number = self.item.no_risiko
        form = TimelineOnlyForm(
            data={"monthly_timeline": ["4"]},
            instance=self.item,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.item.refresh_from_db()
        self.assertEqual(self.item.peristiwa_risiko, original_event)
        self.assertEqual(self.item.no_risiko, original_number)

    def test_media_is_loaded_for_admin_and_inline(self):
        model_admin = ReAssessmentItemAdmin(ReAssessmentItem, AdminSite())
        inline = ReAssessmentItemInline(ReAssessmentSummary, AdminSite())
        for media in (model_admin.media, inline.media):
            self.assertIn("risk/css/monthly_timeline.css", media._css["all"])
            self.assertIn("risk/js/monthly_timeline.js", media._js)

    def test_responsive_css_supports_four_two_and_one_columns(self):
        css = (
            Path(__file__).parent
            / "static/risk/css/monthly_timeline.css"
        ).read_text()
        self.assertIn("repeat(4, minmax(0, 1fr))", css)
        self.assertIn("repeat(2, minmax(0, 1fr))", css)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", css)
