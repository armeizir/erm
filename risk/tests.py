from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from risk.models import (
    BagianKontrakManajemen,
    ItemKontrakManajemen,
    KontrakManajemen,
    MasterBagianKM,
    MasterTemplateKM,
    ProfilRisikoKorporatItem,
    ProfilRisikoKorporatSummary,
    ReAssessmentItem,
    ReAssessmentSummary,
    RiskManagementReview,
    RKMItem,
    RKMSummary,
    KPMRSummary,
)


class CorporateRiskItemLabelTests(SimpleTestCase):
    def test_string_contains_item_number_and_risk_event(self):
        summary = ProfilRisikoKorporatSummary(judul="Profil Risiko Korporat 2026", tahun=2026)
        item = ProfilRisikoKorporatItem(
            summary=summary,
            no_item=11,
            peristiwa_risiko="Serangan cyber pada sistem IT/OT",
        )

        label = str(item)

        self.assertIn("#11", label)
        self.assertIn("Serangan cyber pada sistem IT/OT", label)

    def test_string_falls_back_when_risk_event_empty(self):
        item = ProfilRisikoKorporatItem(no_item=11, peristiwa_risiko="")

        label = str(item)

        self.assertIn("#11", label)
        self.assertIn("Peristiwa risiko belum diisi", label)

    def test_dropdown_label_uses_display_label(self):
        summary = ProfilRisikoKorporatSummary(judul="Profil Risiko Korporat 2026", tahun=2026)
        item = ProfilRisikoKorporatItem(
            summary=summary,
            no_item=11,
            peristiwa_risiko="Gangguan operasional sistem",
        )

        class RiskItemChoiceField(forms.ModelChoiceField):
            def label_from_instance(self, obj):
                return obj.get_display_label()

        field = RiskItemChoiceField(queryset=ProfilRisikoKorporatItem.objects.none())

        self.assertIn("Gangguan operasional sistem", field.label_from_instance(item))


class SensitiveEndpointSecurityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="risk-user", password="unused")
        self.user.user_permissions.add(
            Permission.objects.get(codename="view_profilrisikokorporatitem"),
            Permission.objects.get(codename="change_kpmritem"),
        )

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_rcc_export_requires_login(self):
        response = self.client.get(reverse("rcc_export_excel"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_kpmr_review_requires_login(self):
        response = self.client.get(reverse("kpmr_review", args=[1]))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_kpmr_update_is_post_only_for_authenticated_user(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("kpmr_update_item"))

        self.assertEqual(response.status_code, 405)

    def test_kpmr_update_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(
            reverse("kpmr_update_item"),
            data='{"id": 1, "field": "catatan", "value": "ok"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)


class RKMPDFAdminTests(TestCase):
    def test_superuser_can_download_rkm_pdf(self):
        User = get_user_model()
        admin_user = User.objects.create_superuser(username="admin", password="secret")
        unit = Group.objects.create(name="UB TEST")
        template = MasterTemplateKM.objects.create(tahun=2026, nama="Template 2026")
        master_bagian = MasterBagianKM.objects.create(
            template=template,
            kode_bagian="A",
            nama_bagian="Keuangan",
            urutan=1,
        )
        kontrak = KontrakManajemen.objects.create(
            judul="SMTEST",
            tahun=2026,
            unit_bisnis=unit,
            template=template,
        )
        bagian = BagianKontrakManajemen.objects.create(
            kontrak=kontrak,
            kode_bagian="A",
            nama_bagian="Keuangan",
        )
        km_item = ItemKontrakManajemen.objects.create(
            kontrak=kontrak,
            bagian=bagian,
            master_bagian=master_bagian,
            no_urut=1,
            indikator_kinerja_kunci="Optimalisasi Biaya",
            satuan="%",
            bobot=10,
            target="100",
        )
        rkm = RKMSummary.objects.create(
            judul="RKM UB TEST Mei 2026",
            tahun=2026,
            bulan=5,
            unit_bisnis=unit,
            kontrak_manajemen=kontrak,
        )
        RKMItem.objects.create(
            summary=rkm,
            no_item=1,
            km_item=km_item,
            kategori_rkm="A",
            kpi_indikator="Optimalisasi Biaya",
            target_akumulasi="100",
            realisasi_mei="95",
            jumlah_realisasi="95",
            persen_capaian=95,
        )

        client = Client(HTTP_HOST="127.0.0.1")
        client.force_login(admin_user)
        response = client.get(reverse("admin:risk_rkmsummary_pdf", args=[rkm.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_superuser_can_download_unit_risk_profile_pdf(self):
        User = get_user_model()
        admin_user = User.objects.create_superuser(username="admin-profile", password="secret")
        unit = Group.objects.create(name="UB PROFILE")
        template = MasterTemplateKM.objects.create(tahun=2026, nama="Template Profil 2026")
        master_bagian = MasterBagianKM.objects.create(
            template=template,
            kode_bagian="A",
            nama_bagian="Keuangan",
            urutan=1,
        )
        kontrak = KontrakManajemen.objects.create(
            judul="SMPROFILE",
            tahun=2026,
            unit_bisnis=unit,
            template=template,
        )
        bagian = BagianKontrakManajemen.objects.create(
            kontrak=kontrak,
            kode_bagian="A",
            nama_bagian="Keuangan",
        )
        km_item = ItemKontrakManajemen.objects.create(
            kontrak=kontrak,
            bagian=bagian,
            master_bagian=master_bagian,
            no_urut=1,
            indikator_kinerja_kunci="Optimalisasi Biaya",
            satuan="%",
            bobot=10,
            target="100",
        )
        summary = ReAssessmentSummary.objects.create(
            judul="Profil Risiko UB PROFILE",
            tahun=2026,
            unit_bisnis=unit,
            kontrak_manajemen=kontrak,
        )
        ReAssessmentItem.objects.create(
            summary=summary,
            no_item=1,
            km_item=km_item,
            no_risiko=1,
            peristiwa_risiko="Target tidak tercapai",
            deskripsi_peristiwa_risiko="Deskripsi risiko",
            penyebab_risiko="Penyebab",
            rencana_perlakuan_risiko="Mitigasi",
            output_perlakuan_risiko="Output",
            pic="PIC",
        )

        client = Client(HTTP_HOST="127.0.0.1")
        client.force_login(admin_user)
        response = client.get(reverse("admin:risk_reassessmentsummary_pdf", args=[summary.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_kpmr_generation_uses_unique_sequence_for_duplicate_profile_item_numbers(self):
        unit = Group.objects.create(name="UB KPMR")
        template = MasterTemplateKM.objects.create(tahun=2026, nama="Template KPMR 2026")
        master_bagian = MasterBagianKM.objects.create(
            template=template,
            kode_bagian="A",
            nama_bagian="Keuangan",
            urutan=1,
        )
        kontrak = KontrakManajemen.objects.create(
            judul="SMKPMR",
            tahun=2026,
            unit_bisnis=unit,
            template=template,
        )
        bagian = BagianKontrakManajemen.objects.create(
            kontrak=kontrak,
            kode_bagian="A",
            nama_bagian="Keuangan",
        )
        km_item = ItemKontrakManajemen.objects.create(
            kontrak=kontrak,
            bagian=bagian,
            master_bagian=master_bagian,
            no_urut=1,
            indikator_kinerja_kunci="Optimalisasi Biaya",
            satuan="%",
            bobot=10,
            target="100",
        )
        reassessment = ReAssessmentSummary.objects.create(
            judul="Profil Risiko UB KPMR",
            tahun=2026,
            unit_bisnis=unit,
            kontrak_manajemen=kontrak,
        )
        for no_risiko in (1, 2):
            ReAssessmentItem.objects.create(
                summary=reassessment,
                no_item=1,
                km_item=km_item,
                no_risiko=no_risiko,
                peristiwa_risiko=f"Risiko {no_risiko}",
                deskripsi_peristiwa_risiko="Deskripsi risiko",
                penyebab_risiko="Penyebab",
                rencana_perlakuan_risiko="Mitigasi",
                output_perlakuan_risiko="Output",
            )

        kpmr = KPMRSummary.objects.create(
            judul="KPMR UB KPMR 2026",
            tahun=2026,
            unit_bisnis=unit,
            reassessment=reassessment,
        )

        self.assertEqual(list(kpmr.item.order_by("no_item").values_list("no_item", flat=True)), [1, 2])

    def test_superuser_can_download_risk_management_review_pdf(self):
        User = get_user_model()
        admin_user = User.objects.create_superuser(username="admin-review", password="secret")
        pairing = User.objects.create_user(username="pairing", first_name="Pairing", last_name="Officer")
        man_risk = User.objects.create_user(username="manrisk", first_name="Man", last_name="Risk")
        vp_mrk = User.objects.create_user(username="vpmrk", first_name="VP", last_name="MRK")
        unit = Group.objects.create(name="UB REVIEW")
        template = MasterTemplateKM.objects.create(tahun=2026, nama="Template Review 2026")
        master_bagian = MasterBagianKM.objects.create(
            template=template,
            kode_bagian="A",
            nama_bagian="Keuangan",
            urutan=1,
        )
        kontrak = KontrakManajemen.objects.create(
            judul="SMREVIEW",
            tahun=2026,
            unit_bisnis=unit,
            template=template,
        )
        bagian = BagianKontrakManajemen.objects.create(
            kontrak=kontrak,
            kode_bagian="A",
            nama_bagian="Keuangan",
        )
        km_item = ItemKontrakManajemen.objects.create(
            kontrak=kontrak,
            bagian=bagian,
            master_bagian=master_bagian,
            no_urut=1,
            indikator_kinerja_kunci="Optimalisasi Biaya",
            satuan="%",
            bobot=10,
            target="100",
        )
        rkm = RKMSummary.objects.create(
            judul="RKM UB REVIEW Mei 2026",
            tahun=2026,
            bulan=5,
            unit_bisnis=unit,
            kontrak_manajemen=kontrak,
        )
        profil = ReAssessmentSummary.objects.create(
            judul="Profil Risiko UB REVIEW",
            tahun=2026,
            unit_bisnis=unit,
            kontrak_manajemen=kontrak,
            rkm=rkm,
        )
        ReAssessmentItem.objects.create(
            summary=profil,
            no_item=1,
            km_item=km_item,
            no_risiko=1,
            peristiwa_risiko="Target tidak tercapai",
            deskripsi_peristiwa_risiko="Deskripsi risiko",
            penyebab_risiko="Penyebab",
            rencana_perlakuan_risiko="Mitigasi",
            output_perlakuan_risiko="Output",
        )
        kpmr = KPMRSummary.objects.create(
            judul="KPMR UB REVIEW 2026",
            tahun=2026,
            unit_bisnis=unit,
            reassessment=profil,
        )
        review = RiskManagementReview.objects.create(
            title="Review MR UB REVIEW 2026",
            tahun=2026,
            unit_bisnis=unit,
            kontrak_manajemen=kontrak,
            rkm=rkm,
            profil_risiko=profil,
            kpmr=kpmr,
            review_summary="Dokumen telah direview.",
            recommendation="Dapat dilanjutkan untuk tanda tangan.",
            pairing_officer=pairing,
            man_risk=man_risk,
            vp_mrk=vp_mrk,
        )

        client = Client(HTTP_HOST="127.0.0.1")
        client.force_login(admin_user)
        response = client.get(reverse("admin:risk_riskmanagementreview_pdf", args=[review.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
