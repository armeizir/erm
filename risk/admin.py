from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin, UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html

from masterdata.models import MasterBUMN

from decimal import Decimal

from .models import (
    KontrakManajemen,
    BagianKontrakManajemen,
    ItemKontrakManajemen,
    RKMSummary,
    RKMItem,
    ReAssessmentSummary,
    ReAssessmentItem,
    KPMRSummary,
    KPMRItem,
    ProfilRisikoKorporatSummary,
    ProfilRisikoKorporatItem,
    ProfilRisikoKorporatPenyebab,  # 🔥 WAJIB TAMBAH
    ProfilRisikoKorporatSumber,
    SasaranKBUMN,
    TaksonomiT3,
    KategoriRisiko,
    MasterJenisExistingControl,
    MasterEfektivitasKontrol,
    MasterKategoriDampak,
    MasterSkalaDampak,
    MasterSkalaProbabilitas,
    MasterOpsiPerlakuanRisiko,
    MasterJenisRencanaPerlakuanRisiko,
    MasterPosAnggaran,
    MasterJenisProgramRKAP,
    MasterLevelRisiko,
    RiskMatrix,
    RiskMatrixCell,
    PenugasanUnitBisnis,
    RisikoInherenKuantitatif,
    RencanaPerlakuanRisikoKorporat,
    KPMRPeriode,
    KPMRIndikatorResmi,
    KPMRSubIndikatorResmi,
    KinerjaPeriode,
    KinerjaIndikator,
    KompositRisikoTriwulan,
    RoadmapProgram,
    RoadmapPenilaianSemester,
)
from riskproject.admin_site import risk_admin_site


admin.site.site_header = "Manajemen Risiko PLN Batam"
admin.site.site_title = "Manajemen Risiko PLN Batam"
admin.site.index_title = "Dashboard Manajemen Risiko"


# =========================================================
# AUTH / GROUP
# =========================================================

try:
    admin.site.unregister(Group)
except admin.sites.NotRegistered:
    pass

try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

Group._meta.verbose_name = "Bidang / Unit Bisnis"
Group._meta.verbose_name_plural = "Bidang / Unit Bisnis"


class PenugasanUnitBisnisUserInline(admin.TabularInline):
    model = PenugasanUnitBisnis
    fk_name = "user"
    extra = 0
    autocomplete_fields = ("unit_bisnis",)
    fields = ("unit_bisnis", "peran", "aktif", "catatan")
    ordering = ("unit_bisnis", "peran")


class PenugasanUnitBisnisGroupInline(admin.TabularInline):
    model = PenugasanUnitBisnis
    fk_name = "unit_bisnis"
    extra = 0
    autocomplete_fields = ("user",)
    fields = ("user", "peran", "aktif", "catatan")
    ordering = ("peran", "user")


@admin.register(Group)
class CustomGroupAdmin(BaseGroupAdmin):
    inlines = [PenugasanUnitBisnisGroupInline]
    list_display = ("name",)
    search_fields = ("name",)
    ordering = ("name",)

    def get_queryset(self, request):
        return super().get_queryset(request).order_by("name")


@admin.register(User)
class CustomUserAdmin(BaseUserAdmin):
    inlines = [PenugasanUnitBisnisUserInline]
    list_display = BaseUserAdmin.list_display + ("is_staff",)


@admin.register(PenugasanUnitBisnis)
class PenugasanUnitBisnisAdmin(admin.ModelAdmin):
    list_display = ("user", "unit_bisnis", "peran", "aktif", "dibuat_pada")
    list_filter = ("peran", "aktif", "unit_bisnis")
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "user__email",
        "unit_bisnis__name",
    )
    autocomplete_fields = ("user", "unit_bisnis")
    ordering = ("unit_bisnis__name", "peran", "user__username")




@admin.register(MasterKategoriDampak)
class MasterKategoriDampakAdmin(admin.ModelAdmin):
    list_display = ("nama", "aktif", "urutan")
    list_editable = ("aktif", "urutan")
    search_fields = ("nama",)
    ordering = ("urutan", "nama")


@admin.register(MasterSkalaDampak)
class MasterSkalaDampakAdmin(admin.ModelAdmin):
    list_display = ("nama", "aktif", "urutan")
    list_editable = ("aktif", "urutan")
    search_fields = ("nama",)
    ordering = ("urutan", "nama")


@admin.register(MasterSkalaProbabilitas)
class MasterSkalaProbabilitasAdmin(admin.ModelAdmin):
    list_display = ("nama", "aktif", "urutan")
    list_editable = ("aktif", "urutan")
    search_fields = ("nama",)
    ordering = ("urutan", "nama")


@admin.register(MasterOpsiPerlakuanRisiko)
class MasterOpsiPerlakuanRisikoAdmin(admin.ModelAdmin):
    list_display = ("nama", "aktif", "urutan")
    list_editable = ("aktif", "urutan")
    search_fields = ("nama",)
    ordering = ("urutan", "nama")


@admin.register(MasterJenisRencanaPerlakuanRisiko)
class MasterJenisRencanaPerlakuanRisikoAdmin(admin.ModelAdmin):
    list_display = ("nama", "aktif", "urutan")
    list_editable = ("aktif", "urutan")
    search_fields = ("nama",)
    ordering = ("urutan", "nama")


