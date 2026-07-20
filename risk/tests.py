from django import forms
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.test import RequestFactory
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from risk.admin import CustomUserAdmin
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
from risk.views import _fallback_level_from_score, _fallback_matrix_score


class RiskMatrixReferenceTests(SimpleTestCase):
    def test_scores_follow_reference_matrix(self):
        expected_rows = {
            1: [1, 5, 10, 15, 20],
            2: [2, 6, 11, 16, 21],
            3: [3, 8, 13, 18, 23],
            4: [4, 9, 14, 19, 24],
            5: [7, 12, 17, 22, 25],
        }

        for likelihood, expected in expected_rows.items():
            self.assertEqual(
                [_fallback_matrix_score(impact, likelihood) for impact in range(1, 6)],
                expected,
            )

    def test_levels_follow_reference_score_ranges(self):
        expected = {
            1: "Low",
            4: "Low",
            5: "Low",
            6: "Low to Moderate",
            11: "Low to Moderate",
            12: "Moderate",
            15: "Moderate",
            16: "Moderate to High",
            19: "Moderate to High",
            20: "High",
            25: "High",
        }

        for score, level in expected.items():
            self.assertEqual(_fallback_level_from_score(score)[0], level)


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


class CustomUserAdminTests(TestCase):
    def test_groups_column_is_sortable(self):
        User = get_user_model()
        admin_user = User.objects.create_superuser(username="admin", password="secret")
        target_user = User.objects.create_user(username="risk-user", password="secret")
        group = Group.objects.create(name="BID RISIKO")
        target_user.groups.add(group)
        request = RequestFactory().get("/admin/auth/user/")
        request.user = admin_user
        user_admin = CustomUserAdmin(User, AdminSite())

        queryset = user_admin.get_queryset(request).filter(pk=target_user.pk)
        user = queryset.order_by("groups_order").first()

        self.assertEqual(CustomUserAdmin.groups_display.admin_order_field, "groups_order")
        self.assertEqual(user.groups_order, "BID RISIKO")
        self.assertEqual(user_admin.groups_display(user), "BID RISIKO")


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

    def test_superuser_can_download_rkm_pdf_for_previous_month(self):
        User = get_user_model()
        admin_user = User.objects.create_superuser(username="admin-rkm-month", password="secret")
        unit = Group.objects.create(name="UB RKM MONTH")
        template = MasterTemplateKM.objects.create(tahun=2026, nama="Template RKM Month 2026")
        master_bagian = MasterBagianKM.objects.create(
            template=template,
            kode_bagian="A",
            nama_bagian="Keuangan",
            urutan=1,
        )
        kontrak = KontrakManajemen.objects.create(
            judul="SMRKM-MONTH",
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
            target_april="100",
            realisasi_april="90",
            target_mei="100",
            realisasi_mei="95",
        )

        client = Client(HTTP_HOST="127.0.0.1")
        client.force_login(admin_user)
        response = client.get(
            reverse("admin:risk_rkmsummary_pdf", args=[rkm.pk]),
            {"bulan": 4},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("RKM_UB RKM MONTH_4_2026.pdf", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_superuser_can_download_km_pdf_for_previous_month_from_later_rkm(self):
        User = get_user_model()
        admin_user = User.objects.create_superuser(username="admin-km-month", password="secret")
        unit = Group.objects.create(name="UB KM MONTH")
        template = MasterTemplateKM.objects.create(tahun=2026, nama="Template KM Month 2026")
        master_bagian = MasterBagianKM.objects.create(
            template=template,
            kode_bagian="A",
            nama_bagian="Keuangan",
            urutan=1,
        )
        kontrak = KontrakManajemen.objects.create(
            judul="SMKM-MONTH",
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
            target_april="100",
            realisasi_april="90",
            target_mei="100",
            realisasi_mei="95",
        )

        client = Client(HTTP_HOST="127.0.0.1")
        client.force_login(admin_user)
        response = client.get(
            reverse("admin:risk_kontrakmanajemen_pdf", args=[kontrak.pk]),
            {"tahun": 2026, "bulan": 4},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_generate_rkm_items_skips_existing_and_uses_next_available_number(self):
        unit = Group.objects.create(name="UB RKM GENERATE")
        template = MasterTemplateKM.objects.create(tahun=2026, nama="Template RKM Generate 2026")
        master_bagian = MasterBagianKM.objects.create(
            template=template,
            kode_bagian="A",
            nama_bagian="Keuangan",
            urutan=1,
        )
        kontrak = KontrakManajemen.objects.create(
            judul="SMRKM-GENERATE",
            tahun=2026,
            unit_bisnis=unit,
            template=template,
        )
        bagian = BagianKontrakManajemen.objects.create(
            kontrak=kontrak,
            kode_bagian="A",
            nama_bagian="Keuangan",
        )
        km_item_1 = ItemKontrakManajemen.objects.create(
            kontrak=kontrak,
            bagian=bagian,
            master_bagian=master_bagian,
            no_urut=1,
            indikator_kinerja_kunci="Optimalisasi Biaya",
            satuan="%",
            bobot=10,
            target="100",
        )
        ItemKontrakManajemen.objects.create(
            kontrak=kontrak,
            bagian=bagian,
            master_bagian=master_bagian,
            no_urut=2,
            indikator_kinerja_kunci="Pengendalian Piutang",
            satuan="Hari",
            bobot=10,
            target="30",
        )
        rkm = RKMSummary.objects.create(
            judul="RKM UB Generate Mei 2026",
            tahun=2026,
            bulan=5,
            unit_bisnis=unit,
            kontrak_manajemen=kontrak,
        )
        RKMItem.objects.create(
            summary=rkm,
            no_item=1,
            km_item=km_item_1,
            kategori_rkm="A",
            kpi_indikator="Optimalisasi Biaya",
        )

        created_count = rkm.generate_items_from_km()

        self.assertEqual(created_count, 1)
        self.assertEqual(
            list(rkm.item.order_by("no_item").values_list("no_item", flat=True)),
            [1, 2],
        )

    def test_rkm_item_calculates_monthly_total_and_percentage(self):
        unit = Group.objects.create(name="UB RKM CALC")
        template = MasterTemplateKM.objects.create(tahun=2026, nama="Template RKM Calc 2026")
        master_bagian = MasterBagianKM.objects.create(
            template=template,
            kode_bagian="A",
            nama_bagian="Keuangan",
            urutan=1,
        )
        kontrak = KontrakManajemen.objects.create(
            judul="SMRKM-CALC",
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
            judul="RKM UB Calc Mei 2026",
            tahun=2026,
            bulan=5,
            unit_bisnis=unit,
            kontrak_manajemen=kontrak,
        )

        item = RKMItem.objects.create(
            summary=rkm,
            no_item=1,
            km_item=km_item,
            kategori_rkm="A",
            target_mei="80",
            realisasi_mei="81",
        )

        self.assertEqual(item.jumlah_realisasi, "81")
        self.assertEqual(str(item.persen_capaian), "101.25")

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
