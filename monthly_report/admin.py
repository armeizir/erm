import calendar
from datetime import date

from django import forms
from django.contrib import admin
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.http import Http404
from django.http import HttpResponseRedirect
from django.http import JsonResponse
from django.template.response import TemplateResponse
from django.urls import path
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from riskproject.admin_site import risk_admin_site
from .pdf_reports import (
    _display_number_map,
    _money,
    _ordered_items,
    _percent,
    _quarter_number,
    _risk_level_text,
    _scale_value,
)
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
from risk.services.kpmr_automation import calculate_kpmr_for_report
from risk.services.kpmr_automation import month_to_quarter
from .notifications import send_monthly_report_notification
from .services import refresh_monthly_report_summary


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


def _monthly_level_class(value):
    text = str(value or "").lower()
    if "sangat tinggi" in text or "very high" in text or "ekstr" in text:
        return "level-danger"
    if "tinggi" in text or "high" in text:
        return "level-high"
    if "moderat" in text or "moderate" in text or "sedang" in text:
        return "level-moderate"
    if "rendah" in text or "low" in text:
        return "level-low"
    return ""


def _monthly_progress_class(value):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return ""
    if number >= 100:
        return "progress-done"
    if number >= 50:
        return "progress-warning"
    return "progress-danger"


def _monthly_timeline_mark(value):
    try:
        return "1" if int(value or 0) else ""
    except (TypeError, ValueError):
        return ""