@admin.register(MasterPosAnggaran)
class MasterPosAnggaranAdmin(admin.ModelAdmin):
    list_display = ("nama", "aktif", "urutan")
    list_editable = ("aktif", "urutan")
    search_fields = ("nama",)
    ordering = ("urutan", "nama")


@admin.register(MasterJenisProgramRKAP)
class MasterJenisProgramRKAPAdmin(admin.ModelAdmin):
    list_display = ("nama", "aktif", "urutan")
    list_editable = ("aktif", "urutan")
    search_fields = ("nama",)
    ordering = ("urutan", "nama")


@admin.register(MasterJenisExistingControl)
class MasterJenisExistingControlAdmin(admin.ModelAdmin):
    list_display = ("nama", "aktif", "urutan")
    list_editable = ("aktif", "urutan")
    search_fields = ("nama",)
    ordering = ("urutan", "nama")


@admin.register(MasterEfektivitasKontrol)
class MasterEfektivitasKontrolAdmin(admin.ModelAdmin):
    list_display = ("nama", "aktif", "urutan")
    list_editable = ("aktif", "urutan")
    search_fields = ("nama",)
    ordering = ("urutan", "nama")


@admin.register(MasterLevelRisiko)
class MasterLevelRisikoAdmin(admin.ModelAdmin):
    list_display = ("kode", "nama", "urutan", "aktif")
    search_fields = ("kode", "nama")
    list_filter = ("aktif",)
    ordering = ("urutan", "nama")


class RiskMatrixCellInline(admin.TabularInline):
    model = RiskMatrixCell
    extra = 0


@admin.register(RiskMatrix)
class RiskMatrixAdmin(admin.ModelAdmin):
    list_display = ("kode", "nama", "ukuran", "is_default", "aktif")
    list_filter = ("aktif", "is_default")
    search_fields = ("kode", "nama")
    ordering = ("kode", "nama")
    inlines = [RiskMatrixCellInline]


# =========================================================
# MASTER DATA
# =========================================================

@admin.register(TaksonomiT3)
class TaksonomiT3Admin(admin.ModelAdmin):
    list_display = ("kode", "nama", "aktif")
    search_fields = ("kode", "nama")
    list_filter = ("aktif",)
    ordering = ("kode", "nama")


@admin.register(KategoriRisiko)
class KategoriRisikoAdmin(admin.ModelAdmin):
    list_display = ("kode", "nama", "aktif")
    search_fields = ("kode", "nama")
    list_filter = ("aktif",)
    ordering = ("kode", "nama")


@admin.register(SasaranKBUMN)
class SasaranKBUMNAdmin(admin.ModelAdmin):
    list_display = ("kode", "nama", "aktif")
    search_fields = ("kode", "nama")
    list_filter = ("aktif",)
    ordering = ("kode", "nama")


@admin.register(MasterBUMN)
class MasterBUMNAdmin(admin.ModelAdmin):
    list_display = ("nama", "kode")
    search_fields = ("nama", "kode")
    ordering = ("nama",)


# =========================================================
# KONTRAK MANAJEMEN
# =========================================================

class BagianKontrakInline(admin.TabularInline):
    model = BagianKontrakManajemen
    extra = 0
    fields = ("kode_bagian", "nama_bagian")
    show_change_link = False
    verbose_name = ""
    verbose_name_plural = "Bagian Kontrak Manajemen"

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        formset.form.__str__ = lambda self: ""
        return formset


@admin.register(KontrakManajemen)
class KontrakManajemenAdmin(admin.ModelAdmin):
    list_display = ("judul", "tahun", "unit_bisnis", "status", "dibuat_pada")
    list_filter = ("tahun", "status", "unit_bisnis")
    search_fields = ("judul", "unit_bisnis__name")
    ordering = ("-tahun", "judul")
    inlines = [BagianKontrakInline]


class ItemKontrakInline(admin.TabularInline):
    model = ItemKontrakManajemen
    extra = 0
    fields = (
        "no_urut",
        "indikator_kinerja_kunci",
        "formula",
        "satuan",
        "target",
        "bobot",
    )
    ordering = ("no_urut",)


@admin.register(BagianKontrakManajemen)
class BagianKontrakManajemenAdmin(admin.ModelAdmin):
    list_display = ("kontrak", "kode_bagian", "nama_bagian")
    list_filter = ("kontrak__tahun", "kontrak__unit_bisnis")
    search_fields = ("kode_bagian", "nama_bagian", "kontrak__judul")
    ordering = ("kontrak", "kode_bagian", "nama_bagian")
    inlines = [ItemKontrakInline]


