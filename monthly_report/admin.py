import calendar
from datetime import date

from django import forms
from django.contrib import admin
from django.contrib.auth.models import Group
from django.http import Http404
from django.http import JsonResponse
from django.template.response import TemplateResponse
from django.urls import path
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from riskproject.admin_site import risk_admin_site
from .models import (
    MonthlyRiskReport,
    MonthlyRiskReportChange,
    MonthlyRiskReportItem,
    MonthlyRiskReportKMAlignment,
    MonthlyRiskReportLossEvent,
    MonthlyRiskReportSubmissionLog,
)

from masterdata.models import TahunBuku
from risk.models import (
    MasterSkalaDampak,
    MasterSkalaProbabilitas,
    PenugasanUnitBisnis,
    ReAssessmentItem,
    ReAssessmentSummary,
    RiskMatrix,
)


BULAN_CHOICES = [
    (1, "Januari"),
    (2, "Februari"),
    (3, "Maret"),
    (4, "April"),
    (5, "Mei"),
    (6, "Juni"),
    (7, "Juli"),
    (8, "Agustus"),
    (9, "September"),
    (10, "Oktober"),
    (11, "November"),
    (12, "Desember"),
]
BULAN_LABELS = dict(BULAN_CHOICES)


class MonthlyRiskReportAdminForm(forms.ModelForm):
    bulan_laporan = forms.ChoiceField(
        choices=[("", "---------")] + [(str(value), label) for value, label in BULAN_CHOICES],
        label="Bulan Laporan",
        required=True,
    )

    class Meta:
        model = MonthlyRiskReport
        exclude = ("tahun_buku", "periode", "unit", "kontrak_manajemen")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.periode_id:
            self.fields["bulan_laporan"].initial = self.instance.periode.tanggal_mulai.month


def _get_selected_reassessment_id(request):
    """Extract selected ReAssessmentSummary id from bound POST/GET on the parent form."""
    for key in (
        "reassessment",  # add form
        "reassessment_id",
        "monthlyriskreport-reassessment",
        "monthlyriskreport-0-reassessment",
        "id_reassessment",
    ):
        if key in request.POST:
            return request.POST.get(key)
        if key in request.GET:
            return request.GET.get(key)
    return None


def _assigned_unit_businesses_for_user(user):
    if not user.is_authenticated:
        return PenugasanUnitBisnis.objects.none().values_list("unit_bisnis_id", flat=True)
    if user.is_superuser:
        return Group.objects.all()
    return PenugasanUnitBisnis.objects.filter(
        user=user,
        aktif=True,
    ).values_list("unit_bisnis_id", flat=True)


def _limit_by_assigned_units(request, queryset, unit_lookup):
    if request.user.is_superuser:
        return queryset
    return queryset.filter(
        **{f"{unit_lookup}__in": _assigned_unit_businesses_for_user(request.user)}
    )


def _monthly_risk_item_label(item):
    cause_number = item.no_penyebab_risiko or ""
    risk_number = f"{item.no_risiko}{cause_number}"
    risk_event = (item.peristiwa_risiko or "").strip() or "Peristiwa risiko belum diisi"
    return f"Item {item.no_item} | Risiko {risk_number} - {risk_event}"