def _kpmr_detail_groups(calculation):
    if not calculation:
        return []
    indicators = {item["kode"]: item for item in calculation.indicators}
    i4_subindicators = {
        item["kode"]: item
        for item in indicators.get("I4", {}).get("subindikator", [])
    }
    detail_notes = {}
    for note in calculation.notes:
        if note.startswith("I4.2 "):
            detail_notes["KUANTIFIKASI"] = note
        elif note.startswith("I1 "):
            detail_notes["I1"] = note
        elif note.startswith("I2 "):
            detail_notes["I2"] = note
        elif note.startswith("I3 "):
            detail_notes["I3"] = note
        elif note.startswith("I4 "):
            detail_notes["I4"] = note

    def group(no, title, indicator_code, options):
        indicator = indicators.get(indicator_code, {})
        return {
            "no": no,
            "title": title,
            "answer": indicator.get("jawaban", ""),
            "hasil": indicator.get("hasil"),
            "skor": indicator.get("skor"),
            "options": options,
            "rowspan": len(options) + 1,
            "keterangan": detail_notes.get(indicator_code) or indicator.get("keterangan", ""),
        }

    def subgroup(title, sub_code, options):
        indicator = i4_subindicators.get(sub_code, {})
        return {
            "title": title,
            "answer": indicator.get("jawaban", ""),
            "hasil": indicator.get("hasil"),
            "skor": indicator.get("skor"),
            "options": options,
            "rowspan": len(options) + 1,
            "keterangan": detail_notes.get(sub_code) or indicator.get("keterangan", ""),
        }

    i4_subgroups = [
        subgroup(
            "1). Ketepatan identifikasi Risiko (Bobot 25%)",
            "IDENTIFIKASI",
            [
                ("a", "Tidak ada Risiko baru yang mempengaruhi penurunan kinerja pada triwulan berjalan", 90),
                ("b", "Terdapat Risiko baru yang belum teridentifikasi yang mempengaruhi penurunan kinerja", 50),
            ],
        ),
        subgroup(
            "2). Ketepatan kuantifikasi Risiko (Bobot 25%)",
            "KUANTIFIKASI",
            [
                (
                    "a",
                    "Realisasi perhitungan nilai dampak dan nilai probabilitas memiliki deviasi negatif tidak lebih dari 5% dengan nilai dampak dan nilai probabilitas yang ditargetkan pada triwulan berjalan",
                    90,
                ),
                (
                    "b",
                    "Realisasi perhitungan nilai dampak dan nilai probabilitas memiliki deviasi negatif lebih dari 5% dengan nilai dampak dan nilai probabilitas yang ditargetkan pada triwulan berjalan",
                    50,
                ),
            ],
        ),
        subgroup(
            "3). Ketepatan rencana perlakuan Risiko (Bobot 25%)",
            "RENCANA",
            [
                (
                    "a",
                    "Rencana perlakuan Risiko dapat menurunkan nilai Eksposur Risiko residual sesuai dengan target Risiko residual pada triwulan berjalan",
                    90,
                ),
                (
                    "b",
                    "Rencana perlakuan Risiko belum dapat menurunkan nilai Eksposur Risiko residual sesuai dengan target Risiko residual pada triwulan berjalan",
                    50,
                ),
            ],
        ),
        subgroup(
            "4). Ketepatan prioritisasi Risiko (Bobot 25%)",
            "PRIORITISASI",
            [
                (
                    "a",
                    "Seluruh Risiko dari struktur korporasi di bawah BUMN tidak ada yang baru yang mempengaruhi penurunan kinerja",
                    90,
                ),
                (
                    "b",
                    "Terdapat Risiko baru dari struktur korporasi di bawah BUMN yang tidak masuk dalam Integrasi Risiko yang mempengaruhi penurunan kinerja",
                    50,
                ),
            ],
        ),
    ]

    return [
        group(
            "1",
            "Pencapaian Nilai Eksposur Risiko sesuai dengan target Risiko Residual (Bobot 30%)",
            "I1",
            [
                ("a", "Nilai Eksposur Risiko lebih rendah dari target Risiko Residual", 90),
                ("b", "Nilai Eksposur Risiko sama dengan target Risiko Residual", 60),
                ("c", "Nilai Eksposur Risiko lebih tinggi dari target Risiko Residual*)", 40),
            ],
        ),
        group(
            "2",
            "Pencapaian output pelaksanaan kegiatan perlakuan Risiko sesuai dengan target (Bobot 20%)",
            "I2",
            [
                ("a", "Terealisasi 90-100%", 100),
                ("b", "Terealisasi 80-89%", 80),
                ("c", "Terealisasi 70-79%", 60),
                ("d", "Terealisasi 60-69%", 40),
                ("e", "Terealisasi kurang dari 60%", 20),
            ],
        ),
        group(
            "3",
            "Realisasi anggaran pelaksanaan kegiatan perlakuan Risiko sesuai dengan anggaran (Bobot 20%)",
            "I3",
            [
                ("a", "Realisasi biaya perlakuan Risiko sama dengan atau lebih rendah dari anggaran", 80),
                ("b", "Realisasi biaya perlakuan Risiko lebih tinggi dari anggaran", 40),
            ],
        ),
        {
            "no": "4",
            "title": "Ketepatan penilaian Risiko (Bobot 30%)",
            "subgroups": i4_subgroups,
            "rowspan": 1 + sum(item["rowspan"] for item in i4_subgroups),
        },
    ]


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

        unit = self._selected_unit_bisnis()
        if unit:
            self.fields["prepared_by"].queryset = _users_for_unit_role(
                unit,
                PenugasanUnitBisnis.ROLE_RISK_OFFICER,
            )
            self.fields["reviewed_by"].queryset = _users_for_unit_role(
                unit,
                PenugasanUnitBisnis.ROLE_RISK_CHAMPION,
            )
            self.fields["approved_by"].queryset = _users_for_unit_group(unit)

    def _selected_unit_bisnis(self):
        if self.instance and self.instance.reassessment_id:
            return self.instance.reassessment.unit_bisnis

        reassessment_id = self.data.get("reassessment") or self.initial.get("reassessment")
        if not reassessment_id:
            return None

        return (
            ReAssessmentSummary.objects.filter(pk=reassessment_id)
            .select_related("unit_bisnis")
            .values_list("unit_bisnis", flat=True)
            .first()
        )


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


def _users_for_unit_role(unit, role):
    User = get_user_model()
    return User.objects.filter(
        penugasan_unit_bisnis__unit_bisnis=unit,
        penugasan_unit_bisnis__peran=role,
        penugasan_unit_bisnis__aktif=True,
        is_active=True,
    ).distinct().order_by("first_name", "last_name", "username")


def _users_for_unit_group(unit):
    User = get_user_model()
    return User.objects.filter(
        groups=unit,
        is_active=True,
    ).distinct().order_by("first_name", "last_name", "username")