@admin.register(ItemKontrakManajemen)
class ItemKontrakManajemenAdmin(admin.ModelAdmin):
    list_display = (
        "bagian",
        "no_urut",
        "indikator_kinerja_kunci",
        "formula",
        "satuan",
        "bobot",
        "target",
    )
    list_filter = (
        "bagian__kontrak__tahun",
        "bagian__kontrak__unit_bisnis",
    )
    search_fields = (
        "indikator_kinerja_kunci",
        "formula",
        "satuan",
        "target",
        "bagian__nama_bagian",
        "bagian__kontrak__judul",
    )
    ordering = ("bagian", "no_urut")
    fields = (
        "bagian",
        "no_urut",
        "indikator_kinerja_kunci",
        "formula",
        "satuan",
        "target",
        "bobot",
    )


# =========================================================
# RKM
# =========================================================

class RKMItemInline(admin.TabularInline):
    model = RKMItem
    extra = 0
    fields = (
        "no_item",
        "km_item",
        "sasaran",
        "target_bulanan",
        "realisasi",
        "deviasi",
        "keterangan",
    )
    ordering = ("no_item",)


@admin.register(RKMSummary)
class RKMSummaryAdmin(admin.ModelAdmin):
    list_display = (
        "judul",
        "tahun",
        "bulan",
        "unit_bisnis",
        "kontrak_manajemen",
        "status",
        "status_pengajuan",
        "generate_button",
    )
    list_filter = ("tahun", "bulan", "status", "status_pengajuan", "unit_bisnis")
    search_fields = ("judul", "unit_bisnis__name", "kontrak_manajemen__judul")
    ordering = ("-tahun", "bulan", "judul")
    inlines = [RKMItemInline]

    fieldsets = (
        ("Informasi Utama", {
            "fields": (
                "judul",
                "tahun",
                "bulan",
                "unit_bisnis",
                "kontrak_manajemen",
                "status",
            )
        }),
        ("Periode", {
            "fields": (
                "tanggal_mulai",
                "tanggal_selesai",
            )
        }),
        ("Pengajuan", {
            "fields": (
                "pic",
                "deadline_pengajuan",
                "tanggal_pengajuan",
                "status_pengajuan",
            )
        }),
    )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:rkm_id>/generate-items/",
                self.admin_site.admin_view(self.generate_items_view),
                name="risk_rkmsummary_generate_items",
            ),
        ]
        return custom_urls + urls

    def generate_button(self, obj):
        url = reverse("admin:risk_rkmsummary_generate_items", args=[obj.pk])
        return format_html('<a class="button" href="{}">Generate RKM dari KM</a>', url)
    generate_button.short_description = "Generate"

    def generate_items_view(self, request, rkm_id, *args, **kwargs):
        rkm = get_object_or_404(RKMSummary, pk=rkm_id)
        created_count = rkm.generate_items_from_km()

        self.message_user(
            request,
            f"Berhasil generate {created_count} item RKM dari KM.",
            level=messages.SUCCESS,
        )

        change_url = reverse("admin:risk_rkmsummary_change", args=[rkm.pk])
        return redirect(change_url)


@admin.register(RKMItem)
class RKMItemAdmin(admin.ModelAdmin):
    list_display = (
        "summary",
        "no_item",
        "km_item",
        "sasaran",
        "target_bulanan",
        "realisasi",
        "deviasi",
    )
    list_filter = ("summary__tahun", "summary__bulan", "summary__unit_bisnis")
    search_fields = (
        "summary__judul",
        "km_item__indikator_kinerja_kunci",
        "sasaran",
    )
    ordering = ("summary", "no_item")


# =========================================================
# RE-ASSESSMENT
# =========================================================