class MonthlyRiskReportItemInline(admin.StackedInline):
    model = MonthlyRiskReportItem
    extra = 1
    verbose_name = "Realisasi Risiko Bulanan"
    verbose_name_plural = "Input Realisasi Risiko Bulanan"
    fieldsets = (
        (
            "Item Risiko",
            {
                "fields": ("risk_event",),
            },
        ),
        (
            "III.A - Realisasi Risiko Residual",
            {
                "fields": (
                    "realisasi_asumsi_dampak",
                    "realisasi_nilai_dampak",
                    "realisasi_skala_dampak",
                    "realisasi_nilai_probabilitas",
                    "realisasi_skala_probabilitas",
                    "efektivitas_perlakuan_risiko",
                ),
            },
        ),
        (
            "III.B - Realisasi Perlakuan Risiko dan KRI",
            {
                "fields": (
                    "realisasi_rencana_perlakuan",
                    "realisasi_output_perlakuan",
                    "realisasi_biaya_perlakuan",
                    "persentase_serapan_biaya",
                    "realisasi_pic",
                    "status_rencana_perlakuan",
                    "penjelasan_status_rencana",
                    "progress_pelaksanaan_percent",
                    "realisasi_threshold_kri",
                    "realisasi_threshold_kri_skor",
                ),
            },
        ),
        (
            "Catatan",
            {
                "fields": (
                    "next_action",
                    "escalation_note",
                ),
            },
        ),
    )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "risk_event":
            reassessment_id = getattr(request, "_monthly_report_reassessment_id", None)
            if reassessment_id:
                kwargs["queryset"] = _limit_by_assigned_units(
                    request,
                    ReAssessmentItem.objects.filter(summary_id=reassessment_id),
                    "summary__unit_bisnis",
                ).order_by(
                    "no_item",
                    "no_risiko",
                    "no_penyebab_risiko",
                )
            else:
                kwargs["queryset"] = ReAssessmentItem.objects.none()
            formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)
            formfield.label_from_instance = _monthly_risk_item_label
            return formfield
        if db_field.name == "realisasi_skala_dampak":
            kwargs["queryset"] = MasterSkalaDampak.objects.filter(aktif=True).order_by(
                "urutan",
                "nama",
            )
        if db_field.name == "realisasi_skala_probabilitas":
            kwargs["queryset"] = MasterSkalaProbabilitas.objects.filter(aktif=True).order_by(
                "urutan",
                "nama",
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_formset(self, request, obj=None, **kwargs):
        # Filter inline FK dropdown based on parent MonthlyRiskReport.reassessment.
        reassessment_id = _get_selected_reassessment_id(request) or getattr(
            obj, "reassessment_id", None
        )
        request._monthly_report_reassessment_id = reassessment_id
        formset = super().get_formset(request, obj, **kwargs)

        if reassessment_id:
            try:
                reassessment_obj = ReAssessmentSummary.objects.get(pk=reassessment_id)
                risk_event_qs = ReAssessmentItem.objects.filter(summary=reassessment_obj)
            except Exception:
                risk_event_qs = ReAssessmentItem.objects.none()
        else:
            risk_event_qs = ReAssessmentItem.objects.none()

        # formset.form.base_fields is shared; patch queryset on the field.
        if hasattr(formset, "form"):
            if "risk_event" in formset.form.base_fields:
                formset.form.base_fields["risk_event"].queryset = risk_event_qs

        return formset


class MonthlyRiskReportChangeInline(admin.TabularInline):
    model = MonthlyRiskReportChange
    extra = 1
    verbose_name = "Perubahan Profil/Strategi Risiko"
    verbose_name_plural = "III.D - Ikhtisar Perubahan Profil dan Strategi Risiko"
    fields = [
        "jenis_perubahan",
        "peristiwa_risiko_terdampak",
        "penjelasan",
    ]


class MonthlyRiskReportLossEventInline(admin.StackedInline):
    model = MonthlyRiskReportLossEvent
    extra = 1
    verbose_name = "Kejadian Kerugian"
    verbose_name_plural = "III.E - Catatan Kejadian Kerugian (Loss Event Database)"
    fieldsets = (
        (
            "Kejadian",
            {
                "fields": (
                    "nama_kejadian",
                    "identifikasi_kejadian",
                    "kategori_kejadian",
                    "sumber_penyebab_kejadian",
                    "penyebab_kejadian",
                    "penanganan_saat_kejadian",
                    "deskripsi_kejadian_risk_event",
                ),
            },
        ),
        (
            "Klasifikasi Risiko dan Kerugian",
            {
                "fields": (
                    "kategori_risiko_bumn",
                    "kategori_risiko_t2_t3_kbumn",
                    "penjelasan_kerugian",
                    "nilai_kerugian",
                    "kejadian_berulang",
                    "frekuensi_kejadian",
                ),
            },
        ),
        (
            "Mitigasi dan Asuransi",
            {
                "fields": (
                    "mitigasi_direncanakan",
                    "realisasi_mitigasi",
                    "perbaikan_mendatang",
                    "pihak_terkait",
                    "status_asuransi",
                    "nilai_premi",
                    "nilai_klaim",
                ),
            },
        ),
    )


class MonthlyRiskReportGroupFilter(admin.SimpleListFilter):
    title = "group"
    parameter_name = "group"

    def lookups(self, request, model_admin):
        group_ids = (
            model_admin.get_queryset(request)
            .exclude(reassessment__unit_bisnis__isnull=True)
            .values_list("reassessment__unit_bisnis_id", flat=True)
            .distinct()
        )
        return [
            (str(group.pk), group.name)
            for group in Group.objects.filter(pk__in=group_ids).order_by("name")
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(reassessment__unit_bisnis_id=self.value())
        return queryset


@admin.register(MonthlyRiskReport, site=risk_admin_site)
class MonthlyRiskReportAdmin(admin.ModelAdmin):
    form = MonthlyRiskReportAdminForm
    inlines = [
        MonthlyRiskReportItemInline,
        MonthlyRiskReportChangeInline,
        MonthlyRiskReportLossEventInline,
    ]
    class Media:
        js = ("monthly_report/admin/monthly_report_items.js?v=20260715-local-filtered-risk-items",)

    fields = [
        "reassessment",
        "bulan_laporan",
        "petunjuk_lampiran",
        "peta_risiko_iiic_link",
        "versi",
        "status",
        "prepared_by",
        "reviewed_by",
        "approved_by",
    ]
    readonly_fields = ["petunjuk_lampiran", "peta_risiko_iiic_link"]
    autocomplete_fields = (
        "reassessment",
        "prepared_by",
        "reviewed_by",
        "approved_by",
    )

    list_display = [
        "reassessment",
        "bulan_laporan_display",
        "status",
        "total_risiko",
        "total_high",
        "total_mitigasi_terlambat",
    ]
    list_filter = [MonthlyRiskReportGroupFilter, "status"]
    search_fields = [
        "reassessment__judul",
        "reassessment__unit_bisnis__name",
    ]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/peta-risiko-iiic/",
                self.admin_site.admin_view(self.peta_risiko_iiic_view),
                name="monthly_report_monthlyriskreport_peta_risiko_iiic",
            ),
            path(
                "risk-items/",
                self.admin_site.admin_view(self.risk_items_for_reassessment),
                name="monthly_report_monthlyriskreport_risk_items",
            ),
        ]
        return custom_urls + urls

    @admin.display(description="III.C - Peta Risiko Residual")
    def peta_risiko_iiic_link(self, obj):
        if not obj or not obj.pk:
            return "Simpan laporan terlebih dahulu untuk melihat peta risiko."
        url = reverse(
            "risk_admin:monthly_report_monthlyriskreport_peta_risiko_iiic",
            args=[obj.pk],
        )
        return format_html('<a class="button" href="{}">Lihat Peta Risiko III.C</a>', url)

    @admin.display(description="Petunjuk Lampiran")
    def petunjuk_lampiran(self, obj):
        return mark_safe(
            "<ul style='margin:0; padding-left:18px;'>"
            "<li><strong>III.A & III.B</strong>: ada di bagian "
            "<a href='#items-group'>Input Realisasi Risiko Bulanan</a>.</li>"
            "<li><strong>III.C</strong>: peta risiko residual. Pada halaman Add, simpan laporan dulu; "
            "setelah itu tombol <em>Lihat Peta Risiko III.C</em> bisa dibuka.</li>"
            "<li><strong>III.D</strong>: ada di bagian "
            "<a href='#changes-group'>III.D - Ikhtisar Perubahan Profil dan Strategi Risiko</a>.</li>"
            "<li><strong>III.E</strong>: ada di bagian "
            "<a href='#loss_events-group'>III.E - Catatan Kejadian Kerugian</a>.</li>"
            "</ul>"
        )

    def peta_risiko_iiic_view(self, request, object_id):
        report = self.get_object(request, object_id)
        if report is None:
            raise Http404("Monthly risk report tidak ditemukan.")
        matrix = (
            report.reassessment.risk_matrix
            if report and report.reassessment_id and report.reassessment.risk_matrix_id
            else RiskMatrix.objects.filter(aktif=True, is_default=True).first()
        )
        dampak_scales = list(MasterSkalaDampak.objects.filter(aktif=True).order_by("urutan", "nama"))
        probabilitas_scales = list(
            MasterSkalaProbabilitas.objects.filter(aktif=True).order_by("-urutan", "-nama")
        )
        cells_by_key = {}
        if matrix:
            cells_by_key = {
                (cell.skala_dampak_id, cell.skala_probabilitas_id): cell
                for cell in matrix.cells.select_related("level_risiko").filter(aktif=True)
            }

        inherent_points = {}
        residual_points = {}
        for item in report.items.select_related(
            "risk_event",
            "risk_event__skala_dampak_q1",
            "risk_event__skala_probabilitas_q1",
            "realisasi_skala_dampak",
            "realisasi_skala_probabilitas",
        ):
            risk_number = str(item.risk_event.no_risiko)
            if item.risk_event.skala_dampak_q1_id and item.risk_event.skala_probabilitas_q1_id:
                inherent_points.setdefault(
                    (item.risk_event.skala_dampak_q1_id, item.risk_event.skala_probabilitas_q1_id),
                    [],
                ).append(risk_number)
            if item.realisasi_skala_dampak_id and item.realisasi_skala_probabilitas_id:
                residual_points.setdefault(
                    (item.realisasi_skala_dampak_id, item.realisasi_skala_probabilitas_id),
                    [],
                ).append(risk_number)

        rows = []
        for prob in probabilitas_scales:
            row = []
            for dampak in dampak_scales:
                cell = cells_by_key.get((dampak.id, prob.id))
                key = (dampak.id, prob.id)
                row.append(
                    {
                        "dampak": dampak,
                        "probabilitas": prob,
                        "cell": cell,
                        "score": cell.skor if cell else "",
                        "level": cell.level_risiko.nama if cell and cell.level_risiko_id else "",
                        "color": cell.warna_hex if cell and cell.warna_hex else "#f5f5f5",
                        "inherent_points": inherent_points.get(key, []),
                        "residual_points": residual_points.get(key, []),
                    }
                )
            rows.append({"probabilitas": prob, "cells": row})

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "report": report,
            "matrix": matrix,
            "dampak_scales": dampak_scales,
            "rows": rows,
            "title": "III.C - Peta Risiko Residual",
        }
        return TemplateResponse(request, "monthly_report/peta_risiko_iiic.html", context)

    def risk_items_for_reassessment(self, request):
        reassessment_id = request.GET.get("reassessment")
        queryset = ReAssessmentItem.objects.none()
        if reassessment_id:
            queryset = _limit_by_assigned_units(
                request,
                ReAssessmentItem.objects.filter(summary_id=reassessment_id),
                "summary__unit_bisnis",
            ).order_by(
                "no_item",
                "no_risiko",
                "no_penyebab_risiko",
            )

        return JsonResponse(
            {
                "items": [
                    {
                        "id": item.pk,
                        "text": _monthly_risk_item_label(item),
                    }
                    for item in queryset
                ]
            }
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "reassessment":
            kwargs["queryset"] = _limit_by_assigned_units(
                request,
                ReAssessmentSummary.objects.select_related(
                    "unit_bisnis",
                    "kontrak_manajemen",
                ),
                "unit_bisnis",
            ).order_by("-tahun", "unit_bisnis__name", "judul")
            formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)
            formfield.label = "Profil Risiko Bidang/Unit Bisnis"
            return formfield
        if db_field.name == "realisasi_skala_dampak":
            kwargs["queryset"] = MasterSkalaDampak.objects.filter(aktif=True).order_by(
                "urutan",
                "nama",
            )
        if db_field.name == "realisasi_skala_probabilitas":
            kwargs["queryset"] = MasterSkalaProbabilitas.objects.filter(aktif=True).order_by(
                "urutan",
                "nama",
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if obj.reassessment_id:
            obj.tahun_buku, _ = TahunBuku.objects.get_or_create(
                tahun=obj.reassessment.tahun,
                defaults={"aktif": True},
            )
            bulan = int(form.cleaned_data["bulan_laporan"])
            _, tanggal_selesai = calendar.monthrange(obj.reassessment.tahun, bulan)
            obj.periode, _ = obj.tahun_buku.periodelaporan_set.get_or_create(
                kode_periode=f"{obj.reassessment.tahun}-{bulan:02d}",
                defaults={
                    "nama_periode": f"{BULAN_LABELS[bulan]} {obj.reassessment.tahun}",
                    "jenis_periode": "bulanan",
                    "tanggal_mulai": date(obj.reassessment.tahun, bulan, 1),
                    "tanggal_selesai": date(obj.reassessment.tahun, bulan, tanggal_selesai),
                },
            )
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        return _limit_by_assigned_units(
            request,
            super().get_queryset(request),
            "reassessment__unit_bisnis",
        )

    @admin.display(description="Bulan Laporan", ordering="periode__tanggal_mulai")
    def bulan_laporan_display(self, obj):
        return obj.periode.nama_periode

    # --- Dependent dropdown filtering (works on Add + Edit):

    def get_formset(self, request, obj=None, **kwargs):
        # Not needed; inline filtering handled via get_formset for the inline.
        return super().get_formset(request, obj=obj, **kwargs)

    def get_inline_formsets(self, request, formsets, inline_instances, obj=None):
        # No-op: we will override via inline.get_formset (below).
        return super().get_inline_formsets(request, formsets, inline_instances, obj=obj)



@admin.register(MonthlyRiskReportItem, site=risk_admin_site)
class MonthlyRiskReportItemAdmin(admin.ModelAdmin):
    list_display = [
        "report",
        "risk_event",
        "quarter_display",
        "realisasi_nilai_dampak",
        "realisasi_nilai_probabilitas",
        "realisasi_eksposur",
        "realisasi_skor_risiko",
        "realisasi_level_risiko",
        "efektivitas_perlakuan_risiko",
    ]
    list_filter = [
        "contributes_to_corporate",
        "mitigation_status",
        "trend",
    ]
    search_fields = ["issue_summary", "next_action", "escalation_note"]
    raw_id_fields = ["report", "km_item"]

    def get_queryset(self, request):
        return _limit_by_assigned_units(
            request,
            super().get_queryset(request),
            "report__reassessment__unit_bisnis",
        )

    @admin.display(description="Kuartal")
    def quarter_display(self, obj):
        quarter = obj.quarter
        return f"Q{quarter}" if quarter else "-"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "risk_event":
            kwargs["queryset"] = _limit_by_assigned_units(
                request,
                ReAssessmentItem.objects.select_related(
                    "summary",
                    "unit_bisnis",
                ),
                "summary__unit_bisnis",
            ).order_by("summary", "no_item", "no_risiko", "no_penyebab_risiko")
            formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)
            formfield.label = "Item Risiko Unit/Bidang"
            return formfield
        if db_field.name == "report":
            kwargs["queryset"] = _limit_by_assigned_units(
                request,
                MonthlyRiskReport.objects.all(),
                "reassessment__unit_bisnis",
            )
        if db_field.name == "realisasi_skala_dampak":
            kwargs["queryset"] = MasterSkalaDampak.objects.filter(aktif=True).order_by(
                "urutan",
                "nama",
            )
        if db_field.name == "realisasi_skala_probabilitas":
            kwargs["queryset"] = MasterSkalaProbabilitas.objects.filter(aktif=True).order_by(
                "urutan",
                "nama",
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(MonthlyRiskReportKMAlignment, site=risk_admin_site)
class MonthlyRiskReportKMAlignmentAdmin(admin.ModelAdmin):
    list_display = [
        "report_item",
        "km_item",
        "alignment_status",
        "alignment_score",
    ]
    list_filter = ["alignment_status"]
    search_fields = ["reason"]
    raw_id_fields = ["report_item", "km_item"]

    def get_queryset(self, request):
        return _limit_by_assigned_units(
            request,
            super().get_queryset(request),
            "report_item__report__reassessment__unit_bisnis",
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "report_item":
            kwargs["queryset"] = _limit_by_assigned_units(
                request,
                MonthlyRiskReportItem.objects.all(),
                "report__reassessment__unit_bisnis",
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(MonthlyRiskReportChange, site=risk_admin_site)
class MonthlyRiskReportChangeAdmin(admin.ModelAdmin):
    list_display = [
        "report",
        "jenis_perubahan",
        "peristiwa_risiko_terdampak",
    ]
    list_filter = ["jenis_perubahan"]
    search_fields = [
        "report__reassessment__judul",
        "peristiwa_risiko_terdampak",
        "penjelasan",
    ]
    raw_id_fields = ["report"]

    def get_queryset(self, request):
        return _limit_by_assigned_units(
            request,
            super().get_queryset(request),
            "report__reassessment__unit_bisnis",
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "report":
            kwargs["queryset"] = _limit_by_assigned_units(
                request,
                MonthlyRiskReport.objects.all(),
                "reassessment__unit_bisnis",
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(MonthlyRiskReportLossEvent, site=risk_admin_site)
class MonthlyRiskReportLossEventAdmin(admin.ModelAdmin):
    list_display = [
        "report",
        "nama_kejadian",
        "kategori_kejadian",
        "sumber_penyebab_kejadian",
        "nilai_kerugian",
        "status_asuransi",
    ]
    list_filter = [
        "sumber_penyebab_kejadian",
        "kejadian_berulang",
        "status_asuransi",
    ]
    search_fields = [
        "report__reassessment__judul",
        "nama_kejadian",
        "identifikasi_kejadian",
        "penyebab_kejadian",
        "deskripsi_kejadian_risk_event",
    ]
    raw_id_fields = ["report"]

    def get_queryset(self, request):
        return _limit_by_assigned_units(
            request,
            super().get_queryset(request),
            "report__reassessment__unit_bisnis",
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "report":
            kwargs["queryset"] = _limit_by_assigned_units(
                request,
                MonthlyRiskReport.objects.all(),
                "reassessment__unit_bisnis",
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(MonthlyRiskReportSubmissionLog, site=risk_admin_site)
class MonthlyRiskReportSubmissionLogAdmin(admin.ModelAdmin):
    list_display = [
        "report",
        "action",
        "action_by",
        "action_at",
    ]
    list_filter = ["action", "action_at"]
    search_fields = ["note"]
    raw_id_fields = ["report", "action_by"]

    def get_queryset(self, request):
        return _limit_by_assigned_units(
            request,
            super().get_queryset(request),
            "report__reassessment__unit_bisnis",
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "report":
            kwargs["queryset"] = _limit_by_assigned_units(
                request,
                MonthlyRiskReport.objects.all(),
                "reassessment__unit_bisnis",
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