def _monthly_risk_item_key(item):
    risk_event = (item.peristiwa_risiko or "").strip().casefold()
    if risk_event:
        return risk_event
    return f"item:{item.pk}"


def _monthly_risk_item_number_map(items):
    number_by_key = {}
    number_by_pk = {}
    for item in items:
        key = _monthly_risk_item_key(item)
        if key not in number_by_key:
            number_by_key[key] = len(number_by_key) + 1
        number_by_pk[item.pk] = number_by_key[key]
    return number_by_pk


def _monthly_risk_item_label(item, number_by_pk=None):
    unit_code = ""
    if item.summary_id and item.summary.unit_bisnis_id:
        unit_code = item.summary.unit_bisnis.name
    risk_number = item.no_risiko or item.no_item or "-"
    cause_number = (item.no_penyebab_risiko or "").strip().lower()
    code_parts = [str(part) for part in (unit_code, risk_number) if part]
    risk_code = "-".join(code_parts)
    if cause_number:
        risk_code = f"{risk_code}.{cause_number}"
    risk_event = (item.peristiwa_risiko or "").strip() or "Peristiwa risiko belum diisi"
    return f"{risk_code} | Risiko {risk_number} | Penyebab {cause_number or '-'} - {risk_event}"


class MonthlyRiskReportItemInline(admin.StackedInline):
    model = MonthlyRiskReportItem
    extra = 1
    readonly_fields = ("persentase_serapan_biaya",)
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
                queryset = _limit_by_assigned_units(
                    request,
                    ReAssessmentItem.objects.select_related("summary__unit_bisnis").filter(
                        summary_id=reassessment_id
                    ),
                    "summary__unit_bisnis",
                ).order_by(
                    "no_item",
                    "no_penyebab_risiko",
                    "no_risiko",
                    "id",
                )
            else:
                queryset = ReAssessmentItem.objects.none()
            items = list(queryset)
            number_by_pk = _monthly_risk_item_number_map(items)
            kwargs["queryset"] = queryset
            formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)
            formfield.label_from_instance = lambda item: _monthly_risk_item_label(
                item,
                number_by_pk,
            )
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
        css = {
            "screen": (
                "admin/css/vendor/select2/select2.css",
                "admin/css/autocomplete.css",
            )
        }
        js = (
            "admin/js/vendor/select2/select2.full.js",
            "monthly_report/admin/monthly_report_items_searchable.js",
        )

    fields = [
        "reassessment",
        "bulan_laporan",
        "petunjuk_lampiran",
        "peta_risiko_iiic_link",
        "versi",
        "status",
        "flow_action_button",
        "notification_button",
        "prepared_by",
        "reviewed_by",
        "approved_by",
    ]
    readonly_fields = [
        "petunjuk_lampiran",
        "peta_risiko_iiic_link",
        "flow_action_button",
        "notification_button",
    ]
    autocomplete_fields = (
        "reassessment",
    )

    list_display = [
        "reassessment",
        "bulan_laporan_display",
        "status",
        "total_risiko",
        "total_high",
        "total_mitigasi_terlambat",
        "flow_action_button",
        "notification_button",
        "web_button",
    ]
    list_filter = [MonthlyRiskReportGroupFilter, "status"]
    actions = ["send_next_notification_action"]
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
                "<path:object_id>/web/",
                self.admin_site.admin_view(self.web_report_view),
                name="monthly_report_monthlyriskreport_web",
            ),
            path(
                "<path:object_id>/send-notification/",
                self.admin_site.admin_view(self.send_notification_view),
                name="monthly_report_monthlyriskreport_send_notification",
            ),
            path(
                "<path:object_id>/flow/<str:flow_action>/",
                self.admin_site.admin_view(self.flow_action_view),
                name="monthly_report_monthlyriskreport_flow_action",
            ),
            path(
                "risk-items/",
                self.admin_site.admin_view(self.risk_items_for_reassessment),
                name="monthly_report_monthlyriskreport_risk_items",
            ),
        ]
        return custom_urls + urls

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj and "status" not in readonly_fields:
            readonly_fields.append("status")
        return readonly_fields

    @admin.display(description="III.C - Peta Risiko Residual")
    def peta_risiko_iiic_link(self, obj):
        if not obj or not obj.pk:
            return "Simpan laporan terlebih dahulu untuk melihat peta risiko."
        url = reverse(
            "risk_admin:monthly_report_monthlyriskreport_peta_risiko_iiic",
            args=[obj.pk],
        )
        return format_html('<a class="button" href="{}">Lihat Peta Risiko III.C</a>', url)

    def _flow_action_for_status(self, status):
        return {
            "draft": ("submit", "Submit Laporan"),
            "revision": ("submit", "Submit Ulang"),
            "submitted": ("review", "Review & Paraf"),
            "under_review": ("approve", "Approve"),
        }.get(status)

    @admin.display(description="Flow")
    def flow_action_button(self, obj):
        if not obj or not obj.pk:
            return "-"
        action = self._flow_action_for_status(obj.status)
        if not action:
            return obj.get_status_display()
        action_name, label = action
        url = reverse(
            f"{self.admin_site.name}:monthly_report_monthlyriskreport_flow_action",
            args=[obj.pk, action_name],
        )
        return format_html('<a class="button" href="{}">{}</a>', url, label)

    @admin.display(description="Notifikasi")
    def notification_button(self, obj):
        if not obj or not obj.pk:
            return "-"
        if obj.status in {"approved", "locked"}:
            return "-"
        url = reverse(
            f"{self.admin_site.name}:monthly_report_monthlyriskreport_send_notification",
            args=[obj.pk],
        )
        return format_html('<a class="button" href="{}">Kirim Notifikasi</a>', url)

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

        previous_report = None
        next_report = None
        if report.periode_id and report.reassessment_id:
            current_date = report.periode.tanggal_mulai

            def shifted_month(delta):
                month_index = current_date.year * 12 + current_date.month - 1 + delta
                year, zero_based_month = divmod(month_index, 12)
                return year, zero_based_month + 1

            adjacent_reports = self.get_queryset(request).filter(
                reassessment_id=report.reassessment_id
            )
            previous_year, previous_month = shifted_month(-1)
            next_year, next_month = shifted_month(1)
            previous_report = (
                adjacent_reports.filter(
                    periode__tanggal_mulai__year=previous_year,
                    periode__tanggal_mulai__month=previous_month,
                )
                .order_by("-versi", "-pk")
                .first()
            )
            next_report = (
                adjacent_reports.filter(
                    periode__tanggal_mulai__year=next_year,
                    periode__tanggal_mulai__month=next_month,
                )
                .order_by("-versi", "-pk")
                .first()
            )

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

        kpmr_calculation = None
        kpmr_month = report.periode.tanggal_mulai.month if report.periode_id else None
        kpmr_quarter = month_to_quarter(kpmr_month) if kpmr_month else None
        if report.reassessment_id and report.reassessment.unit_bisnis_id and kpmr_quarter:
            kpmr_calculation = calculate_kpmr_for_report(report)

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "report": report,
            "matrix": matrix,
            "dampak_scales": dampak_scales,
            "rows": rows,
            "kpmr_calculation": kpmr_calculation,
            "kpmr_detail_groups": _kpmr_detail_groups(kpmr_calculation),
            "kpmr_month": kpmr_month,
            "kpmr_quarter": kpmr_quarter,
            "kpmr_is_quarter_snapshot": kpmr_month in {3, 6, 9, 12} if kpmr_month else False,
            "previous_report": previous_report,
            "next_report": next_report,
            "title": "III.C - Peta Risiko Residual",
        }
        return TemplateResponse(request, "monthly_report/peta_risiko_iiic.html", context)

    @admin.display(description="Laporan")
    def web_button(self, obj):
        if not obj or not obj.pk:
            return "-"
        url = reverse(
            f"{self.admin_site.name}:monthly_report_monthlyriskreport_web",
            args=[obj.pk],
        )
        return format_html('<a class="button" href="{}" target="_blank">Lihat</a>', url)

    def _monthly_report_web_context(self, request, report):
        items = _ordered_items(report)
        number_by_risk = _display_number_map(items)
        quarter = _quarter_number(report)
        iiia_rows = []
        iiib_rows = []
        for item in items:
            risk = item.risk_event
            risk_no = number_by_risk.get(risk.id, risk.no_risiko or risk.no_item)
            target_level = _risk_level_text(
                getattr(risk, f"skala_risiko_q{quarter}", ""),
                getattr(risk, f"level_nilai_risiko_q{quarter}", ""),
            )
            iiia_rows.append(
                {
                    "risk_no": risk_no,
                    "event": risk.peristiwa_risiko,
                    "risk_type": "Kualitatif",
                    "assumption": item.realisasi_asumsi_dampak or risk.asumsi_perhitungan_dampak,
                    "target": {
                        "impact_value": _money(getattr(risk, f"nilai_dampak_q{quarter}", None)),
                        "impact_scale": _scale_value(getattr(risk, f"skala_dampak_q{quarter}", None)),
                        "probability_value": _percent(getattr(risk, f"nilai_probabilitas_q{quarter}", None)),
                        "probability_scale": _scale_value(getattr(risk, f"skala_probabilitas_q{quarter}", None)),
                        "exposure": _money(getattr(risk, f"eksposur_risiko_q{quarter}", None)),
                        "score": getattr(risk, f"skala_risiko_q{quarter}", "") or "",
                        "level": target_level,
                        "level_class": _monthly_level_class(target_level),
                    },
                    "realization": {
                        "impact_value": _money(item.realisasi_nilai_dampak),
                        "impact_scale": item.realisasi_skala_dampak or "",
                        "probability_value": _percent(item.realisasi_nilai_probabilitas),
                        "probability_scale": item.realisasi_skala_probabilitas or "",
                        "exposure": _money(item.realisasi_eksposur),
                        "score": item.realisasi_skor_risiko or "",
                        "level": item.realisasi_level_risiko or "",
                        "level_class": _monthly_level_class(item.realisasi_level_risiko),
                    },
                    "effectiveness": item.get_efektivitas_perlakuan_risiko_display() or "",
                }
            )
            iiib_rows.append(
                {
                    "risk_no": risk_no,
                    "event": risk.peristiwa_risiko,
                    "description": risk.deskripsi_peristiwa_risiko,
                    "cause_no": (risk.no_penyebab_risiko or "").lower(),
                    "cause_code": risk.kode_penyebab_risiko,
                    "cause": risk.penyebab_risiko,
                    "treatment_plan": risk.rencana_perlakuan_risiko,
                    "treatment_output": risk.output_perlakuan_risiko,
                    "treatment_cost": _money(risk.biaya_perlakuan_risiko),
                    "realized_plan": item.realisasi_rencana_perlakuan,
                    "realized_output": item.realisasi_output_perlakuan,
                    "absorbed_cost": _percent(item.persentase_serapan_biaya),
                    "pic": item.realisasi_pic or risk.pic,
                    "status": item.get_status_rencana_perlakuan_display() or "",
                    "status_explanation": item.penjelasan_status_rencana or "",
                    "progress": _percent(item.progress_pelaksanaan_percent),
                    "progress_class": _monthly_progress_class(item.progress_pelaksanaan_percent),
                    "kri": item.realisasi_threshold_kri,
                    "timeline": [_monthly_timeline_mark(getattr(risk, f"timeline_{month}", 0)) for month in range(1, 13)],
                }
            )
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Laporan Realisasi Manajemen Risiko",
            "report": report,
            "quarter": quarter,
            "iiia_rows": iiia_rows,
            "iiib_rows": iiib_rows,
            "changes": report.changes.all(),
            "loss_events": report.loss_events.all(),
        }
        return context

    def web_report_view(self, request, object_id):
        report = self.get_object(request, object_id)
        if report is None:
            raise Http404("Monthly risk report tidak ditemukan.")
        return TemplateResponse(
            request,
            "monthly_report/monthly_risk_report_web.html",
            self._monthly_report_web_context(request, report),
        )

    def _send_next_notification(self, request, report):
        try:
            sent = send_monthly_report_notification(report, request=request)
        except ValidationError as exc:
            message = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            self.message_user(request, message, level=messages.ERROR)
            return 0
        if sent:
            self.message_user(
                request,
                f"Notifikasi terkirim untuk {report.reassessment} - {report.periode.nama_periode}.",
                level=messages.SUCCESS,
            )
        return sent

    def _apply_flow_action(self, report, flow_action, user):
        valid_actions = {
            "submit": {"draft", "revision"},
            "review": {"submitted"},
            "approve": {"under_review"},
        }
        if flow_action not in valid_actions:
            raise ValidationError("Aksi flow tidak dikenal.")
        if report.status not in valid_actions[flow_action]:
            raise ValidationError(
                f"Aksi tidak sesuai. Status laporan saat ini: {report.get_status_display()}."
            )

        update_fields = ["status", "updated_at"]
        note = ""
        if flow_action == "submit":
            if not report.prepared_by_id:
                raise ValidationError("Prepared by/Risk Office belum diisi.")
            report.status = "submitted"
            report.submitted_at = timezone.now()
            update_fields.append("submitted_at")
            note = "Submitted oleh Prepared by/Risk Office."
        elif flow_action == "review":
            if not report.reviewed_by_id:
                raise ValidationError("Reviewed by belum diisi.")
            report.status = "under_review"
            note = "Review dan paraf oleh Reviewed by."
        elif flow_action == "approve":
            if not report.approved_by_id:
                raise ValidationError("Approved by belum diisi.")
            report.status = "approved"
            report.approved_at = timezone.now()
            update_fields.append("approved_at")
            note = "Approved oleh Approved by."

        report.save(update_fields=update_fields)
        MonthlyRiskReportSubmissionLog.objects.create(
            report=report,
            action=flow_action,
            action_by=user,
            note=note,
        )
        return report

    def flow_action_view(self, request, object_id, flow_action):
        report = self.get_object(request, object_id)
        if report is None:
            raise Http404("Monthly risk report tidak ditemukan.")
        try:
            self._apply_flow_action(report, flow_action, request.user)
        except ValidationError as exc:
            message = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            self.message_user(request, message, level=messages.ERROR)
        else:
            self.message_user(
                request,
                f"Flow laporan berhasil diproses. Status sekarang: {report.get_status_display()}.",
                level=messages.SUCCESS,
            )
        return HttpResponseRedirect(
            reverse(
                f"{self.admin_site.name}:monthly_report_monthlyriskreport_change",
                args=[report.pk],
            )
        )

    def send_notification_view(self, request, object_id):
        report = self.get_object(request, object_id)
        if report is None:
            raise Http404("Monthly risk report tidak ditemukan.")
        self._send_next_notification(request, report)
        return HttpResponseRedirect(
            reverse(
                f"{self.admin_site.name}:monthly_report_monthlyriskreport_change",
                args=[report.pk],
            )
        )

    @admin.action(description="Kirim notifikasi tahap berikutnya")
    def send_next_notification_action(self, request, queryset):
        sent_count = 0
        for report in queryset.select_related(
            "reassessment",
            "periode",
            "prepared_by",
            "reviewed_by",
            "approved_by",
        ):
            sent_count += self._send_next_notification(request, report)
        if sent_count:
            self.message_user(request, f"Total email notifikasi terkirim: {sent_count}.", level=messages.SUCCESS)

    def risk_items_for_reassessment(self, request):
        reassessment_id = request.GET.get("reassessment")
        queryset = ReAssessmentItem.objects.none()
        if reassessment_id:
            queryset = _limit_by_assigned_units(
                request,
                ReAssessmentItem.objects.select_related("summary__unit_bisnis").filter(
                    summary_id=reassessment_id
                ),
                "summary__unit_bisnis",
            ).order_by(
                "no_item",
                "no_penyebab_risiko",
                "no_risiko",
                "id",
            )
        items = list(queryset)
        number_by_pk = _monthly_risk_item_number_map(items)

        return JsonResponse(
            {
                "items": [
                    {
                        "id": item.pk,
                        "text": _monthly_risk_item_label(item, number_by_pk),
                    }
                    for item in items
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

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        refresh_monthly_report_summary(form.instance)

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