class ReAssessmentItemInline(admin.TabularInline):
    model = ReAssessmentItem
    extra = 0
    ordering = ("no_item",)
    autocomplete_fields = (
        "km_item",
        "taksonomi_t3",
        "sasaran_kbumn",
        "kategori_risiko",
        "jenis_existing_control",
        "penilaian_efektivitas_kontrol",
        "kategori_dampak",
        "opsi_perlakuan_risiko",
        "pos_anggaran",
        "jenis_program_dalam_rkap",
    )
    fields = (
        "no_item",
        "km_item",
        "taksonomi_t3",
        "sasaran_kbumn",
        "kategori_risiko",
        "no_risiko",
        "peristiwa_risiko",
        "deskripsi_peristiwa_risiko",
        "no_penyebab_risiko",
        "kode_penyebab_risiko",
        "penyebab_risiko",
        "key_risk_indicators",
        "unit_satuan_kri",
        "threshold_aman",
        "threshold_hati_hati",
        "threshold_bahaya",
        "jenis_existing_control",
        "existing_control",
        "penilaian_efektivitas_kontrol",
        "kategori_dampak",
        "deskripsi_dampak",
        "perkiraan_waktu_terpapar_risiko",
        "asumsi_perhitungan_dampak",
        "nilai_dampak",
        "nilai_dampak_q1",
        "nilai_dampak_q2",
        "nilai_dampak_q3",
        "nilai_dampak_q4",
        "skala_dampak_q1",
        "skala_dampak_q2",
        "skala_dampak_q3",
        "skala_dampak_q4",
        "nilai_probabilitas",
        "nilai_probabilitas_q1",
        "nilai_probabilitas_q2",
        "nilai_probabilitas_q3",
        "nilai_probabilitas_q4",
        "skala_probabilitas",
        "skala_probabilitas_q1",
        "skala_probabilitas_q2",
        "skala_probabilitas_q3",
        "skala_probabilitas_q4",
        "eksposur_risiko_q1",
        "eksposur_risiko_q2",
        "eksposur_risiko_q3",
        "eksposur_risiko_q4",
        "skala_risiko_q1",
        "skala_risiko_q2",
        "skala_risiko_q3",
        "skala_risiko_q4",
        "level_nilai_risiko_q1",
        "level_nilai_risiko_q2",
        "level_nilai_risiko_q3",
        "level_nilai_risiko_q4",
        "opsi_perlakuan_risiko",
        "jenis_rencana_perlakuan_risiko",
        "rencana_perlakuan_risiko",
        "output_perlakuan_risiko",
        "biaya_perlakuan_risiko",
        "pos_anggaran",
        "prk",
        "jenis_program_dalam_rkap",
        "pic",
        "timeline_1",
        "timeline_2",
        "timeline_3",
        "timeline_4",
        "timeline_5",
        "timeline_6",
        "timeline_7",
        "timeline_8",
        "timeline_9",
        "timeline_10",
        "timeline_11",
        "timeline_12",
    )
    readonly_fields = (
        "kode_penyebab_risiko",
        "nilai_dampak_q1",
        "nilai_probabilitas_q1",
        "nilai_probabilitas_q2",
        "nilai_probabilitas_q3",
        "nilai_probabilitas_q4",
        "eksposur_risiko_q1",
        "eksposur_risiko_q2",
        "eksposur_risiko_q3",
        "eksposur_risiko_q4",
        "skala_risiko_q1",
        "skala_risiko_q2",
        "skala_risiko_q3",
        "skala_risiko_q4",
        "level_nilai_risiko_q1",
        "level_nilai_risiko_q2",
        "level_nilai_risiko_q3",
        "level_nilai_risiko_q4",
    )

@admin.register(ReAssessmentSummary)
class ReAssessmentSummaryAdmin(admin.ModelAdmin):
    list_display = (
        "judul",
        "tahun",
        "unit_bisnis",
        "kontrak_manajemen",
        "dibuat_pada",
    )
    list_filter = ("tahun", "unit_bisnis")
    search_fields = ("judul", "unit_bisnis__name", "kontrak_manajemen__judul")
    ordering = ("-tahun", "judul")
    inlines = [ReAssessmentItemInline]


@admin.register(ReAssessmentItem)
class ReAssessmentItemAdmin(admin.ModelAdmin):
    fields = (
        "summary",
        "no_item",
        "km_item",
        "taksonomi_t3",
        "sasaran_kbumn",
        "kategori_risiko",
        "no_risiko",
        "peristiwa_risiko",
        "deskripsi_peristiwa_risiko",
        "no_penyebab_risiko",
        "kode_penyebab_risiko",
        "penyebab_risiko",
        "key_risk_indicators",
        "unit_satuan_kri",
        "threshold_aman",
        "threshold_hati_hati",
        "threshold_bahaya",
        "jenis_existing_control",
        "existing_control",
        "penilaian_efektivitas_kontrol",
        "kategori_dampak",
        "deskripsi_dampak",
        "perkiraan_waktu_terpapar_risiko",
        "asumsi_perhitungan_dampak",
        "nilai_dampak",
        "nilai_dampak_q1",
        "nilai_dampak_q2",
        "nilai_dampak_q3",
        "nilai_dampak_q4",
        "skala_dampak_q1",
        "skala_dampak_q2",
        "skala_dampak_q3",
        "skala_dampak_q4",
        "nilai_probabilitas",
        "nilai_probabilitas_q1",
        "nilai_probabilitas_q2",
        "nilai_probabilitas_q3",
        "nilai_probabilitas_q4",
        "skala_probabilitas",
        "skala_probabilitas_q1",
        "skala_probabilitas_q2",
        "skala_probabilitas_q3",
        "skala_probabilitas_q4",
        "eksposur_risiko_q1",
        "eksposur_risiko_q2",
        "eksposur_risiko_q3",
        "eksposur_risiko_q4",
        "skala_risiko_q1",
        "skala_risiko_q2",
        "skala_risiko_q3",
        "skala_risiko_q4",
        "level_nilai_risiko_q1",
        "level_nilai_risiko_q2",
        "level_nilai_risiko_q3",
        "level_nilai_risiko_q4",
        "opsi_perlakuan_risiko",
        "jenis_rencana_perlakuan_risiko",
        "rencana_perlakuan_risiko",
        "output_perlakuan_risiko",
        "biaya_perlakuan_risiko",
        "pos_anggaran",
        "prk",
        "jenis_program_dalam_rkap",
        "pic",
        "timeline_1",
        "timeline_2",
        "timeline_3",
        "timeline_4",
        "timeline_5",
        "timeline_6",
        "timeline_7",
        "timeline_8",
        "timeline_9",
        "timeline_10",
        "timeline_11",
        "timeline_12",
    )
    readonly_fields = (
        "kode_penyebab_risiko",
        "nilai_dampak_q1",
        "nilai_probabilitas_q1",
        "nilai_probabilitas_q2",
        "nilai_probabilitas_q3",
        "nilai_probabilitas_q4",
        "eksposur_risiko_q1",
        "eksposur_risiko_q2",
        "eksposur_risiko_q3",
        "eksposur_risiko_q4",
        "skala_risiko_q1",
        "skala_risiko_q2",
        "skala_risiko_q3",
        "skala_risiko_q4",
        "level_nilai_risiko_q1",
        "level_nilai_risiko_q2",
        "level_nilai_risiko_q3",
        "level_nilai_risiko_q4",
    )
    list_display = (
        "summary",
        "no_item",
        "unit_bisnis_summary",
        "km_item",
        "sasaran_kbumn",
        "taksonomi_t3",
        "kategori_risiko",
        "no_risiko",
    )
    list_filter = (
        "summary__tahun",
        "summary__unit_bisnis",
        "sasaran_kbumn",
        "taksonomi_t3",
        "kategori_risiko",
    )
    search_fields = (
        "peristiwa_risiko",
        "deskripsi_peristiwa_risiko",
        "km_item__indikator_kinerja_kunci",
        "sasaran_kbumn__kode",
        "sasaran_kbumn__nama",
        "taksonomi_t3__kode",
        "taksonomi_t3__nama",
        "kategori_risiko__kode",
        "kategori_risiko__nama",
        "summary__judul",
        "summary__unit_bisnis__name",
    )
    ordering = ("summary", "no_item")
    autocomplete_fields = (
        "summary",
        "km_item",
        "taksonomi_t3",
        "sasaran_kbumn",
        "kategori_risiko",
        "jenis_existing_control",
        "penilaian_efektivitas_kontrol",
        "kategori_dampak",
        "opsi_perlakuan_risiko",
        "pos_anggaran",
        "jenis_program_dalam_rkap",
    )

    def unit_bisnis_summary(self, obj):
        return obj.summary.unit_bisnis if obj.summary_id else "-"
    unit_bisnis_summary.short_description = "Bidang / Unit Bisnis"

