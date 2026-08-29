import calendar
from datetime import date

from django import forms
from django.contrib import admin
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.http import JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from riskproject.admin_site import risk_admin_site
from .excel_reports import XLSX_CONTENT_TYPE, build_monthly_risk_report_excel
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
    MonthlyRiskReportImportBatch,
    MonthlyRiskReportImportRow,
    MonthlyRiskReportEvidence,
    validate_https_evidence_url,
)

from masterdata.models import OrganizationUnit, TahunBuku
from risk.access_policy import organizational_groups_for_user
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
from .notifications import (
    monthly_report_notification_stage,
    resolve_monthly_report_notification_recipients,
    send_monthly_report_notification,
)
from .services import (
    duplicate_approved_report_to_next_month,
    initialize_monthly_report_structure_from_profile,
    initialize_monthly_report_structure_from_reference,
    refresh_monthly_report_summary,
    structure_reference_reports,
)
from .import_services import (
    IMPORT_PARSER_VERSION,
    analyze_import_batch,
    apply_import_batch,
    batch_analysis_is_current,
    build_display_changes,
    file_sha256,
    target_item_fingerprint,
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


# MONTHLY_ACTUAL_TIMELINE_UI_V1
MONTHLY_ACTUAL_TIMELINE_FIELDS = tuple(
    f"realisasi_timeline_{month}" for month in range(1, 13)
)
MONTHLY_ACTUAL_TIMELINE_CHOICES = (
    ("Q1", (("1", "Januari"), ("2", "Februari"), ("3", "Maret"))),
    ("Q2", (("4", "April"), ("5", "Mei"), ("6", "Juni"))),
    ("Q3", (("7", "Juli"), ("8", "Agustus"), ("9", "September"))),
    ("Q4", (("10", "Oktober"), ("11", "November"), ("12", "Desember"))),
)


class MonthlyActualTimelineWidget(forms.CheckboxSelectMultiple):
    template_name = "monthly_report/widgets/monthly_actual_timeline.html"


class MonthlyRiskReportImportForm(forms.Form):
    source_file = forms.FileField(
        label="File laporan profil risiko (.xlsx)",
        help_text="Gunakan template resmi yang memiliki sheet III.A dan III.B. Maksimum 10 MB.",
    )

    def clean_source_file(self):
        source_file = self.cleaned_data["source_file"]
        if source_file.size > 10 * 1024 * 1024:
            raise forms.ValidationError("Ukuran file maksimum 10 MB.")
        if not source_file.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("File harus berformat .xlsx.")
        return source_file


class MonthlyRiskReportNotificationForm(forms.Form):
    subject = forms.CharField(
        label="Subjek email",
        max_length=255,
        widget=forms.TextInput(attrs={"style": "width:100%;"}),
    )
    instruction = forms.CharField(
        label="Isi / instruksi email",
        widget=forms.Textarea(attrs={"rows": 6, "style": "width:100%;"}),
    )
    test_email = forms.EmailField(
        label="Email tujuan uji coba",
        required=False,
        help_text=(
            "Kirim Test hanya dikirim ke alamat ini tanpa CC/BCC "
            "penerima final."
        ),
        widget=forms.EmailInput(attrs={"style": "width:100%;"}),
    )
    confirm_final = forms.BooleanField(
        label="Saya telah memeriksa penerima, subjek, dan isi email",
        required=False,
    )


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
        exclude = ("tahun_buku", "periode", "unit", "kontrak_manajemen", "prepared_by")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.periode_id:
            self.fields["bulan_laporan"].initial = self.instance.periode.tanggal_mulai.month

        unit = self._selected_unit_bisnis()
        if unit:
            reviewed_by_field = self.fields.get("reviewed_by")
            if reviewed_by_field:
                risk_champions = _users_for_unit_role(
                    unit,
                    PenugasanUnitBisnis.ROLE_RISK_CHAMPION,
                )
                reviewed_by_field.queryset = risk_champions
                risk_champion = risk_champions.first()
                if risk_champion:
                    reviewed_by_field.initial = risk_champion.pk
                    self.initial["reviewed_by"] = risk_champion.pk
                reviewed_by_field.disabled = True
                reviewed_by_field.help_text = (
                    "Otomatis mengikuti Risk Champion aktif BID/Unit Bisnis laporan."
                )

            approved_by_field = self.fields.get("approved_by")
            if approved_by_field:
                approved_by_field.queryset = _users_for_unit_group(unit)

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

    def clean(self):
        cleaned_data = super().clean()
        reassessment = cleaned_data.get("reassessment") or getattr(self.instance, "reassessment", None)
        if reassessment and reassessment.unit_bisnis_id:
            risk_champion = _users_for_unit_role(
                reassessment.unit_bisnis,
                PenugasanUnitBisnis.ROLE_RISK_CHAMPION,
            ).first()
            if not risk_champion:
                self.add_error(
                    "reassessment",
                    "Belum ada Risk Champion aktif pada BID/Unit Bisnis yang dipilih.",
                )
            elif "reviewed_by" in self.fields:
                cleaned_data["reviewed_by"] = risk_champion

            first_officer = _users_for_unit_role(
                reassessment.unit_bisnis,
                PenugasanUnitBisnis.ROLE_RISK_OFFICER,
            ).first()
            if not first_officer:
                self.add_error(
                    "reassessment",
                    "Belum ada Risk Officer aktif pada BID/Unit Bisnis yang dipilih.",
                )
            elif not self.instance.prepared_by_id:
                # Kolom lama dipertahankan sebagai referensi kompatibilitas;
                # tampilan dan notifikasi memakai seluruh Risk Officer unit.
                self.instance.prepared_by = first_officer
        return cleaned_data


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
    """
    Scope laporan mengikuti Group organisasi BID/UB user.

    PenugasanUnitBisnis tetap digunakan untuk workflow,
    bukan untuk menentukan hak melihat data unit.
    """
    return organizational_groups_for_user(user).values_list(
        "id",
        flat=True,
    )


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


class MonthlyRiskReportItemForm(forms.ModelForm):
    realisasi_kri_text = forms.CharField(
        label="Realisasi KRI Teks / Komposit",
        required=False,
        max_length=100,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Contoh:\nR = 101%\nI = 35%",
            }
        ),
        help_text=(
            "Gunakan untuk KRI yang realisasinya tidak dapat dinyatakan dengan "
            "satu angka, misalnya beberapa indikator atau keterangan teks."
        ),
    )

    realisasi_kri_status_manual = forms.ChoiceField(
        label="Status Threshold KRI (untuk KRI Teks/Komposit)",
        required=False,
        choices=(
            ("", "---------"),
            ("green", "Hijau"),
            ("yellow", "Kuning"),
            ("red", "Merah"),
        ),
        help_text=(
            "Diisi hanya untuk KRI Teks/Komposit. "
            "Untuk KRI numerik, status dihitung otomatis oleh sistem."
        ),
    )

    realisasi_timeline_bulanan = forms.MultipleChoiceField(
        label="Realisasi Timeline Pelaksanaan",
        choices=MONTHLY_ACTUAL_TIMELINE_CHOICES,
        required=False,
        widget=MonthlyActualTimelineWidget(
            attrs={"class": "monthly-timeline-checkbox"}
        ),
        help_text=(
            "Centang bulan yang pada dokumen III.B ditandai sebagai realisasi timeline. "
            "Data ini tidak mengubah Timeline Rencana pada Profil Risiko."
        ),
    )

    class Meta:
        model = MonthlyRiskReportItem
        fields = "__all__"
        labels = {
            "risk_event": "Peristiwa Risiko",
            "realisasi_asumsi_dampak": "Asumsi Perhitungan Dampak",
            "realisasi_nilai_dampak": "Nilai Dampak",
            "realisasi_skala_dampak": "Skala Dampak BUMN",
            "realisasi_nilai_probabilitas": "Nilai Probabilitas (%)",
            "realisasi_skala_probabilitas": "Skala Probabilitas BUMN",
            "efektivitas_perlakuan_risiko": "Efektifitas Perlakuan Risiko",
            "jenis_risiko": "Jenis Risiko",
            "realisasi_eksposur": "Nilai Eksposur Risiko",
            "realisasi_skor_risiko": "Skala Nilai Risiko BUMN",
            "realisasi_skala_dampak_kbumn": "Skala Dampak KBUMN",
            "realisasi_skala_probabilitas_kbumn": "Skala Probabilitas KBUMN",
            "realisasi_skala_nilai_risiko_kbumn": "Skala Nilai Risiko KBUMN",
            "realisasi_level_risiko_bumn": "Level Risiko BUMN",
            "realisasi_level_risiko_kbumn": "Level Risiko KBUMN",
            "realisasi_rencana_perlakuan": "Realisasi Rencana Perlakuan Risiko",
            "realisasi_output_perlakuan": "Realisasi Output atas Masing-masing Breakdown Perlakuan Risiko",
            "realisasi_biaya_perlakuan": "Realisasi Biaya Perlakuan Risiko (Rp/USD)",
            "realisasi_pic_organization_unit": "Realisasi PIC",
            "status_rencana_perlakuan": "Status Rencana Perlakuan Risiko",
            "penjelasan_status_rencana": "Penjelasan Status Rencana Perlakuan",
            "progress_pelaksanaan_percent": "Progress Pelaksanaan Rencana Perlakuan (%)",
            "realisasi_nilai_kri": "Nilai Realisasi KRI",
            "next_action": "Tindak Lanjut Bulan Berikutnya",
            "escalation_note": "Catatan Eskalasi",
        }
        help_texts = {
            "realisasi_asumsi_dampak": "Tambahkan penjelasan atas asumsi atau pendekatan yang dipakai untuk menghitung nilai dampak.",
            "realisasi_nilai_dampak": "Isi realisasi perkiraan nilai dampak untuk risiko kuantitatif. Untuk risiko kualitatif, nilai numerik tidak wajib dan jangan isi 0 hanya sebagai placeholder.",
            "realisasi_skala_dampak": "Pilih skala dampak BUMN 1–5 sesuai definisi perusahaan.",
            "realisasi_nilai_probabilitas": "Isi nilai probabilitas risiko kuantitatif dalam persentase. Untuk risiko kualitatif, nilai numerik tidak wajib.",
            "realisasi_skala_probabilitas": "Pilih skala probabilitas BUMN 1–5 sesuai definisi perusahaan.",
            "realisasi_rencana_perlakuan": "Isi realisasi rencana perlakuan risiko yang telah dijalankan.",
            "realisasi_output_perlakuan": "Isi realisasi output untuk masing-masing rencana perlakuan risiko yang relevan.",
            "realisasi_biaya_perlakuan": "Isi realisasi biaya perlakuan risiko beserta satuan mata uang yang digunakan.",
            "progress_pelaksanaan_percent": "Isi progress pelaksanaan rencana perlakuan antara 0 sampai 100.",
            "realisasi_nilai_kri": "Status threshold dihitung otomatis berdasarkan nilai realisasi dan konfigurasi KRI.",
            "realisasi_skala_dampak_kbumn": "Isi skala dampak KBUMN antara 1 sampai 5 sesuai Kertas Kerja III.A.",
            "realisasi_skala_probabilitas_kbumn": "Isi skala probabilitas KBUMN antara 1 sampai 5 sesuai Kertas Kerja III.A.",
            "realisasi_eksposur": "Isi nilai eksposur risiko dalam Rupiah/USD sesuai Kertas Kerja III.A. Diisi manual atau melalui import Excel.",
            "realisasi_skor_risiko": "Isi skala nilai risiko BUMN antara 1 sampai 25 sesuai Kertas Kerja III.A.",
            "realisasi_skala_nilai_risiko_kbumn": "Isi skala nilai risiko KBUMN antara 1 sampai 25 sesuai Kertas Kerja III.A.",
            "realisasi_level_risiko_bumn": "Isi level risiko BUMN sesuai Kertas Kerja III.A.",
            "realisasi_level_risiko_kbumn": "Isi level risiko KBUMN sesuai Kertas Kerja III.A.",
            "next_action": "Jelaskan tindakan yang akan dilakukan pada periode berikutnya.",
            "escalation_note": "Isi apabila terdapat kendala atau kondisi yang perlu dilaporkan kepada pejabat yang lebih tinggi.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance:
            self.initial["realisasi_timeline_bulanan"] = [
                str(month)
                for month in range(1, 13)
                if int(getattr(self.instance, f"realisasi_timeline_{month}", 0) or 0)
            ]
        self.fields["efektivitas_perlakuan_risiko"].choices = (
            ("", "---------"),
            ("efektif", "Efektif"),
            ("tidak_efektif", "Tidak Efektif"),
        )
        for field_name in (
            "realisasi_skala_dampak_kbumn",
            "realisasi_skala_probabilitas_kbumn",
        ):
            self.fields[field_name].widget.attrs.update({"min": 1, "max": 5, "step": 1})
        for field_name in (
            "realisasi_skor_risiko",
            "realisasi_skala_nilai_risiko_kbumn",
        ):
            self.fields[field_name].widget.attrs.update({"min": 1, "max": 25, "step": 1})
        self.fields["realisasi_eksposur"].widget.attrs.update({"min": 0, "step": "0.01"})
        report = self.instance.report if self.instance and self.instance.report_id else None
        if report and report.periode_id and report.periode.tanggal_mulai:
            month_name = BULAN_LABELS[report.periode.tanggal_mulai.month]
            quarter = ((report.periode.tanggal_mulai.month - 1) // 3) + 1
            self.fields["realisasi_nilai_dampak"].label = f"Nilai Dampak Q{quarter}"
            self.fields["realisasi_skala_dampak"].label = f"Skala Dampak BUMN Q{quarter}"
            self.fields["realisasi_nilai_probabilitas"].label = f"Nilai Probabilitas Q{quarter} (%)"
            self.fields["realisasi_skala_probabilitas"].label = (
                f"Skala Probabilitas BUMN Q{quarter}"
            )
            self.fields["realisasi_skala_dampak_kbumn"].label = f"Skala Dampak KBUMN Q{quarter}"
            self.fields["realisasi_skala_probabilitas_kbumn"].label = f"Skala Probabilitas KBUMN Q{quarter}"
            self.fields["realisasi_eksposur"].label = f"Nilai Eksposur Risiko Q{quarter}"
            self.fields["realisasi_skor_risiko"].label = f"Skala Nilai Risiko BUMN Q{quarter}"
            self.fields["realisasi_skala_nilai_risiko_kbumn"].label = f"Skala Nilai Risiko KBUMN Q{quarter}"
            self.fields["realisasi_level_risiko_bumn"].label = f"Level Risiko BUMN Q{quarter}"
            self.fields["realisasi_level_risiko_kbumn"].label = f"Level Risiko KBUMN Q{quarter}"
            self.fields["realisasi_nilai_kri"].label = f"Nilai Realisasi KRI {month_name}"
            self.fields["realisasi_kri_text"].label = (
                f"Realisasi KRI Teks / Komposit {month_name}"
            )
        risk = self.instance.risk_event if self.instance and self.instance.risk_event_id else None

        # Legacy/historical KRI non-numerik:
        # realisasi_threshold_kri_skor selama ini memang digunakan untuk
        # menyimpan skor/rentang berbentuk teks.
        if (
            self.instance
            and self.instance.pk
            and self.instance.realisasi_nilai_kri is None
        ):
            legacy_kri_text = (
                self.instance.realisasi_threshold_kri_skor or ""
            ).strip()
            if legacy_kri_text:
                self.initial["realisasi_kri_text"] = legacy_kri_text

                raw_status = (
                    self.instance.realisasi_threshold_kri or ""
                ).strip().casefold()
                status_map = {
                    "green": "green",
                    "hijau": "green",
                    "3. hijau": "green",
                    "yellow": "yellow",
                    "kuning": "yellow",
                    "2. kuning": "yellow",
                    "red": "red",
                    "merah": "red",
                    "1. merah": "red",
                }
                if raw_status in status_map:
                    self.initial["realisasi_kri_status_manual"] = (
                        status_map[raw_status]
                    )

        pic_field = self.fields["realisasi_pic_organization_unit"]
        pic_field.label = "Mapping PIC ke Master Organisasi"
        pic_field.queryset = OrganizationUnit.objects.filter(aktif=True).order_by("code")
        pic_field.help_text = (
            "Pilih unit PIC aktif dari Master Organisasi hanya jika mapping "
            "resminya sudah diketahui. Ketik kode atau nama untuk mencari."
        )
        if (
            self.instance
            and not self.instance.realisasi_pic_organization_unit_id
            and self.instance.realisasi_pic
        ):
            legacy_pic = self.instance.realisasi_pic.strip()
            match = pic_field.queryset.filter(code__iexact=legacy_pic).first()
            if match is None:
                match = pic_field.queryset.filter(name__iexact=legacy_pic).first()
            if match:
                self.initial["realisasi_pic_organization_unit"] = match.pk
            else:
                pic_field.help_text = (
                    "Belum terhubung ke Master Organisasi. "
                    "Biarkan kosong sampai mapping resmi PIC diketahui."
                )
        if risk:
            canonical_risk_type = getattr(risk, "jenis_risiko", None)
            if canonical_risk_type in {"kuantitatif", "kualitatif"}:
                self.initial["jenis_risiko"] = canonical_risk_type
                self.fields["jenis_risiko"].disabled = True
                self.fields["jenis_risiko"].help_text = (
                    "Mengikuti Jenis Risiko pada Profil Risiko dan tidak diubah "
                    "di laporan bulanan."
                )
            self.fields["realisasi_nilai_kri"].widget.attrs.update({
                "data-kri-direction": risk.kri_threshold_direction or "",
                "data-kri-green": risk.threshold_aman or "",
                "data-kri-yellow": risk.threshold_hati_hati or "",
                "data-kri-red": risk.threshold_bahaya or "",
                "data-kri-unit": risk.unit_satuan_kri or "",
            })
        widgets = {
            "realisasi_asumsi_dampak": forms.Textarea(attrs={"rows": 3}),
            "realisasi_rencana_perlakuan": forms.Textarea(attrs={"rows": 3}),
            "realisasi_output_perlakuan": forms.Textarea(attrs={"rows": 3}),
            "penjelasan_status_rencana": forms.Textarea(attrs={"rows": 3}),
            "next_action": forms.Textarea(attrs={"rows": 3}),
            "escalation_note": forms.Textarea(attrs={"rows": 3}),
        }

    def _threshold_for_kri_status(self, status):
        risk = self.risk
        if not risk:
            return None

        return {
            "green": risk.threshold_aman,
            "yellow": risk.threshold_hati_hati,
            "red": risk.threshold_bahaya,
        }.get(status)

    def clean(self):
        cleaned = super().clean()

        numeric_value = cleaned.get("realisasi_nilai_kri")
        text_value = (cleaned.get("realisasi_kri_text") or "").strip()
        manual_status = cleaned.get("realisasi_kri_status_manual")

        if numeric_value is not None and text_value:
            self.add_error(
                "realisasi_kri_text",
                "Isi salah satu saja: Nilai Realisasi KRI numerik atau "
                "Realisasi KRI Teks/Komposit.",
            )

        if text_value and not manual_status:
            self.add_error(
                "realisasi_kri_status_manual",
                "Status Threshold wajib dipilih untuk KRI Teks/Komposit.",
            )

        if manual_status and not text_value:
            self.add_error(
                "realisasi_kri_text",
                "Isi realisasi KRI Teks/Komposit jika menggunakan status manual.",
            )

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)

        kri_text = (self.cleaned_data.get("realisasi_kri_text") or "").strip()
        manual_status = self.cleaned_data.get("realisasi_kri_status_manual")

        if kri_text:
            # Mode KRI Teks/Komposit:
            # jangan jalankan evaluator numerik.
            obj.realisasi_nilai_kri = None
            obj.realisasi_kri_text = kri_text
            obj.realisasi_threshold_kri_skor = (
                self._threshold_for_kri_status(manual_status)
            )
            obj.realisasi_threshold_kri = manual_status
        elif self.cleaned_data.get("realisasi_nilai_kri") is None:
            # Kedua mode kosong: kosongkan hasil KRI.
            obj.realisasi_threshold_kri = None
            obj.realisasi_threshold_kri_skor = None

        # Bila realisasi_nilai_kri berisi angka, tidak perlu set status di sini.
        # Model akan menjalankan evaluator threshold numerik seperti sebelumnya.

        selected = set(self.cleaned_data.get("realisasi_timeline_bulanan", ()))
        for month in range(1, 13):
            setattr(obj, f"realisasi_timeline_{month}", 1 if str(month) in selected else 0)
        if commit:
            obj.save()
            self.save_m2m()
        return obj

    def _value(self, field_name):
        if self.is_bound and field_name in self.fields:
            return self[field_name].value()
        return getattr(self.instance, field_name, None)

    @property
    def risk(self):
        return self.instance.risk_event if self.instance and self.instance.risk_event_id else None

    @property
    def risk_heading(self):
        risk_number = self.risk.no_risiko if self.risk else self._value("risk_event") or "Baru"
        period = (
            self.instance.report.periode.nama_periode
            if self.instance and self.instance.report_id and self.instance.report.periode_id
            else "periode laporan"
        )
        return f"Risiko {risk_number} – Pemantauan {period}"

    @property
    def active_period_context(self):
        if not self.instance or not self.instance.report_id or not self.instance.report.periode_id:
            return "Quarter aktif belum tersedia"
        period = self.instance.report.periode
        quarter = ((period.tanggal_mulai.month - 1) // 3) + 1
        return f"Quarter aktif: Q{quarter} | Periode laporan: {period.nama_periode}"

    @property
    def system_code(self):
        return str(self.instance) if self.instance and self.instance.pk else "Kode dibuat setelah disimpan"

    def _has_kri_realisasi(self):
        numeric_value = self._value("realisasi_nilai_kri")

        if self.is_bound and "realisasi_kri_text" in self.fields:
            text_value = self["realisasi_kri_text"].value()
        else:
            text_value = self.initial.get("realisasi_kri_text")

        return (
            numeric_value not in (None, "")
            or (text_value or "").strip() != ""
        )

    @property
    def completion_status(self):
        if self.errors:
            return "Perlu Diperiksa"
        required_values = [
            self._value(name)
            for name, _label in self.required_monitoring_fields
        ]
        base_complete = all(
            value not in (None, "") for value in required_values
        )

        kri_required = bool(
            self.risk and (self.risk.key_risk_indicators or "").strip()
        )
        kri_complete = (
            not kri_required or self._has_kri_realisasi()
        )

        return (
            "Lengkap"
            if base_complete and kri_complete
            else "Belum Lengkap"
        )

    @property
    def required_monitoring_fields(self):
        fields = [
            ("risk_event", "risiko"),
            ("realisasi_skala_dampak", "skala dampak"),
            ("realisasi_skala_probabilitas", "skala probabilitas"),
            ("realisasi_eksposur", "nilai eksposur"),
            ("realisasi_skor_risiko", "skala nilai risiko"),
            ("realisasi_level_risiko_bumn", "level risiko BUMN belum tersedia pada Kertas Kerja III.A"),
            ("status_rencana_perlakuan", "status mitigasi"),
            ("progress_pelaksanaan_percent", "progres mitigasi"),
        ]
        return fields

    @property
    def missing_fields_display(self):
        missing = [
            label for name, label in self.required_monitoring_fields
            if self._value(name) in (None, "")
        ]

        if (
            self.risk
            and (self.risk.key_risk_indicators or "").strip()
            and not self._has_kri_realisasi()
        ):
            missing.append("realisasi KRI")

        return ", ".join(missing)

    @property
    def kri_status_display(self):
        value = (self.instance.realisasi_threshold_kri or "").strip().casefold()
        labels = {
            "green": "Hijau", "hijau": "Hijau", "3. hijau": "Hijau",
            "yellow": "Kuning", "kuning": "Kuning", "2. kuning": "Kuning",
            "red": "Merah", "merah": "Merah", "1. merah": "Merah",
        }
        return labels.get(value, self.instance.realisasi_threshold_kri or "Belum diisi")

    @property
    def should_open(self):
        return bool(self.errors)

    @property
    def status_mitigasi_display(self):
        return self.instance.get_status_rencana_perlakuan_display() if self.instance.pk else "-"


class MonthlyRiskReportItemInline(admin.StackedInline):
    model = MonthlyRiskReportItem
    form = MonthlyRiskReportItemForm
    template = "admin/monthly_report/monthlyriskreport/edit_inline/monitoring_stacked.html"
    extra = 0
    autocomplete_fields = ("realisasi_pic_organization_unit",)
    readonly_fields = (
        "risk_event",
        "data_item_profil",
        "nomor_risiko_profil",
        "peristiwa_risiko_profil",
        "asumsi_dampak_inheren",
        "nilai_dampak_inheren",
        "skala_dampak_bumn_inheren",
        "skala_dampak_kbumn_inheren",
        "nilai_probabilitas_inheren",
        "skala_probabilitas_bumn_inheren",
        "skala_probabilitas_kbumn_inheren",
        "eksposur_risiko_inheren",
        "skala_nilai_risiko_bumn_inheren",
        "deskripsi_peristiwa_risiko_profil",
        "nomor_penyebab_risiko_profil",
        "kode_penyebab_risiko_profil",
        "penyebab_risiko_profil",
        "rencana_perlakuan_risiko_profil",
        "output_perlakuan_risiko_profil",
        "biaya_perlakuan_risiko_profil",
        "realisasi_timeline_profil",
        "key_risk_indicators_profil",
        "unit_satuan_kri_profil",
        "threshold_aman_profil",
        "threshold_hati_hati_profil",
        "threshold_bahaya_profil",
        "satuan_kri_otomatis",
        "status_threshold_kri",
        "rentang_threshold_kri",
        "persentase_serapan_biaya",
        "serapan_biaya_mitigasi",
        "pic_dokumen_sumber",
    )
    verbose_name = "Risiko yang Dipantau"
    verbose_name_plural = "III.A & III.B – Pemantauan Risiko Bulanan"

    @admin.display(description="PIC pada Dokumen Sumber")
    def pic_dokumen_sumber(self, obj):
        if not obj or not obj.pk:
            return "-"
        return (obj.realisasi_pic or "-").strip() or "-"

    fieldsets = (
        (
            "REFERENSI PROFIL RISIKO (klik untuk membuka)",
            {
                "classes": ("collapse", "profile-reference"),
                "description": "Data sumber dari profil risiko. Gunakan sebagai referensi; bagian ini tidak perlu diisi ulang.",
                "fields": (
                    "data_item_profil",
                    "nomor_risiko_profil",
                    "peristiwa_risiko_profil",
                    "jenis_risiko",
                    "asumsi_dampak_inheren",
                    "nilai_dampak_inheren",
                    "skala_dampak_bumn_inheren",
                    "skala_dampak_kbumn_inheren",
                    "nilai_probabilitas_inheren",
                    "skala_probabilitas_bumn_inheren",
                    "skala_probabilitas_kbumn_inheren",
                    "eksposur_risiko_inheren",
                    "skala_nilai_risiko_bumn_inheren",
                ),
            },
        ),
        (
            "REALISASI RESIDUAL RISK – QUARTER AKTIF",
            {
                "classes": ("residual-grid",),
                "description": "Isi hasil pemantauan residual untuk quarter aktif. Field berlabel dihitung otomatis tidak perlu diketik.",
                "fields": (
                    "realisasi_asumsi_dampak",
                    "realisasi_nilai_dampak",
                    "realisasi_skala_dampak",
                    "realisasi_skala_dampak_kbumn",
                    "realisasi_nilai_probabilitas",
                    "realisasi_skala_probabilitas",
                    "realisasi_skala_probabilitas_kbumn",
                    "realisasi_eksposur",
                    "realisasi_skor_risiko",
                    "realisasi_skala_nilai_risiko_kbumn",
                    "realisasi_level_risiko_bumn",
                    "realisasi_level_risiko_kbumn",
                    "efektivitas_perlakuan_risiko",
                ),
            },
        ),
        (
            "REFERENSI RENCANA PERLAKUAN (klik untuk membuka)",
            {
                "classes": ("collapse", "profile-reference"),
                "description": "Rencana, target output, biaya, PIC, dan timeline dari profil risiko.",
                "fields": (
                    "deskripsi_peristiwa_risiko_profil",
                    "nomor_penyebab_risiko_profil",
                    "kode_penyebab_risiko_profil",
                    "penyebab_risiko_profil",
                    "rencana_perlakuan_risiko_profil",
                    "output_perlakuan_risiko_profil",
                    "biaya_perlakuan_risiko_profil",
                    "realisasi_timeline_profil",
                ),
            },
        ),
        (
            "III.B – REALISASI PERLAKUAN RISIKO BULAN INI",
            {
                "description": "Isi hanya perkembangan yang benar-benar terjadi pada bulan laporan.",
                "fields": (
                    "realisasi_rencana_perlakuan",
                    "realisasi_output_perlakuan",
                    "realisasi_biaya_perlakuan",
                    "serapan_biaya_mitigasi",
                    "pic_dokumen_sumber",
                    "realisasi_pic_organization_unit",
                    "realisasi_timeline_bulanan",
                    "status_rencana_perlakuan",
                    "penjelasan_status_rencana",
                    "progress_pelaksanaan_percent",
                ),
            },
        ),
        (
            "REFERENSI KONFIGURASI KRI (klik untuk membuka)",
            {
                "classes": ("collapse", "profile-reference"),
                "description": "Indikator, satuan, dan batas kategori yang ditetapkan pada profil risiko.",
                "fields": (
                    "key_risk_indicators_profil",
                    "unit_satuan_kri_profil",
                    "threshold_aman_profil",
                    "threshold_hati_hati_profil",
                    "threshold_bahaya_profil",
                ),
            },
        ),
        (
            "REALISASI KEY RISK INDICATOR BULAN INI",
            {
                "classes": ("kri-current",),
                "description": (
                    "Untuk KRI numerik, isi Nilai Realisasi KRI dan status akan "
                    "dihitung otomatis. Untuk KRI Teks/Komposit, isi field teks "
                    "dan pilih status threshold secara manual. Isi salah satu mode saja."
                ),
                "fields": (
                    "realisasi_nilai_kri",
                    "realisasi_kri_text",
                    "realisasi_kri_status_manual",
                    "satuan_kri_otomatis",
                    "status_threshold_kri",
                    "rentang_threshold_kri",
                ),
            },
        ),
        (
            "CATATAN TAMBAHAN ERM",
            {
                "classes": ("collapse",),
                "description": (
                    "Bagian ini merupakan catatan tambahan aplikasi ERM dan tidak "
                    "termasuk kolom standar Lampiran III.A atau III.B."
                ),
                "fields": (
                    "next_action",
                    "escalation_note",
                ),
            },
        ),
    )

    @staticmethod
    def _is_approved_report(obj):
        return bool(
            obj
            and getattr(obj, "status", None) == "approved"
        )

    def has_change_permission(self, request, obj=None):
        if self._is_approved_report(obj):
            return False
        return super().has_change_permission(request, obj)

    def has_add_permission(self, request, obj=None):
        if self._is_approved_report(obj):
            return False
        return super().has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self._is_approved_report(obj):
            return False
        return super().has_delete_permission(request, obj)

    def get_extra(self, request, obj=None, **kwargs):
        if self._is_approved_report(obj):
            return 0
        return super().get_extra(request, obj, **kwargs)

    def get_fieldsets(self, request, obj=None):
        fieldsets = list(super().get_fieldsets(request, obj))
        if obj and obj.periode_id and obj.periode.tanggal_mulai:
            period_date = obj.periode.tanggal_mulai
            quarter = ((period_date.month - 1) // 3) + 1
            month_name = BULAN_LABELS[period_date.month].upper()
            fieldsets[1] = (
                f"REALISASI RESIDUAL RISK – Q{quarter} / {month_name} {period_date.year}",
                fieldsets[1][1],
            )
        return tuple(fieldsets)

    @admin.display(description="Persentase Serapan Biaya")
    def serapan_biaya_mitigasi(self, obj):
        # COST_ABSORPTION_DISPLAY_V2
        if not obj or not obj.pk or obj.persentase_serapan_biaya is None:
            return "-"
        return f"{obj.persentase_serapan_biaya:.2f}%"


    def _risk_value(self, obj, field_name):
        risk = obj.risk_event if obj and obj.risk_event_id else None
        value = getattr(risk, field_name, None) if risk else None
        return value if value not in (None, "") else "Data belum lengkap"

    @admin.display(description="Data Item")
    def data_item_profil(self, obj):
        return self._risk_value(obj, "no_item")

    @admin.display(description="No. Risiko")
    def nomor_risiko_profil(self, obj):
        return self._risk_value(obj, "no_risiko")

    @admin.display(description="Peristiwa Risiko")
    def peristiwa_risiko_profil(self, obj):
        return self._risk_value(obj, "peristiwa_risiko")

    @admin.display(description="Asumsi Perhitungan Dampak Kuantitatif / Penjelasan Dampak Kualitatif")
    def asumsi_dampak_inheren(self, obj):
        return self._risk_value(obj, "asumsi_perhitungan_dampak")

    @admin.display(description="Nilai Dampak Risiko Inheren")
    def nilai_dampak_inheren(self, obj):
        return self._risk_value(obj, "nilai_dampak")

    @admin.display(description="Skala Dampak BUMN Risiko Inheren")
    def skala_dampak_bumn_inheren(self, obj):
        return self._risk_value(obj, "skala_dampak")

    @admin.display(description="Skala Dampak KBUMN Risiko Inheren — Dihitung otomatis")
    def skala_dampak_kbumn_inheren(self, obj):
        return "Data belum lengkap"

    @admin.display(description="Nilai Probabilitas Risiko Inheren (%)")
    def nilai_probabilitas_inheren(self, obj):
        return self._risk_value(obj, "nilai_probabilitas")

    @admin.display(description="Skala Probabilitas BUMN Risiko Inheren")
    def skala_probabilitas_bumn_inheren(self, obj):
        return self._risk_value(obj, "skala_probabilitas")

    @admin.display(description="Skala Probabilitas KBUMN Risiko Inheren — Dihitung otomatis")
    def skala_probabilitas_kbumn_inheren(self, obj):
        return "Data belum lengkap"

    @admin.display(description="Eksposur Risiko Inheren — Dihitung otomatis")
    def eksposur_risiko_inheren(self, obj):
        return self._risk_value(obj, "eksposur_risiko")

    @admin.display(description="Skala Nilai Risiko BUMN Risiko Inheren")
    def skala_nilai_risiko_bumn_inheren(self, obj):
        return self._risk_value(obj, "skala_risiko")

    @admin.display(description="Deskripsi Peristiwa Risiko")
    def deskripsi_peristiwa_risiko_profil(self, obj):
        return self._risk_value(obj, "deskripsi_peristiwa_risiko")

    @admin.display(description="No. Penyebab Risiko")
    def nomor_penyebab_risiko_profil(self, obj):
        return self._risk_value(obj, "no_penyebab_risiko")

    @admin.display(description="Kode Penyebab Risiko")
    def kode_penyebab_risiko_profil(self, obj):
        return self._risk_value(obj, "kode_penyebab_risiko")

    @admin.display(description="Penyebab Risiko")
    def penyebab_risiko_profil(self, obj):
        return self._risk_value(obj, "penyebab_risiko")

    @admin.display(description="Rencana Perlakuan Risiko")
    def rencana_perlakuan_risiko_profil(self, obj):
        return self._risk_value(obj, "rencana_perlakuan_risiko")

    @admin.display(description="Output Perlakuan Risiko")
    def output_perlakuan_risiko_profil(self, obj):
        return self._risk_value(obj, "output_perlakuan_risiko")

    @admin.display(description="Biaya Perlakuan Risiko")
    def biaya_perlakuan_risiko_profil(self, obj):
        return self._risk_value(obj, "biaya_perlakuan_risiko")

    @admin.display(description="Timeline Rencana (Profil) – Bulan Ini")
    def realisasi_timeline_profil(self, obj):
        if not obj or not obj.report_id or not obj.report.periode_id:
            return "Data belum lengkap"
        return self._risk_value(
            obj, f"timeline_{obj.report.periode.tanggal_mulai.month}"
        )

    @admin.display(description="Key Risk Indicators")
    def key_risk_indicators_profil(self, obj):
        return self._risk_value(obj, "key_risk_indicators")

    @admin.display(description="Unit Satuan KRI")
    def unit_satuan_kri_profil(self, obj):
        return self._risk_value(obj, "unit_satuan_kri")

    @admin.display(description="Kategori Threshold Aman")
    def threshold_aman_profil(self, obj):
        return self._risk_value(obj, "threshold_aman")

    @admin.display(description="Kategori Threshold Hati-Hati")
    def threshold_hati_hati_profil(self, obj):
        return self._risk_value(obj, "threshold_hati_hati")

    @admin.display(description="Kategori Threshold Bahaya")
    def threshold_bahaya_profil(self, obj):
        return self._risk_value(obj, "threshold_bahaya")

    @admin.display(description="Satuan KRI")
    def satuan_kri_otomatis(self, obj):
        return self._risk_value(obj, "unit_satuan_kri")

    @admin.display(description="Status Threshold")
    def status_threshold_kri(self, obj):
        from .kri_services import STATUS_LABELS

        value = (obj.realisasi_threshold_kri or "").strip().casefold() if obj else ""
        legacy = {
            "3. hijau": "green", "hijau": "green", "green": "green",
            "2. kuning": "yellow", "kuning": "yellow", "yellow": "yellow",
            "1. merah": "red", "merah": "red", "red": "red",
        }
        status = legacy.get(value)
        if not status:
            return "Belum diisi" if not value else f"Legacy: {obj.realisasi_threshold_kri}"
        return format_html(
            '<span class="kri-status-badge kri-{}">{}</span>',
            status,
            STATUS_LABELS[status],
        )

    @admin.display(description="Rentang Threshold")
    def rentang_threshold_kri(self, obj):
        return obj.realisasi_threshold_kri_skor or "Belum diisi" if obj else "Belum diisi"

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
        request._monthly_report_period_start = (
            obj.periode.tanggal_mulai
            if obj and obj.periode_id
            else None
        )
        request._monthly_report_period_end = (
            obj.periode.tanggal_selesai
            if obj and obj.periode_id
            else None
        )
        formset = super().get_formset(request, obj, **kwargs)

        if reassessment_id:
            try:
                reassessment_obj = ReAssessmentSummary.objects.get(
                    pk=reassessment_id
                )
                if (
                    obj
                    and obj.periode_id
                ):
                    risk_event_qs = reassessment_obj.items_for_period(
                        obj.periode.tanggal_mulai,
                        obj.periode.tanggal_selesai,
                    )
                else:
                    risk_event_qs = reassessment_obj.active_items()
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


class MonthlyRiskReportEvidenceInline(admin.TabularInline):
    model = MonthlyRiskReportEvidence
    extra = 1
    fields = ("title", "description", "external_url", "uploaded_by", "created_at")
    readonly_fields = ("uploaded_by", "created_at")
    verbose_name = "Eviden Pendukung"
    verbose_name_plural = "Eviden Pendukung — link eksternal"


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
                "monthly_report/admin/monthly_report_monitoring.css",
                "risk/css/monthly_timeline.css",
            )
        }
        js = (
            "admin/js/vendor/select2/select2.full.js",
            "monthly_report/admin/monthly_report_items_searchable.js",
            "monthly_report/admin/monthly_report_monitoring.js",
            "risk/js/monthly_timeline.js",
        )

    fields = [
        "reassessment",
        "bulan_laporan",
        "petunjuk_lampiran",
        "peta_risiko_iiic_link",
        "versi",
        "status",
        "copy_source_display",
        "flow_action_button",
        "latest_revision_comment",
        "notification_button",
        "import_profile_button",
        "evidence_url",
        "prepared_by_display",
        "reviewed_by",
        "approved_by",
    ]
    readonly_fields = [
        "petunjuk_lampiran",
        "peta_risiko_iiic_link",
        "flow_action_button",
        "latest_revision_comment",
        "notification_button",
        "import_profile_button",
        "prepared_by_display",
        "copy_source_display",
    ]
    autocomplete_fields = (
        "reassessment",
    )

    list_display = [
        "profile_display",
        "bulan_laporan_display",
        "status",
        "total_risiko",
        "total_high",
        "total_mitigasi_terlambat",
        "flow_action_button",
        "notification_button",
        "web_button",
        "excel_button",
        "import_profile_button",
        "duplicate_next_month_button",
    ]
    list_filter = [MonthlyRiskReportGroupFilter, "status"]
    actions = []
    search_fields = [
        "reassessment__judul",
        "reassessment__unit_bisnis__name",
    ]

    NOTIFICATION_ADMIN_GROUPS = {
        "Admin ERM",
        "ERM Admin",
        "Risk Admin",
        "Risk Administrator",
        "Admin Risiko",
    }

    @staticmethod
    def _is_approved_report(obj):
        return bool(
            obj
            and getattr(obj, "status", None) == "approved"
        )

    def has_change_permission(self, request, obj=None):
        if self._is_approved_report(obj):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self._is_approved_report(obj):
            return False
        return super().has_delete_permission(request, obj)

    def _can_manage_notifications(self, request):
        user = request.user
        return bool(
            user
            and user.is_active
            and user.is_staff
            and (
                user.is_superuser
                or user.groups.filter(
                    name__in=self.NOTIFICATION_ADMIN_GROUPS
                ).exists()
            )
        )

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
                "<path:object_id>/excel/",
                self.admin_site.admin_view(self.excel_report_view),
                name="monthly_report_monthlyriskreport_excel",
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
                "<path:object_id>/duplicate-next-month/",
                self.admin_site.admin_view(self.duplicate_next_month_view),
                name="monthly_report_monthlyriskreport_duplicate_next_month",
            ),
            path(
                "<path:object_id>/import-profile/",
                self.admin_site.admin_view(self.import_profile_view),
                name="monthly_report_monthlyriskreport_import_profile",
            ),
            path(
                "<path:object_id>/import-profile/<int:batch_id>/review/",
                self.admin_site.admin_view(self.import_profile_review_view),
                name="monthly_report_monthlyriskreport_import_profile_review",
            ),
            path(
                "risk-items/",
                self.admin_site.admin_view(self.risk_items_for_reassessment),
                name="monthly_report_monthlyriskreport_risk_items",
            ),
        ]
        return custom_urls + urls

    def get_fields(self, request, obj=None):
        fields = list(super().get_fields(request, obj))
        if not self._can_manage_notifications(request):
            fields = [field for field in fields if field != "notification_button"]
        return fields

    def get_list_display(self, request):
        list_display = list(super().get_list_display(request))
        if not self._can_manage_notifications(request):
            list_display = [field for field in list_display if field != "notification_button"]
        return list_display

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("send_next_notification_action", None)
        return actions

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj and "status" not in readonly_fields:
            readonly_fields.append("status")
        return readonly_fields

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, MonthlyRiskReportEvidence) and not instance.uploaded_by_id:
                instance.uploaded_by = request.user
            instance.save()
        for instance in formset.deleted_objects:
            instance.delete()
        formset.save_m2m()

    @admin.display(description="Import Excel")
    def import_profile_button(self, obj):
        if not obj or not obj.pk or obj.status not in {"draft", "revision"}:
            return "-"
        url = reverse(
            f"{self.admin_site.name}:monthly_report_monthlyriskreport_import_profile",
            args=[obj.pk],
        )
        return format_html('<a class="button" href="{}">Upload & Analisis</a>', url)

    def _import_report(self, request, object_id):
        report = self.get_object(request, object_id)
        if report is None:
            raise Http404("Monthly risk report tidak ditemukan.")
        if not self.has_change_permission(request, report):
            raise PermissionDenied("Anda tidak memiliki izin mengubah laporan ini.")
        if report.status not in {"draft", "revision"}:
            raise PermissionDenied("Import hanya tersedia untuk laporan Draft atau Revision.")
        return report

    def import_profile_view(self, request, object_id):
        report = self._import_report(request, object_id)
        form = MonthlyRiskReportImportForm(request.POST or None, request.FILES or None)
        if (
            request.method == "POST"
            and request.POST.get("action") == "initialize_profile"
        ):
            try:
                profile, total, created = (
                    initialize_monthly_report_structure_from_profile(report)
                )
            except ValidationError as exc:
                self.message_user(
                    request, "; ".join(exc.messages), level=messages.ERROR
                )
            else:
                self.message_user(
                    request,
                    f"Struktur Profil Risiko {profile.judul}: {total} item "
                    f"tersedia ({created} item dibuat).",
                    level=messages.SUCCESS,
                )
            return redirect(request.path)
        if request.method == "POST" and form.is_valid():
            source_file = form.cleaned_data["source_file"]
            digest = file_sha256(source_file)
            existing = MonthlyRiskReportImportBatch.objects.filter(
                report=report,
                file_sha256=digest,
                parser_version=IMPORT_PARSER_VERSION,
                target_fingerprint=target_item_fingerprint(report),
            ).first()
            if existing and batch_analysis_is_current(existing):
                self.message_user(
                    request,
                    "File yang sama sudah pernah diunggah. Menampilkan hasil sebelumnya.",
                    level=messages.WARNING,
                )
                return redirect(
                    reverse(
                        f"{self.admin_site.name}:monthly_report_monthlyriskreport_import_profile_review",
                        args=[report.pk, existing.pk],
                    )
                )
            batch = MonthlyRiskReportImportBatch.objects.create(
                report=report,
                source_file=source_file,
                original_filename=source_file.name,
                file_sha256=digest,
                parser_version=IMPORT_PARSER_VERSION,
                uploaded_by=request.user,
            )
            try:
                analyze_import_batch(batch)
            except Exception as exc:
                batch.status = batch.STATUS_FAILED
                batch.error_message = str(exc)
                batch.save(update_fields=["status", "error_message", "updated_at"])
                self.message_user(request, f"Analisis gagal: {exc}", level=messages.ERROR)
            return redirect(
                reverse(
                    f"{self.admin_site.name}:monthly_report_monthlyriskreport_import_profile_review",
                    args=[report.pk, batch.pk],
                )
            )
        context = {
            **self.admin_site.each_context(request),
            "title": "Upload Laporan Profil Risiko",
            "opts": self.model._meta,
            "report": report,
            "form": form,
            "profile": report.reassessment,
            "profile_item_count": report.profile_items_queryset().count(),
            "profile_status": getattr(
                report.reassessment, "status", "Status tidak tersedia"
            ),
            "target_is_empty": not report.items.exists(),
            "batches": report.import_batches.select_related("uploaded_by").order_by("-created_at")[:10],
            "cancel_url": reverse(
                f"{self.admin_site.name}:monthly_report_monthlyriskreport_change", args=[report.pk]
            ),
        }
        return TemplateResponse(
            request,
            "admin/monthly_report/monthlyriskreport/import_profile.html",
            context,
        )

    def import_profile_review_view(self, request, object_id, batch_id):
        report = self._import_report(request, object_id)
        batch = MonthlyRiskReportImportBatch.objects.filter(
            pk=batch_id, report=report
        ).first()
        if batch is None:
            raise Http404("Batch import tidak ditemukan.")
        rows = list(batch.rows.select_related("matched_report_item__risk_event").order_by("pk"))
        if (
            request.method == "POST"
            and request.POST.get("action") == "initialize_profile"
        ):
            try:
                profile, total, created = (
                    initialize_monthly_report_structure_from_profile(report)
                )
                analyze_import_batch(batch)
            except ValidationError as exc:
                self.message_user(
                    request, "; ".join(exc.messages), level=messages.ERROR
                )
            except Exception as exc:
                self.message_user(
                    request,
                    f"Struktur telah diperiksa, tetapi analisis file gagal: {exc}",
                    level=messages.ERROR,
                )
            else:
                self.message_user(
                    request,
                    f"Struktur Profil Risiko {profile.judul}: {total} item "
                    f"tersedia ({created} item dibuat); analisis dijalankan ulang.",
                    level=messages.SUCCESS,
                )
            return redirect(request.path)
        if request.method == "POST" and batch.status == batch.STATUS_REVIEW:
            if request.POST.get("action") == "copy_structure":
                try:
                    if request.POST.get("confirm_reference") != "yes":
                        raise ValidationError(
                            "Konfirmasi pilihan laporan referensi wajib diberikan."
                        )
                    source, copied = initialize_monthly_report_structure_from_reference(
                        report, request.POST.get("reference_report")
                    )
                    analyze_import_batch(batch)
                except ValidationError as exc:
                    self.message_user(
                        request, "; ".join(exc.messages), level=messages.ERROR
                    )
                else:
                    self.message_user(
                        request,
                        f"{copied} struktur item disalin dari "
                        f"{source.periode.nama_periode}; analisis dijalankan ulang.",
                        level=messages.SUCCESS,
                    )
                return redirect(request.path)
            for row in rows:
                decision = request.POST.get(f"decision_{row.pk}", row.user_decision)
                if decision not in {row.DECISION_IMPORT, row.DECISION_SKIP}:
                    decision = row.DECISION_PENDING
                if row.validation_level == row.LEVEL_RED and decision == row.DECISION_IMPORT:
                    decision = row.DECISION_PENDING
                row.user_decision = decision
                row.user_note = request.POST.get(f"note_{row.pk}", "").strip()
                row.save(update_fields=["user_decision", "user_note", "updated_at"])
            if request.POST.get("action") == "apply":
                try:
                    apply_import_batch(batch, request.user)
                except ValidationError as exc:
                    self.message_user(request, "; ".join(exc.messages), level=messages.ERROR)
                else:
                    self.message_user(
                        request,
                        "Data terpilih berhasil diimpor dan ringkasan laporan diperbarui.",
                        level=messages.SUCCESS,
                    )
                    return redirect(
                        reverse(
                            f"{self.admin_site.name}:monthly_report_monthlyriskreport_change",
                            args=[report.pk],
                        )
                    )
            else:
                self.message_user(request, "Keputusan review berhasil disimpan.", level=messages.SUCCESS)
            return redirect(request.path)
        counts = {
            level: sum(row.validation_level == level for row in rows)
            for level in ("green", "yellow", "red")
        }
        for row in rows:
            row.display_changes = build_display_changes(row)
        reference_reports = list(structure_reference_reports(report))
        recommended_reference = (
            reference_reports[0] if reference_reports else None
        )
        for reference in reference_reports:
            reference.is_recommended = (
                recommended_reference is not None
                and reference.pk == recommended_reference.pk
            )
            reference.is_future = (
                reference.periode.tanggal_mulai > report.periode.tanggal_mulai
            )
        target_only_items = list(
            report.items.filter(
                pk__in=batch.analysis_summary.get("target_only_ids", [])
            ).select_related("risk_event")
        )
        unresolved = any(
            row.user_decision == row.DECISION_PENDING
            and row.validation_level in {row.LEVEL_YELLOW, row.LEVEL_RED}
            for row in rows
        )
        can_apply = bool(rows) and not batch.blocking_reason and not unresolved
        context = {
            **self.admin_site.each_context(request),
            "title": "Review Import Laporan Profil Risiko",
            "opts": self.model._meta,
            "report": report,
            "batch": batch,
            "rows": rows,
            "counts": counts,
            "summary": batch.analysis_summary,
            "reference_reports": reference_reports,
            "recommended_reference": recommended_reference,
            "target_only_items": target_only_items,
            "profile": report.reassessment,
            "profile_item_count": report.profile_items_queryset().count(),
            "profile_status": getattr(
                report.reassessment, "status", "Status tidak tersedia"
            ),
            "target_is_empty": not report.items.exists(),
            "can_apply": can_apply,
            "cancel_url": reverse(
                f"{self.admin_site.name}:monthly_report_monthlyriskreport_change", args=[report.pk]
            ),
        }
        return TemplateResponse(
            request,
            "admin/monthly_report/monthlyriskreport/import_profile_review.html",
            context,
        )

    @admin.display(description="Prepared by")
    def prepared_by_display(self, obj):
        if not obj or not obj.reassessment_id or not obj.reassessment.unit_bisnis_id:
            return "Otomatis mengikuti Risk Officer BID/Unit Bisnis setelah laporan disimpan."
        officers = _users_for_unit_role(
            obj.reassessment.unit_bisnis,
            PenugasanUnitBisnis.ROLE_RISK_OFFICER,
        )
        names = [officer.get_full_name().strip() or officer.get_username() for officer in officers]
        return ", ".join(names) if names else "Belum ada Risk Officer aktif pada BID/Unit Bisnis ini."

    def save_model(self, request, obj, form, change):
        if obj.reassessment_id:
            if not obj.prepared_by_id:
                obj.prepared_by = _users_for_unit_role(
                    obj.reassessment.unit_bisnis,
                    PenugasanUnitBisnis.ROLE_RISK_OFFICER,
                ).first()
            obj.reviewed_by = _users_for_unit_role(
                obj.reassessment.unit_bisnis,
                PenugasanUnitBisnis.ROLE_RISK_CHAMPION,
            ).first()
        super().save_model(request, obj, form, change)

    @admin.display(description="Reassessment", ordering="reassessment__judul")
    def profile_display(self, obj):
        name = obj.display_profile_name
        reassessment = getattr(obj, "reassessment", None)
        unit = getattr(reassessment, "unit_bisnis", None) if reassessment else None
        unit_name = (getattr(unit, "name", "") or "").strip().casefold()

        # Revision profile MANPRO tetap dipisahkan di database agar histori bulanan
        # aman, tetapi pada daftar laporan ditampilkan dengan nama canonical agar
        # pengguna tidak melihat suffix teknis "Mei-Juni 2026" / "Juli 2026".
        if unit_name == "bid manpro" and name.startswith("Profil Risiko MANPRO - "):
            copy_marker = " (copy bulan "
            copy_suffix = name[name.index(copy_marker):] if copy_marker in name else ""
            return f"Profil Risiko MANPRO{copy_suffix}"

        return name

    @admin.display(description="Sumber Salinan")
    def copy_source_display(self, obj):
        if not obj or not obj.copied_from_id:
            return "-"
        source_url = reverse(
            f"{self.admin_site.name}:monthly_report_monthlyriskreport_change",
            args=[obj.copied_from_id],
        )
        return format_html(
            '<a href="{}">{} - {}</a><br><span class="help">Disalin oleh {} pada {}</span>',
            source_url,
            obj.copied_from.reassessment,
            obj.copied_from.periode.nama_periode,
            obj.copied_by.get_full_name().strip() or obj.copied_by.get_username()
            if obj.copied_by_id
            else "-",
            timezone.localtime(obj.copied_at).strftime("%d-%m-%Y %H:%M")
            if obj.copied_at
            else "-",
        )

    @admin.display(description="Bulan Berikutnya")
    def duplicate_next_month_button(self, obj):
        if (
            not obj
            or obj.status != "approved"
            or not obj.periode_id
            or not obj.reassessment_id
        ):
            return "-"

        current_date = obj.periode.tanggal_mulai
        month_index = current_date.year * 12 + current_date.month
        next_year, zero_based_month = divmod(month_index, 12)
        next_month = zero_based_month + 1

        next_report = (
            self.model.objects.filter(
                reassessment_id=obj.reassessment_id,
                periode__tanggal_mulai__year=next_year,
                periode__tanggal_mulai__month=next_month,
            )
            .order_by("-versi", "-pk")
            .first()
        )

        if next_report:
            url = reverse(
                f"{self.admin_site.name}:monthly_report_monthlyriskreport_change",
                args=[next_report.pk],
            )
            return format_html('<a href="{}">Sudah dibuat</a>', url)

        url = reverse(
            f"{self.admin_site.name}:monthly_report_monthlyriskreport_duplicate_next_month",
            args=[obj.pk],
        )
        return format_html('<a class="button" href="{}">Buat Laporan Bulan Berikutnya</a>', url)

    def duplicate_next_month_view(self, request, object_id):
        source = self.get_object(request, object_id)
        if source is None:
            raise Http404("Monthly risk report tidak ditemukan.")
        if not self.has_add_permission(request):
            raise PermissionDenied("Anda tidak memiliki izin membuat laporan bulanan.")

        if request.method == "POST":
            try:
                target = duplicate_approved_report_to_next_month(source, request.user)
            except ValidationError as exc:
                message = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
                self.message_user(request, message, level=messages.ERROR)
                return redirect(
                    reverse(
                        f"{self.admin_site.name}:monthly_report_monthlyriskreport_changelist"
                    )
                )
            self.message_user(
                request,
                f"{target.display_profile_name} - {target.periode.nama_periode} berhasil dibuat sebagai Draft.",
                level=messages.SUCCESS,
            )
            return redirect(
                reverse(
                    f"{self.admin_site.name}:monthly_report_monthlyriskreport_change",
                    args=[target.pk],
                )
            )

        context = {
            **self.admin_site.each_context(request),
            "title": "Buat Laporan Bulan Berikutnya",
            "opts": self.model._meta,
            "source": source,
            "cancel_url": reverse(
                f"{self.admin_site.name}:monthly_report_monthlyriskreport_change",
                args=[source.pk],
            ),
        }
        return TemplateResponse(
            request,
            "admin/monthly_report/monthlyriskreport/confirm_duplicate.html",
            context,
        )

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
        primary_button = format_html('<a class="button" href="{}">{}</a>', url, label)
        if obj.status not in {"submitted", "under_review"}:
            return primary_button
        revise_url = reverse(
            f"{self.admin_site.name}:monthly_report_monthlyriskreport_flow_action",
            args=[obj.pk, "revise"],
        )
        return format_html(
            '{} <a class="button" style="margin-left:6px;background:#b45309" '
            'href="{}">Kembalikan ke Drafter</a>',
            primary_button,
            revise_url,
        )

    @admin.display(description="Komentar Koreksi Terakhir")
    def latest_revision_comment(self, obj):
        if not obj or not obj.pk:
            return "-"
        revision = (
            obj.submission_logs.filter(action="revise")
            .select_related("action_by")
            .order_by("-action_at", "-pk")
            .first()
        )
        if revision is None:
            return "-"
        actor = (
            revision.action_by.get_full_name().strip()
            or revision.action_by.get_username()
        )
        action_time = timezone.localtime(revision.action_at).strftime("%d-%m-%Y %H:%M")
        return format_html(
            '<div style="border-left:4px solid #b45309;padding:8px 12px;'
            'background:#fff7ed;white-space:pre-line"><strong>{}</strong> — {}<br>{}</div>',
            actor,
            action_time,
            revision.note or "-",
        )

    @admin.display(description="Notifikasi")
    def notification_button(self, obj):
        if not obj or not obj.pk:
            return "-"
        if obj.status not in {"draft", "revision", "submitted", "under_review", "approved"}:
            return "-"
        url = reverse(
            f"{self.admin_site.name}:monthly_report_monthlyriskreport_send_notification",
            args=[obj.pk],
        )
        return format_html(
            '<a class="button" href="{}">Konfigurasi Notifikasi</a>',
            url,
        )

    @admin.display(description="Petunjuk Lampiran")
    def petunjuk_lampiran(self, obj):
        return mark_safe(
            "<ul style='margin:0; padding-left:18px;'>"
            "<li><strong>III.A & III.B</strong>: ada di bagian "
            "<a href='#items-group'>III.A &amp; III.B – Pemantauan Risiko Bulanan</a>.</li>"
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
        report_quarter = (
            ((report.periode.tanggal_mulai.month - 1) // 3) + 1
            if report.periode_id
            else 1
        )
        inherent_dampak_field = f"skala_dampak_q{report_quarter}"
        inherent_probabilitas_field = f"skala_probabilitas_q{report_quarter}"
        for item in report.items.select_related(
            "risk_event",
            f"risk_event__{inherent_dampak_field}",
            f"risk_event__{inherent_probabilitas_field}",
            "realisasi_skala_dampak",
            "realisasi_skala_probabilitas",
        ):
            risk_number = str(item.risk_event.no_risiko)
            inherent_dampak_id = getattr(
                item.risk_event, f"{inherent_dampak_field}_id"
            )
            inherent_probabilitas_id = getattr(
                item.risk_event, f"{inherent_probabilitas_field}_id"
            )
            if inherent_dampak_id and inherent_probabilitas_id:
                inherent_points.setdefault(
                    (inherent_dampak_id, inherent_probabilitas_id),
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
                        "text_color": (
                            "#ffffff"
                            if cell and cell.level_risiko_id and cell.level_risiko.kode == "HIGH"
                            else "#000000"
                        ),
                        "inherent_points": inherent_points.get(key, []),
                        "residual_points": residual_points.get(key, []),
                    }
                )
            rows.append(
                {
                    "probabilitas": prob,
                    "probabilitas_kode": chr(64 + prob.urutan) if 1 <= prob.urutan <= 5 else "",
                    "cells": row,
                }
            )

        kpmr_calculation = None
        kpmr_month = report.periode.tanggal_mulai.month if report.periode_id else None
        kpmr_quarter = month_to_quarter(kpmr_month) if kpmr_month else None
        normalized_status = (report.status or "").strip().lower()
        show_kpmr = bool(
            report.reassessment_id
            and report.reassessment.unit_bisnis_id
            and kpmr_quarter
        )
        if show_kpmr:
            kpmr_calculation = calculate_kpmr_for_report(report)

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "report": report,
            "matrix": matrix,
            "dampak_scales": dampak_scales,
            "rows": rows,
            "show_kpmr": show_kpmr,
            "kpmr_is_preview": normalized_status == "draft",
            "kpmr_calculation": kpmr_calculation,
            "kpmr_diagnostics": (
                kpmr_calculation.diagnostics if kpmr_calculation else None
            ),
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

    @admin.display(description="Excel")
    def excel_button(self, obj):
        if not obj or not obj.pk or obj.status != "approved":
            return "-"
        url = reverse(
            f"{self.admin_site.name}:monthly_report_monthlyriskreport_excel",
            args=[obj.pk],
        )
        return format_html('<a class="button" href="{}">Download XLSX</a>', url)

    def excel_report_view(self, request, object_id):
        report = self.get_object(request, object_id)
        if report is None:
            raise Http404("Monthly risk report tidak ditemukan.")
        if not self.has_view_permission(request, report):
            raise PermissionDenied("Anda tidak memiliki izin melihat laporan ini.")
        if report.status != "approved":
            raise PermissionDenied("Laporan Excel hanya dapat diunduh setelah berstatus Approved.")

        output, filename = build_monthly_risk_report_excel(report)
        response = HttpResponse(output.getvalue(), content_type=XLSX_CONTENT_TYPE)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["X-Content-Type-Options"] = "nosniff"
        return response

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
                    "risk_type": (
                        risk.get_jenis_risiko_display()
                        if getattr(risk, "jenis_risiko", None)
                        else "-"
                    ),
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
                    "pic": item.realisasi_pic or risk.pic_display,
                    "status": item.get_status_rencana_perlakuan_display() or "",
                    "status_explanation": item.penjelasan_status_rencana or "",
                    "progress": _percent(item.progress_pelaksanaan_percent),
                    "progress_class": _monthly_progress_class(item.progress_pelaksanaan_percent),
                    "kri": item.realisasi_threshold_kri,
                    "planned_timeline": [
                        _monthly_timeline_mark(getattr(risk, f"timeline_{month}", 0))
                        for month in range(1, 13)
                    ],
                    "timeline": [
                        _monthly_timeline_mark(getattr(item, f"realisasi_timeline_{month}", 0))
                        for month in range(1, 13)
                    ],
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

    def _send_next_notification(
        self,
        request,
        report,
        correction_note="",
        approved_transition=False,
    ):
        try:
            sent = send_monthly_report_notification(
                report,
                request=request,
                correction_note=correction_note,
                approved_transition=approved_transition,
                delivery_mode="final",
            )
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

    def _apply_flow_action(self, report, flow_action, user, note=""):
        valid_actions = {
            "submit": {"draft", "revision"},
            "review": {"submitted"},
            "approve": {"under_review"},
            "revise": {"submitted", "under_review"},
        }
        if flow_action not in valid_actions:
            raise ValidationError("Aksi flow tidak dikenal.")
        if report.status not in valid_actions[flow_action]:
            raise ValidationError(
                f"Aksi tidak sesuai. Status laporan saat ini: {report.get_status_display()}."
            )

        update_fields = ["status", "updated_at"]
        action_note = ""
        if flow_action == "submit":
            if not report.evidence_url:
                raise ValidationError(
                    "Laporan wajib memiliki minimal satu Link Eviden sebelum disubmit."
                )
            validate_https_evidence_url(report.evidence_url)
            risk_officers = _users_for_unit_role(
                report.reassessment.unit_bisnis,
                PenugasanUnitBisnis.ROLE_RISK_OFFICER,
            )
            if not risk_officers.exists():
                raise ValidationError("Belum ada Risk Officer aktif pada BID/Unit Bisnis laporan.")
            if not user.is_superuser and not risk_officers.filter(pk=user.pk).exists():
                raise ValidationError("Hanya Prepared by/Risk Officer unit yang dapat submit laporan.")
            report.status = "submitted"
            report.submitted_at = timezone.now()
            update_fields.append("submitted_at")
            action_note = "Submitted oleh Prepared by/Risk Office."
        elif flow_action == "review":
            if not report.reviewed_by_id:
                raise ValidationError("Reviewed by belum diisi.")
            if not user.is_superuser and user.pk != report.reviewed_by_id:
                raise ValidationError("Hanya user Reviewed by yang dapat melakukan review dan paraf.")
            report.status = "under_review"
            action_note = "Review dan paraf oleh Reviewed by."
        elif flow_action == "approve":
            if not report.approved_by_id:
                raise ValidationError("Approved by belum diisi.")
            if not user.is_superuser and user.pk != report.approved_by_id:
                raise ValidationError("Hanya user Approved by yang dapat menyetujui laporan.")
            report.status = "approved"
            report.approved_at = timezone.now()
            update_fields.append("approved_at")
            action_note = "Approved oleh Approved by."
        elif flow_action == "revise":
            correction_note = (note or "").strip()
            if not correction_note:
                raise ValidationError("Komentar koreksi wajib diisi.")
            if report.status == "submitted":
                if not report.reviewed_by_id:
                    raise ValidationError("Reviewed by belum diisi.")
                if not user.is_superuser and user.pk != report.reviewed_by_id:
                    raise ValidationError(
                        "Hanya user Reviewed by yang dapat mengembalikan laporan."
                    )
                actor_role = "Reviewed by"
            else:
                if not report.approved_by_id:
                    raise ValidationError("Approved by belum diisi.")
                if not user.is_superuser and user.pk != report.approved_by_id:
                    raise ValidationError(
                        "Hanya user Approved by yang dapat mengembalikan laporan."
                    )
                actor_role = "Approved by"
            report.status = "revision"
            report.approved_at = None
            update_fields.append("approved_at")
            action_note = f"Dikembalikan oleh {actor_role}. Koreksi: {correction_note}"

        report.save(update_fields=update_fields)
        MonthlyRiskReportSubmissionLog.objects.create(
            report=report,
            action=flow_action,
            action_by=user,
            note=action_note,
        )
        return report

    def flow_action_view(self, request, object_id, flow_action):
        report = self.get_object(request, object_id)
        if report is None:
            raise Http404("Monthly risk report tidak ditemukan.")
        if flow_action == "revise" and request.method != "POST":
            context = {
                **self.admin_site.each_context(request),
                "title": "Kembalikan Laporan ke Drafter",
                "opts": self.model._meta,
                "report": report,
                "cancel_url": reverse(
                    f"{self.admin_site.name}:monthly_report_monthlyriskreport_change",
                    args=[report.pk],
                ),
            }
            return TemplateResponse(
                request,
                "admin/monthly_report/monthlyriskreport/confirm_revision.html",
                context,
            )
        correction_note = request.POST.get("correction_note", "") if flow_action == "revise" else ""
        try:
            self._apply_flow_action(
                report,
                flow_action,
                request.user,
                note=correction_note,
            )
        except ValidationError as exc:
            message = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            self.message_user(request, message, level=messages.ERROR)
            if flow_action == "revise":
                return redirect(request.path)
        else:
            self.message_user(
                request,
                f"Flow laporan berhasil diproses. Status sekarang: {report.get_status_display()}.",
                level=messages.SUCCESS,
            )
            self._send_next_notification(
                request,
                report,
                correction_note=correction_note,
                approved_transition=flow_action == "approve",
            )
        return HttpResponseRedirect(
            reverse(
                f"{self.admin_site.name}:monthly_report_monthlyriskreport_change",
                args=[report.pk],
            )
        )

    def send_notification_view(self, request, object_id):
        if not self._can_manage_notifications(request):
            raise PermissionDenied(
                "Hanya Admin ERM yang dapat mengonfigurasi dan mengirim "
                "notifikasi laporan risiko."
            )
        report = self.get_object(request, object_id)
        if report is None:
            raise Http404("Monthly risk report tidak ditemukan.")

        stage = monthly_report_notification_stage(report)
        if not stage:
            raise PermissionDenied(
                "Status laporan ini tidak memerlukan notifikasi tahap berikutnya."
            )

        recipient_error = ""
        try:
            final_delivery = resolve_monthly_report_notification_recipients(
                report,
                stage=stage,
                delivery_mode="final",
            )
        except ValidationError as exc:
            recipient_error = (
                "; ".join(exc.messages)
                if hasattr(exc, "messages")
                else str(exc)
            )
            final_delivery = {
                "recipients": [],
                "cc_recipients": [],
                "bcc_recipients": [],
            }

        initial = {
            "subject": (
                f"{stage['title']} - {report.reassessment} "
                f"{report.periode.nama_periode}"
            ),
            "instruction": stage["instruction"],
            "test_email": request.user.email or "",
        }
        form = MonthlyRiskReportNotificationForm(
            request.POST or None,
            initial=initial,
        )

        if request.method == "POST" and form.is_valid():
            action = request.POST.get("action")
            subject = form.cleaned_data["subject"].strip()
            instruction = form.cleaned_data["instruction"].strip()
            approved_transition = report.status == "approved"

            try:
                if action == "test":
                    test_email = (
                        form.cleaned_data.get("test_email") or ""
                    ).strip()
                    if not test_email:
                        raise ValidationError(
                            "Email tujuan uji coba wajib diisi."
                        )
                    sent = send_monthly_report_notification(
                        report,
                        request=request,
                        approved_transition=approved_transition,
                        delivery_mode="test",
                        test_email_override=test_email,
                        subject_override=subject,
                        instruction_override=instruction,
                    )
                    if sent:
                        self.message_user(
                            request,
                            f"Email uji coba berhasil dikirim ke {test_email}.",
                            level=messages.SUCCESS,
                        )
                    return redirect(request.path)

                if action == "send_final":
                    if not form.cleaned_data.get("confirm_final"):
                        raise ValidationError(
                            "Centang konfirmasi pemeriksaan sebelum mengirim "
                            "notifikasi final."
                        )
                    sent = send_monthly_report_notification(
                        report,
                        request=request,
                        approved_transition=approved_transition,
                        delivery_mode="final",
                        subject_override=subject,
                        instruction_override=instruction,
                    )
                    if sent:
                        self.message_user(
                            request,
                            "Notifikasi final berhasil dikirim.",
                            level=messages.SUCCESS,
                        )
                    return HttpResponseRedirect(
                        reverse(
                            f"{self.admin_site.name}:"
                            "monthly_report_monthlyriskreport_change",
                            args=[report.pk],
                        )
                    )

                raise ValidationError("Aksi notifikasi tidak dikenal.")
            except ValidationError as exc:
                message = (
                    "; ".join(exc.messages)
                    if hasattr(exc, "messages")
                    else str(exc)
                )
                self.message_user(request, message, level=messages.ERROR)

        context = {
            **self.admin_site.each_context(request),
            "title": "Konfigurasi Notifikasi Laporan Risiko Bulanan",
            "opts": self.model._meta,
            "report": report,
            "stage": stage,
            "form": form,
            "to_emails": final_delivery["recipients"],
            "cc_emails": final_delivery["cc_recipients"],
            "bcc_emails": final_delivery["bcc_recipients"],
            "recipient_error": recipient_error,
            "cancel_url": reverse(
                f"{self.admin_site.name}:"
                "monthly_report_monthlyriskreport_change",
                args=[report.pk],
            ),
        }
        return TemplateResponse(
            request,
            "admin/monthly_report/monthlyriskreport/"
            "notification_config.html",
            context,
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
                    summary_id=reassessment_id,
                    is_active=True,
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
            super().get_queryset(request).select_related(
                "copied_from__periode",
                "copied_from__reassessment",
                "copied_by",
            ).prefetch_related("copied_reports"),
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
