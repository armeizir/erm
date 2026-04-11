from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.models import TimeStampedModel
from km.models import KontrakManajemen, KontrakManajemenItem
from masterdata.models import (
    PeriodeLaporan,
    SkalaDampak,
    SkalaProbabilitas,
    TahunBuku,
    UnitOrganisasi,
)
from reassessment.models import ReAssessment, RiskEvent


class MonthlyRiskReport(TimeStampedModel):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("under_review", "Under Review"),
        ("revision", "Revision"),
        ("approved", "Approved"),
        ("locked", "Locked"),
    ]

    kode = models.CharField(max_length=50, unique=True)
    judul = models.CharField(max_length=255)
    tahun_buku = models.ForeignKey(TahunBuku, on_delete=models.PROTECT)
    periode = models.ForeignKey(PeriodeLaporan, on_delete=models.PROTECT)
    unit = models.ForeignKey(UnitOrganisasi, on_delete=models.PROTECT)
    kontrak_manajemen = models.ForeignKey(KontrakManajemen, on_delete=models.PROTECT)
    reassessment = models.ForeignKey(
        ReAssessment, on_delete=models.PROTECT, related_name="monthly_reports"
    )
    versi = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="draft")

    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="monthly_report_prepared",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="monthly_report_reviewed",
        null=True,
        blank=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="monthly_report_approved",
        null=True,
        blank=True,
    )

    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    summary_km = models.TextField(null=True, blank=True)
    summary_rkm = models.TextField(null=True, blank=True)
    summary_risiko = models.TextField(null=True, blank=True)
    catatan_manajemen = models.TextField(null=True, blank=True)

    total_risiko = models.PositiveIntegerField(default=0)
    total_high = models.PositiveIntegerField(default=0)
    total_mitigasi_terlambat = models.PositiveIntegerField(default=0)
    total_selesai = models.PositiveIntegerField(default=0)

    is_aggregated_to_corporate = models.BooleanField(default=False)
    aggregated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mr_monthly_risk_report"
        unique_together = [("tahun_buku", "periode", "unit", "versi")]
        ordering = ["-tahun_buku__tahun", "periode__tanggal_mulai", "unit__kode", "-versi"]

    def __str__(self):
        return f"{self.kode} - {self.unit.nama} - {self.periode.nama_periode}"

    def clean(self):
        errors = {}
        if self.periode_id and self.tahun_buku_id and self.periode.tahun_buku_id != self.tahun_buku_id:
            errors["periode"] = "Periode harus berada pada tahun buku yang sama."
        if self.reassessment_id:
            if self.unit_id and self.reassessment.unit_id != self.unit_id:
                errors["unit"] = "Unit laporan harus sama dengan unit reassessment."
            if self.periode_id and self.reassessment.periode_id != self.periode_id:
                errors["periode"] = "Periode laporan harus sama dengan periode reassessment."
            if self.tahun_buku_id and self.reassessment.tahun_buku_id != self.tahun_buku_id:
                errors["tahun_buku"] = "Tahun buku laporan harus sama dengan tahun buku reassessment."
        if self.kontrak_manajemen_id:
            if self.unit_id and self.kontrak_manajemen.unit_id != self.unit_id:
                errors["kontrak_manajemen"] = "KM harus milik unit yang sama dengan laporan."
            if self.tahun_buku_id and self.kontrak_manajemen.tahun_buku_id != self.tahun_buku_id:
                errors["kontrak_manajemen"] = "KM harus berada pada tahun buku yang sama."
        if errors:
            raise ValidationError(errors)