# =========================================================
# KPMR
# =========================================================

class KPMRItemInline(admin.TabularInline):
    model = KPMRItem
    extra = 0
    can_delete = False

    fields = (
        "no_item",
        "reassessment_item",
        "perlakuan_risiko",
        "bukti",
        "nilai_kpmr",
        "status_kpmr",
        "catatan",
    )

    readonly_fields = (
        "no_item",
        "reassessment_item",
        "perlakuan_risiko",
        "bukti",
        "nilai_kpmr",
        "status_kpmr",
        "catatan",
    )

    ordering = ("no_item",)

    def has_add_permission(self, request, obj=None):
        return False

@admin.register(KPMRSummary)
class KPMRSummaryAdmin(admin.ModelAdmin):
    list_display = (
        "judul",
        "tahun",
        "unit_bisnis",
        "reassessment",
        "dibuat_pada",
    )
    list_filter = ("tahun", "unit_bisnis")
    search_fields = ("judul", "unit_bisnis__name", "reassessment__judul")
    ordering = ("-tahun", "judul")
    readonly_fields = ("dibuat_pada",)

    inlines = [KPMRItemInline]

    fieldsets = (
        ("Informasi Utama", {
            "fields": (
                "judul",
                "tahun",
                "unit_bisnis",
                "reassessment",
                "dibuat_pada",
            )
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj and obj.reassessment_id:
            readonly.extend(["unit_bisnis", "tahun"])
        return readonly

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        self.message_user(
            request,
            "KPMR berhasil disimpan dan item dihitung otomatis dari Re-Assessment.",
            level=messages.SUCCESS,
        )

@admin.register(KPMRItem)
class KPMRItemAdmin(admin.ModelAdmin):
    list_display = (
        "summary",
        "no_item",
        "reassessment_item",
        "status_kpmr",
        "nilai_kpmr",
    )
    list_filter = (
        "summary__tahun",
        "summary__unit_bisnis",
        "status_kpmr",
    )
    search_fields = (
        "reassessment_item__peristiwa_risiko",
        "perlakuan_risiko",
        "catatan",
    )
    ordering = ("summary", "no_item")
    readonly_fields = (
        "summary",
        "no_item",
        "reassessment_item",
        "perlakuan_risiko",
        "bukti",
        "nilai_kpmr",
        "status_kpmr",
        "catatan",
    )

    def has_add_permission(self, request):
        return False

# =========================================================
# KPMR PLN 2026 (RESMI)
# =========================================================

class KPMRSubIndikatorResmiInline(admin.TabularInline):
    model = KPMRSubIndikatorResmi
    extra = 0
    fields = (
        "kode",
        "nama",
        "bobot",
        "jawaban",
        "hasil",
        "skor",
        "keterangan",
    )
    ordering = ("kode",)


class KPMRIndikatorResmiInline(admin.TabularInline):
    model = KPMRIndikatorResmi
    extra = 0
    fields = (
        "kode",
        "nama",
        "bobot",
        "hasil",
        "skor",
        "dokumen_referensi",
        "keterangan",
    )
    ordering = ("kode",)
    show_change_link = True


@admin.register(KPMRPeriode)
class KPMRPeriodeAdmin(admin.ModelAdmin):
    list_display = (
        "tahun",
        "triwulan",
        "unit_bisnis",
        "status",
        "skor_total",
        "rating",
        "dibuat_pada",
    )
    list_filter = ("tahun", "triwulan", "status", "rating", "unit_bisnis")
    search_fields = ("unit_bisnis__name", "catatan")
    ordering = ("-tahun", "triwulan", "unit_bisnis__name")
    inlines = [KPMRIndikatorResmiInline]


@admin.register(KPMRIndikatorResmi)
class KPMRIndikatorResmiAdmin(admin.ModelAdmin):
    list_display = (
        "periode",
        "kode",
        "nama",
        "bobot",
        "hasil",
        "skor",
    )
    list_filter = ("kode", "periode__tahun", "periode__triwulan", "periode__unit_bisnis")
    search_fields = ("nama", "periode__unit_bisnis__name")
    ordering = ("periode", "kode")
    inlines = [KPMRSubIndikatorResmiInline]


@admin.register(KPMRSubIndikatorResmi)
class KPMRSubIndikatorResmiAdmin(admin.ModelAdmin):
    list_display = (
        "indikator",
        "kode",
        "nama",
        "bobot",
        "hasil",
        "skor",
    )
    list_filter = (
        "kode",
        "indikator__periode__tahun",
        "indikator__periode__triwulan",
        "indikator__periode__unit_bisnis",
    )
    search_fields = ("nama", "indikator__periode__unit_bisnis__name")
    ordering = ("indikator", "kode")


class KinerjaIndikatorInline(admin.TabularInline):
    model = KinerjaIndikator
    extra = 0
    fields = ("nama", "bobot", "hasil", "skor", "keterangan")
    ordering = ("nama",)


@admin.register(KinerjaPeriode)
class KinerjaPeriodeAdmin(admin.ModelAdmin):
    list_display = (
        "tahun",
        "triwulan",
        "unit_bisnis",
        "skor_total",
        "rating",
    )
    list_filter = ("tahun", "triwulan", "rating", "unit_bisnis")
    search_fields = ("unit_bisnis__name", "catatan")
    ordering = ("-tahun", "triwulan", "unit_bisnis__name")
    inlines = [KinerjaIndikatorInline]


@admin.register(KinerjaIndikator)
class KinerjaIndikatorAdmin(admin.ModelAdmin):
    list_display = ("periode", "nama", "bobot", "hasil", "skor")
    list_filter = ("nama", "periode__tahun", "periode__triwulan", "periode__unit_bisnis")
    search_fields = ("periode__unit_bisnis__name",)
    ordering = ("periode", "nama")


@admin.register(KompositRisikoTriwulan)
class KompositRisikoTriwulanAdmin(admin.ModelAdmin):
    list_display = (
        "periode_kpmr",
        "periode_kinerja",
        "skor_kpmr",
        "skor_kinerja",
        "peringkat_komposit",
    )
    search_fields = (
        "periode_kpmr__unit_bisnis__name",
        "periode_kinerja__unit_bisnis__name",
        "catatan_review_spi",
    )
    ordering = ("-periode_kpmr__tahun", "periode_kpmr__triwulan")


@admin.register(RoadmapProgram)
class RoadmapProgramAdmin(admin.ModelAdmin):
    list_display = ("tahun", "nomor_urut", "nama_program", "aktif")
    list_filter = ("tahun", "aktif")
    search_fields = ("nama_program",)
    ordering = ("tahun", "nomor_urut")


@admin.register(RoadmapPenilaianSemester)
class RoadmapPenilaianSemesterAdmin(admin.ModelAdmin):
    list_display = (
        "tahun",
        "semester",
        "unit_bisnis",
        "program",
        "nilai_kuantitas",
        "nilai_kualitas",
        "nilai_waktu",
        "nilai_program",
    )
    list_filter = ("tahun", "semester", "unit_bisnis")
    search_fields = ("unit_bisnis__name", "program__nama_program", "catatan")
    ordering = ("-tahun", "semester", "unit_bisnis__name", "program__nomor_urut")


# =========================================================
# PROFIL RISIKO KORPORAT
# =========================================================

class ProfilRisikoKorporatItemInline(admin.TabularInline):
    model = ProfilRisikoKorporatItem
    extra = 0
    ordering = ("no_item",)
    fields = (
        "no_item",
        "no_risiko",
        "bumn",
        "sasaran_korporat",
        "sasaran_kbumn",
        "kategori_risiko",
        "taksonomi_t3",
        "peristiwa_risiko",
        "deskripsi_peristiwa_risiko",
        "dampak",
        "kemungkinan",
        "level_risiko",
        "matrix_cell_inheren",
        "residual_dampak",
        "residual_kemungkinan",
        "residual_level_risiko",
        "matrix_cell_residual",
        "pemilik_risiko",
        "status",
    )
    readonly_fields = (
        "no_risiko",
        "level_risiko",
        "matrix_cell_inheren",
        "residual_level_risiko",
        "matrix_cell_residual",
    )
    autocomplete_fields = ("bumn", "sasaran_kbumn", "kategori_risiko", "taksonomi_t3")

@admin.register(ProfilRisikoKorporatSummary)
class ProfilRisikoKorporatSummaryAdmin(admin.ModelAdmin):
    list_display = (
        "judul",
        "tahun",
        "nama_perusahaan",
        "kode_perusahaan",
        "status",
        "dibuat_pada",
    )
    list_filter = ("tahun", "status")
    search_fields = ("judul", "nama_perusahaan", "kode_perusahaan")
    ordering = ("-tahun", "judul")
    inlines = [ProfilRisikoKorporatItemInline]

    fieldsets = (
        ("Informasi Utama", {
            "fields": (
                "judul",
                "tahun",
                "nama_perusahaan",
                "kode_perusahaan",
                "status",
            )
        }),
        ("Catatan", {
            "fields": ("catatan",)
        }),
    )


class ProfilRisikoKorporatPenyebabInline(admin.StackedInline):
    model = ProfilRisikoKorporatPenyebab
    extra = 1
    ordering = ("urutan",)

    fields = (
        "urutan",
        "no_penyebab_risiko",
        "kode_penyebab_risiko",
        "penyebab_risiko",
        "key_risk_indicators",
        "unit_satuan_kri",
        "threshold_aman",
        "threshold_hati_hati",
        "threshold_bahaya",
        "jenis_existing_control",
        "existing_control",
        "penilaian_efektivitas_kontrol",
        "kategori_dampak",
        "deskripsi_dampak",
        "perkiraan_waktu_terpapar",
    )

    readonly_fields = (
        "no_penyebab_risiko",
        "kode_penyebab_risiko",
    )

    autocomplete_fields = (
        "jenis_existing_control",
        "penilaian_efektivitas_kontrol",
        "kategori_dampak",
    )


class RisikoInherenKuantitatifInline(admin.StackedInline):
    model = RisikoInherenKuantitatif
    extra = 0
    max_num = 1

    fields = (
        "nilai_dampak",
        "probabilitas",
        "eksposur",
        "keterangan",
    )

    readonly_fields = (
        "eksposur",
    )


class RencanaPerlakuanRisikoKorporatInline(admin.StackedInline):
    model = RencanaPerlakuanRisikoKorporat
    extra = 1
    ordering = ("urutan",)

    fields = (
        "urutan",
        "opsi_perlakuan_risiko",
        "jenis_rencana_perlakuan_risiko",
        "rencana_perlakuan_risiko",
        "output_perlakuan_risiko",
        "biaya_perlakuan_risiko",
        "pos_anggaran",
        "prk",
        "jenis_program_dalam_rkap",
        "pic",
        "timeline_1",
        "timeline_2",
        "timeline_3",
        "timeline_4",
        "timeline_5",
        "timeline_6",
        "timeline_7",
        "timeline_8",
        "timeline_9",
        "timeline_10",
        "timeline_11",
        "timeline_12",
        "status",
        "keterangan",
    )

    autocomplete_fields = (
        "opsi_perlakuan_risiko",
        "pos_anggaran",
        "jenis_program_dalam_rkap",
    )

    filter_horizontal = (
        "jenis_rencana_perlakuan_risiko",
    )


@admin.register(ProfilRisikoKorporatItem)
class ProfilRisikoKorporatItemAdmin(admin.ModelAdmin):
    inlines = [
        RisikoInherenKuantitatifInline,
        ProfilRisikoKorporatPenyebabInline,
        RencanaPerlakuanRisikoKorporatInline,
    ]

    list_display = (
        "summary",
        "no_item",
        "no_risiko",
        "bumn",
        "kode_bumn",
        "sasaran_korporat",
        "sasaran_kbumn",
        "kategori_risiko",
        "taksonomi_t3",
        "level_risiko",
        "pemilik_risiko",
        "status",
    )

    list_filter = (
        "summary__tahun",
        "summary",
        "bumn",
        "sasaran_kbumn",
        "kategori_risiko",
        "taksonomi_t3",
        "status",
    )

    search_fields = (
        "summary__judul",
        "bumn__nama",
        "bumn__kode",
        "sasaran_korporat",
        "peristiwa_risiko",
        "deskripsi_peristiwa_risiko",
        "pemilik_risiko",
        "sasaran_kbumn__kode",
        "sasaran_kbumn__nama",
        "kategori_risiko__kode",
        "kategori_risiko__nama",
        "taksonomi_t3__kode",
        "taksonomi_t3__nama",
    )

    ordering = ("summary", "no_item")

    autocomplete_fields = (
        "bumn",
        "summary",
        "sasaran_kbumn",
        "kategori_risiko",
        "taksonomi_t3",
    )

    readonly_fields = (
        "no_risiko",
        "level_risiko",
        "matrix_cell_inheren",
        "residual_level_risiko",
        "matrix_cell_residual",
    )

    fieldsets = (
        ("Header Risiko", {
            "fields": (
                "summary",
                "no_item",
                "no_risiko",
                "bumn",
            )
        }),
        ("Klasifikasi", {
            "fields": (
                "sasaran_korporat",
                "sasaran_kbumn",
                "kategori_risiko",
                "taksonomi_t3",
            )
        }),
        ("Peristiwa Risiko", {
            "fields": (
                "peristiwa_risiko",
                "deskripsi_peristiwa_risiko",
            )
        }),
        ("Penilaian Inheren", {
            "fields": (
                "dampak",
                "kemungkinan",
                "level_risiko",
                "matrix_cell_inheren",
            )
        }),
        ("Penilaian Residual", {
            "fields": (
                "residual_dampak",
                "residual_kemungkinan",
                "residual_level_risiko",
                "matrix_cell_residual",
            )
        }),
        ("Info Tambahan", {
            "fields": (
                "pemilik_risiko",
                "status",
            )
        }),
    )



@admin.register(ProfilRisikoKorporatSumber)
class ProfilRisikoKorporatSumberAdmin(admin.ModelAdmin):
    list_display = (
        "risiko_korporat",
        "reassessment_item",
        "no_penyebab_risiko",
        "kode_penyebab_risiko",
    )
    search_fields = (
        "risiko_korporat__sasaran_korporat",
        "risiko_korporat__peristiwa_risiko",
        "reassessment_item__peristiwa_risiko",
        "reassessment_item__penyebab_risiko",
        "kode_penyebab_risiko",
    )
    list_filter = (
        "risiko_korporat__summary__tahun",
        "risiko_korporat__summary",
    )
    ordering = (
        "risiko_korporat",
        "no_penyebab_risiko",
    )
    readonly_fields = (
        "no_penyebab_risiko",
        "kode_penyebab_risiko",
        "penyebab_risiko",
    )
    autocomplete_fields = (
        "risiko_korporat",
        "reassessment_item",
    )


# =========================================================
# CUSTOM ADMIN SITE
# =========================================================

try:
    risk_admin_site.register(User, CustomUserAdmin)
except Exception:
    pass

try:
    risk_admin_site.register(Group, CustomGroupAdmin)
except Exception:
    pass

risk_admin_site.register(KontrakManajemen, KontrakManajemenAdmin)
risk_admin_site.register(BagianKontrakManajemen, BagianKontrakManajemenAdmin)
risk_admin_site.register(ItemKontrakManajemen, ItemKontrakManajemenAdmin)
risk_admin_site.register(RKMSummary, RKMSummaryAdmin)
risk_admin_site.register(RKMItem, RKMItemAdmin)
risk_admin_site.register(ReAssessmentSummary, ReAssessmentSummaryAdmin)
risk_admin_site.register(ReAssessmentItem, ReAssessmentItemAdmin)
risk_admin_site.register(KPMRSummary, KPMRSummaryAdmin)
risk_admin_site.register(ProfilRisikoKorporatSummary, ProfilRisikoKorporatSummaryAdmin)
risk_admin_site.register(ProfilRisikoKorporatItem, ProfilRisikoKorporatItemAdmin)
risk_admin_site.register(TaksonomiT3, TaksonomiT3Admin)
risk_admin_site.register(KategoriRisiko, KategoriRisikoAdmin)
risk_admin_site.register(SasaranKBUMN, SasaranKBUMNAdmin)
risk_admin_site.register(MasterBUMN, MasterBUMNAdmin)
risk_admin_site.register(MasterJenisExistingControl, MasterJenisExistingControlAdmin)
risk_admin_site.register(MasterEfektivitasKontrol, MasterEfektivitasKontrolAdmin)
risk_admin_site.register(MasterKategoriDampak, MasterKategoriDampakAdmin)
risk_admin_site.register(MasterSkalaDampak, MasterSkalaDampakAdmin)
risk_admin_site.register(MasterSkalaProbabilitas, MasterSkalaProbabilitasAdmin)
risk_admin_site.register(MasterOpsiPerlakuanRisiko, MasterOpsiPerlakuanRisikoAdmin)
risk_admin_site.register(MasterJenisRencanaPerlakuanRisiko, MasterJenisRencanaPerlakuanRisikoAdmin)
risk_admin_site.register(MasterPosAnggaran, MasterPosAnggaranAdmin)
risk_admin_site.register(MasterJenisProgramRKAP, MasterJenisProgramRKAPAdmin)
risk_admin_site.register(MasterLevelRisiko, MasterLevelRisikoAdmin)
risk_admin_site.register(RiskMatrix, RiskMatrixAdmin)
risk_admin_site.register(KPMRPeriode, KPMRPeriodeAdmin)
risk_admin_site.register(KPMRIndikatorResmi, KPMRIndikatorResmiAdmin)
risk_admin_site.register(KPMRSubIndikatorResmi, KPMRSubIndikatorResmiAdmin)
risk_admin_site.register(KinerjaPeriode, KinerjaPeriodeAdmin)
risk_admin_site.register(KinerjaIndikator, KinerjaIndikatorAdmin)
risk_admin_site.register(KompositRisikoTriwulan, KompositRisikoTriwulanAdmin)
risk_admin_site.register(RoadmapProgram, RoadmapProgramAdmin)
risk_admin_site.register(RoadmapPenilaianSemester, RoadmapPenilaianSemesterAdmin)