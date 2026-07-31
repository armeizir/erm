from datetime import date
from io import StringIO

from django.contrib.admin import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import RequestFactory, TestCase

from masterdata.models import (
    OrganizationUnit,
    OrganizationUnitAccessGroup,
    OrganizationUnitUserAssignment,
)
from risk.admin import (
    ReAssessmentItemAdmin,
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
from risk.services.pic import effective_assignments, resolve_import_pic


class PICOnlyForm(ReAssessmentItemTimelineForm):
    class Meta:
        model = ReAssessmentItem
        fields = (
            "pic_organization_unit",
            "pic_user_assignment",
        )


class PICOrganizationRelationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.unit_group = Group.objects.create(name="UB BES")
        cls.other_group = Group.objects.create(name="BID KEU")
        cls.organization = OrganizationUnit.objects.create(
            code="ORG-BES",
            name="UB BES",
        )
        cls.other_organization = OrganizationUnit.objects.create(
            code="ORG-KEU",
            name="BID KEU",
        )
        OrganizationUnitAccessGroup.objects.create(
            organization_unit=cls.organization,
            group=cls.unit_group,
            utama=True,
        )
        OrganizationUnitAccessGroup.objects.create(
            organization_unit=cls.other_organization,
            group=cls.other_group,
            utama=True,
        )
        cls.user = User.objects.create_user(
            username="1234567",
            first_name="Muhammad",
            last_name="Reza",
            email="reza@example.com",
        )
        cls.other_user = User.objects.create_user(username="7654321")
        cls.inactive_user = User.objects.create_user(
            username="inactive.pic",
            is_active=False,
        )
        cls.assignment = OrganizationUnitUserAssignment.objects.create(
            user=cls.user,
            organization_unit=cls.organization,
            tanggal_mulai=date(2026, 1, 1),
        )
        cls.other_assignment = OrganizationUnitUserAssignment.objects.create(
            user=cls.other_user,
            organization_unit=cls.other_organization,
            tanggal_mulai=date(2026, 1, 1),
            utama=False,
        )
        cls.inactive_assignment = OrganizationUnitUserAssignment.objects.create(
            user=cls.other_user,
            organization_unit=cls.organization,
            tanggal_mulai=date(2026, 1, 1),
            aktif=False,
            utama=False,
        )
        cls.inactive_user_assignment = (
            OrganizationUnitUserAssignment.objects.create(
                user=cls.inactive_user,
                organization_unit=cls.organization,
                tanggal_mulai=date(2026, 1, 1),
                utama=False,
            )
        )
        template = MasterTemplateKM.objects.create(
            tahun=2026,
            nama="KM PIC",
        )
        section = MasterBagianKM.objects.create(
            template=template,
            kode_bagian="A",
            nama_bagian="Kinerja",
            urutan=1,
        )
        contract = KontrakManajemen.objects.create(
            judul="KM BES",
            tahun=2026,
            unit_bisnis=cls.unit_group,
            template=template,
        )
        cls.km_item = ItemKontrakManajemen.objects.create(
            kontrak=contract,
            master_bagian=section,
            no_urut=1,
            indikator_kinerja_kunci="KPI",
        )
        cls.summary = ReAssessmentSummary.objects.create(
            judul="Profil Risiko BES",
            tahun=2026,
            unit_bisnis=cls.unit_group,
            kontrak_manajemen=contract,
        )
        cls.item = ReAssessmentItem.objects.create(
            summary=cls.summary,
            no_item=1,
            km_item=cls.km_item,
            no_risiko=1,
            peristiwa_risiko="Risiko",
            deskripsi_peristiwa_risiko="Deskripsi",
            pic="UB BES",
        )

    def form(self, data=None, instance=None):
        return PICOnlyForm(data=data, instance=instance or self.item)

    def test_pic_organization_uses_organization_unit_model(self):
        field = ReAssessmentItem._meta.get_field("pic_organization_unit")
        self.assertIs(field.remote_field.model, OrganizationUnit)

    def test_pic_assignment_uses_assignment_model(self):
        field = ReAssessmentItem._meta.get_field("pic_user_assignment")
        self.assertIs(
            field.remote_field.model,
            OrganizationUnitUserAssignment,
        )

    def test_owner_organization_is_default(self):
        form = self.form()
        self.assertEqual(
            form.initial["pic_organization_unit"],
            self.organization.pk,
        )
        self.assertTrue(form.initial["use_owner_organization"])

    def test_assignment_dropdown_is_filtered_by_organization(self):
        item = self.item
        item.pic_organization_unit = self.organization
        form = self.form(instance=item)
        self.assertIn(
            self.assignment,
            form.fields["pic_user_assignment"].queryset,
        )
        self.assertNotIn(
            self.other_assignment,
            form.fields["pic_user_assignment"].queryset,
        )

    def test_valid_assignment_can_be_saved(self):
        form = self.form(
            {
                "pic_organization_unit": self.organization.pk,
                "pic_user_assignment": self.assignment.pk,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_assignment_from_other_organization_is_rejected(self):
        form = self.form(
            {
                "pic_organization_unit": self.organization.pk,
                "pic_user_assignment": self.other_assignment.pk,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn(
            "PIC Pelaksana tidak memiliki penugasan aktif",
            str(form.errors["pic_user_assignment"]),
        )

    def test_manipulated_post_is_rejected_by_model(self):
        item = self.item
        item.pic_organization_unit = self.organization
        item.pic_user_assignment = self.other_assignment
        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_inactive_assignment_is_rejected(self):
        form = self.form(
            {
                "pic_organization_unit": self.organization.pk,
                "pic_user_assignment": self.inactive_assignment.pk,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("penugasan dan user aktif", str(form.errors))

    def test_inactive_user_is_rejected(self):
        form = self.form(
            {
                "pic_organization_unit": self.organization.pk,
                "pic_user_assignment": self.inactive_user_assignment.pk,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("penugasan dan user aktif", str(form.errors))


    def test_historical_include_never_leaks_assignment_from_other_organization(self):
        assignments = effective_assignments(
            self.organization,
            on_date=date(2026, 6, 1),
            include_assignment_ids=(self.other_assignment.pk,),
        )
        self.assertNotIn(self.other_assignment, assignments)

    def test_model_rejects_inactive_new_assignment(self):
        self.item.pic_organization_unit = self.organization
        self.item.pic_user_assignment = self.inactive_assignment
        with self.assertRaises(ValidationError) as context:
            self.item.full_clean()
        self.assertIn("penugasan dan user aktif", str(context.exception))

    def test_model_rejects_inactive_user_new_assignment(self):
        self.item.pic_organization_unit = self.organization
        self.item.pic_user_assignment = self.inactive_user_assignment
        with self.assertRaises(ValidationError) as context:
            self.item.full_clean()
        self.assertIn("penugasan dan user aktif", str(context.exception))

    def test_assignment_is_optional(self):
        form = self.form(
            {"pic_organization_unit": self.organization.pk}
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_legacy_pic_remains_readable(self):
        self.assertEqual(self.item.pic, "UB BES")
        self.assertEqual(self.item.pic_organization_display, "UB BES")

    def test_relational_pic_display_includes_organization_and_user(self):
        self.item.pic_organization_unit = self.organization
        self.item.pic_user_assignment = self.assignment
        self.assertEqual(
            self.item.pic_display,
            "UB BES — Muhammad Reza",
        )

    def test_historical_assignment_survives_user_transfer(self):
        self.item.pic_organization_unit = self.organization
        self.item.pic_user_assignment = self.assignment
        self.item.save()
        self.assignment.aktif = False
        self.assignment.utama = False
        self.assignment.tanggal_selesai = date(2026, 6, 30)
        self.assignment.save()
        OrganizationUnitUserAssignment.objects.create(
            user=self.user,
            organization_unit=self.other_organization,
            tanggal_mulai=date(2026, 7, 1),
        )
        self.item.refresh_from_db()
        self.assertEqual(
            self.item.pic_user_assignment.organization_unit,
            self.organization,
        )

    def test_existing_inactive_historical_assignment_remains_editable(self):
        self.item.pic_organization_unit = self.organization
        self.item.pic_user_assignment = self.assignment
        self.item.save()
        self.assignment.aktif = False
        self.assignment.utama = False
        self.assignment.tanggal_selesai = date(2026, 6, 30)
        self.assignment.save()
        form = self.form(
            {
                "pic_organization_unit": self.organization.pk,
                "pic_user_assignment": self.assignment.pk,
            },
            instance=self.item,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_dry_run_mapping_does_not_change_data(self):
        output = StringIO()
        call_command("map_legacy_risk_pic", stdout=output)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.pic_organization_unit_id)
        self.assertIn("MODE: DRY-RUN", output.getvalue())

    def test_apply_maps_single_exact_match(self):
        call_command("map_legacy_risk_pic", "--apply", stdout=StringIO())
        self.item.refresh_from_db()
        self.assertEqual(
            self.item.pic_organization_unit,
            self.organization,
        )

    def test_apply_is_idempotent(self):
        call_command("map_legacy_risk_pic", "--apply", stdout=StringIO())
        call_command("map_legacy_risk_pic", "--apply", stdout=StringIO())
        self.assertEqual(
            ReAssessmentItem.objects.filter(
                pk=self.item.pk,
                pic_organization_unit=self.organization,
            ).count(),
            1,
        )

    def test_ambiguous_legacy_value_is_not_mapped(self):
        OrganizationUnit.objects.create(code="ORG-BES-2", name="UB BES")
        call_command("map_legacy_risk_pic", "--apply", stdout=StringIO())
        self.item.refresh_from_db()
        self.assertIsNone(self.item.pic_organization_unit_id)

    def test_unmatched_legacy_value_is_not_mapped(self):
        self.item.pic = "ORGANISASI TIDAK ADA"
        self.item.save(update_fields=["pic"])
        call_command("map_legacy_risk_pic", "--apply", stdout=StringIO())
        self.item.refresh_from_db()
        self.assertIsNone(self.item.pic_organization_unit_id)

    def test_import_resolves_existing_organization_and_assignment(self):
        organization, assignment = resolve_import_pic(
            organization_code=self.organization.code,
            user_email=self.user.email,
        )
        self.assertEqual(organization, self.organization)
        self.assertEqual(assignment, self.assignment)

    def test_import_does_not_create_unknown_master(self):
        before = OrganizationUnit.objects.count()
        organization, assignment = resolve_import_pic(
            organization_code="UNKNOWN",
            user_email="nobody@example.com",
        )
        self.assertIsNone(organization)
        self.assertIsNone(assignment)
        self.assertEqual(OrganizationUnit.objects.count(), before)


    def test_endpoint_rejects_non_get_requests(self):
        request = RequestFactory().post(
            "/admin/risk/reassessmentitem/pic-assignments/",
        )
        request.user = self.user
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        response = ReAssessmentItemAdmin(
            ReAssessmentItem,
            AdminSite(),
        ).pic_assignments_view(request)
        self.assertEqual(response.status_code, 405)

    def test_endpoint_does_not_expose_other_organization(self):
        request_user = get_user_model().objects.create_user(
            username="scoped.user",
            is_staff=True,
        )
        request_user.groups.add(self.unit_group)
        request_user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="risk",
                codename="view_reassessmentitem",
            )
        )
        request = RequestFactory().get(
            "/admin/risk/reassessmentitem/pic-assignments/",
            {"organization_unit": self.other_organization.pk},
        )
        request.user = request_user
        response = ReAssessmentItemAdmin(
            ReAssessmentItem,
            AdminSite(),
        ).pic_assignments_view(request)
        self.assertJSONEqual(response.content, {"results": []})