class MonthlyRiskReportItem(TimeStampedModel):
    TREND_CHOICES = [
        ("up", "Meningkat"),
        ("down", "Menurun"),
        ("flat", "Tetap"),
    ]

    MITIGATION_STATUS_CHOICES = [
        ("not_started", "Not Started"),
        ("on_progress", "On Progress"),
        ("done", "Done"),
        ("delayed", "Delayed"),
    ]

    report = models.ForeignKey(
        MonthlyRiskReport, on_delete=models.CASCADE, related_name="items"
    )
    risk_event = models.ForeignKey(
        RiskEvent, on_delete=models.PROTECT, related_name="monthly_report_items"
    )
    km_item = models.ForeignKey(
        KontrakManajemenItem, on_delete=models.PROTECT, null=True, blank=True
    )

    inherent_skala_dampak = models.ForeignKey(
        SkalaDampak, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    inherent_skala_probabilitas = models.ForeignKey(
        SkalaProbabilitas, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    inherent_level = models.PositiveSmallIntegerField(null=True, blank=True)

    residual_skala_dampak = models.ForeignKey(
        SkalaDampak, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    residual_skala_probabilitas = models.ForeignKey(
        SkalaProbabilitas, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    residual_level = models.PositiveSmallIntegerField(null=True, blank=True)
    target_residual_level = models.PositiveSmallIntegerField(null=True, blank=True)

    mitigation_progress_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    mitigation_status = models.CharField(
        max_length=30, choices=MITIGATION_STATUS_CHOICES, null=True, blank=True
    )

    trend = models.CharField(max_length=10, choices=TREND_CHOICES, null=True, blank=True)
    issue_summary = models.TextField(null=True, blank=True)
    next_action = models.TextField(null=True, blank=True)
    escalation_note = models.TextField(null=True, blank=True)

    contributes_to_corporate = models.BooleanField(default=False)
    corporate_note = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "mr_monthly_risk_report_item"
        unique_together = [("report", "risk_event")]
        ordering = ["risk_event__no_item", "risk_event__no_risiko"]

    def __str__(self):
        return f"{self.report.kode} - {self.risk_event.no_risiko}"

    def clean(self):
        errors = {}
        if self.report_id and self.risk_event_id:
            if self.risk_event.reassessment_id != self.report.reassessment_id:
                errors["risk_event"] = "Risk event harus berasal dari reassessment yang sama dengan report."
        if self.km_item_id and self.report_id:
            if self.km_item.bagian.kontrak_id != self.report.kontrak_manajemen_id:
                errors["km_item"] = "KM item harus berasal dari Kontrak Manajemen pada report ini."
        if self.residual_level and self.target_residual_level:
            if self.residual_level > self.target_residual_level and not self.escalation_note:
                errors["escalation_note"] = (
                    "Wajib isi catatan eskalasi jika residual masih di atas target residual."
                )
        if errors:
            raise ValidationError(errors)


class MonthlyRiskReportKMAlignment(TimeStampedModel):
    ALIGNMENT_CHOICES = [
        ("aligned", "Aligned"),
        ("partial", "Partial"),
        ("not_aligned", "Not Aligned"),
    ]

    report_item = models.OneToOneField(
        MonthlyRiskReportItem,
        on_delete=models.CASCADE,
        related_name="km_alignment",
    )
    km_item = models.ForeignKey(
        KontrakManajemenItem, on_delete=models.PROTECT, null=True, blank=True
    )
    alignment_status = models.CharField(
        max_length=20,
        choices=ALIGNMENT_CHOICES,
        default="partial",
    )
    alignment_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    reason = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "mr_km_alignment"

    def clean(self):
        errors = {}
        if self.km_item_id and self.report_item_id:
            if self.km_item_id != self.report_item.km_item_id:
                errors["km_item"] = "KM alignment harus mengacu pada KM item yang sama dengan report item."
        if errors:
            raise ValidationError(errors)


class MonthlyRiskReportSubmissionLog(models.Model):
    ACTION_CHOICES = [
        ("submit", "Submit"),
        ("review", "Review"),
        ("revise", "Revise"),
        ("approve", "Approve"),
        ("lock", "Lock"),
    ]

    report = models.ForeignKey(
        MonthlyRiskReport,
        on_delete=models.CASCADE,
        related_name="submission_logs",
    )
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    action_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "mr_submission_log"
        ordering = ["-action_at"]
