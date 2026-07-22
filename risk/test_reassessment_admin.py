from types import SimpleNamespace

from django.contrib.admin import AdminSite
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from risk.admin import ReAssessmentItemInline
from risk.models import (
    ItemKontrakManajemen,
    KontrakManajemen,
    MasterBagianKM,
    MasterTemplateKM,
    ReAssessmentItem,
    ReAssessmentSummary,
)


class ReAssessmentItemInlineTests(TestCase):
    def setUp(self):
        template = MasterTemplateKM.objects.create(tahun=2026, nama="KM 2026")
        master_bagian = MasterBagianKM.objects.create(
            template=template,
            kode_bagian="A",
            nama_bagian="Kinerja Utama",
            urutan=1,
        )

        setper = Group.objects.create(name="SETPER")
        aga = Group.objects.create(name="BID AGA")
        setper_contract = KontrakManajemen.objects.create(
            judul="SETPER",
            tahun=2026,
            unit_bisnis=setper,
        )
        aga_contract = KontrakManajemen.objects.create(
            judul="VPAGA",
            tahun=2026,
            unit_bisnis=aga,
        )
        self.setper_item = ItemKontrakManajemen.objects.create(
            kontrak=setper_contract,
            master_bagian=master_bagian,
            no_urut=1,
            indikator_kinerja_kunci="KPI SETPER",
        )
        self.aga_item = ItemKontrakManajemen.objects.create(
            kontrak=aga_contract,
            master_bagian=master_bagian,
            no_urut=1,
            indikator_kinerja_kunci="KPI AGA",
        )
        self.summary = ReAssessmentSummary.objects.create(
            judul="Profil Risiko SETPER",
            tahun=2026,
            unit_bisnis=setper,
            kontrak_manajemen=setper_contract,
        )

    def test_km_item_choices_follow_parent_summary_contract(self):
        request = RequestFactory().get(
            f"/admin/risk/reassessmentsummary/{self.summary.pk}/change/"
        )
        request.resolver_match = SimpleNamespace(
            kwargs={"object_id": str(self.summary.pk)}
        )
        inline = ReAssessmentItemInline(ReAssessmentSummary, AdminSite())

        formfield = inline.formfield_for_foreignkey(
            ReAssessmentItem._meta.get_field("km_item"),
            request,
        )

        self.assertQuerySetEqual(
            formfield.queryset,
            [self.setper_item],
        )
        self.assertNotIn(self.aga_item, formfield.queryset)
