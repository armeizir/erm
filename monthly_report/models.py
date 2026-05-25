from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from decimal import Decimal

from core.models import TimeStampedModel
from km.models import KontrakManajemen, KontrakManajemenItem
from masterdata.models import (
    PeriodeLaporan,
    SkalaDampak,
    SkalaProbabilitas,
    TahunBuku,
    UnitOrganisasi,
)
from risk.models import (
    MasterSkalaDampak as RiskSkalaDampak,
    MasterSkalaProbabilitas as RiskSkalaProbabilitas,
    ReAssessmentItem,
    ReAssessmentSummary,
    RiskMatrix,
)


class MonthlyRiskReport(TimeStampedModel):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("under_review", "Under Review"),
        ("revision", "Revision"),
        ("approved", "Approved"),
        ("locked", "Locked"),
    ]

    kode = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        null=True,
    )
    # judul = models.CharField(max_length=255)
    tahun_buku = models.ForeignKey(TahunBuku, on_delete=models.PROTECT)
    periode = models.ForeignKey(PeriodeLaporan, on_delete=models.PROTECT)
    unit = models.ForeignKey(
        UnitOrganisasi,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    kontrak_manajemen = models.ForeignKey(
        KontrakManajemen,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    reassessment = models.ForeignKey(
        ReAssessmentSummary, on_delete=models.PROTECT, related_name="monthly_reports"
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

    is_locked = models.BooleanField(default=False)

    class Meta:
        db_table = "mr_monthly_risk_report"
        unique_together = [("tahun_buku", "periode", "unit", "versi")]
        ordering = ["-tahun_buku__tahun", "periode__tanggal_mulai", "unit__kode", "-versi"]

    def __str__(self):
        return f"{self.reassessment} - {self.periode.nama_periode}"

    def clean(self):
        errors = {}
        if self.periode_id and self.tahun_buku_id and self.periode.tahun_buku_id != self.tahun_buku_id:
            errors["periode"] = "Periode harus berada pada tahun buku yang sama."
        if self.reassessment_id:
            if self.tahun_buku_id and self.reassessment.tahun != self.tahun_buku.tahun:
                errors["tahun_buku"] = "Tahun buku laporan harus sama dengan tahun buku reassessment."
        if self.kontrak_manajemen_id:
            if self.unit_id and self.kontrak_manajemen.unit_id != self.unit_id:
                errors["kontrak_manajemen"] = "KM harus milik unit yang sama dengan laporan."
            if self.tahun_buku_id and self.kontrak_manajemen.tahun_buku_id != self.tahun_buku_id:
                errors["kontrak_manajemen"] = "KM harus berada pada tahun buku yang sama."
        if errors:
            raise ValidationError(errors)

    def generate_items(self):

        risk_events = ReAssessmentItem.objects.filter(summary=self.reassessment)

        for risk_event in risk_events:
            MonthlyRiskReportItem.objects.get_or_create(
                report=self,
                risk_event=risk_event,
            )


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

    EFFECTIVENESS_CHOICES = [
        ("efektif", "Efektif"),
        ("cukup_efektif", "Cukup Efektif"),
        ("tidak_efektif", "Tidak Efektif"),
    ]
    TREATMENT_STATUS_CHOICES = [
        ("continue", "Continue"),
        ("discontinue", "Discontinue"),
    ]

    report = models.ForeignKey(
        MonthlyRiskReport, on_delete=models.CASCADE, related_name="items"
    )
    risk_event = models.ForeignKey(
        ReAssessmentItem,
        on_delete=models.PROTECT,
        related_name="monthly_report_items",
        verbose_name="Item Risiko Unit/Bidang",
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

    realisasi_asumsi_dampak = models.TextField(
        null=True,
        blank=True,
        verbose_name="Asumsi Perhitungan Dampak Realisasi",
    )
    realisasi_nilai_dampak = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Nilai Dampak Bulan Ini",
    )
    realisasi_skala_dampak = models.ForeignKey(
        RiskSkalaDampak,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="monthly_report_realisasi_dampak",
        verbose_name="Skala Dampak Bulan Ini",
    )
    realisasi_nilai_probabilitas = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Nilai Probabilitas Bulan Ini (%)",
    )
    realisasi_skala_probabilitas = models.ForeignKey(
        RiskSkalaProbabilitas,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="monthly_report_realisasi_probabilitas",
        verbose_name="Skala Probabilitas Bulan Ini",
    )
    realisasi_eksposur = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Eksposur Risiko Bulan Ini",
    )
    realisasi_skor_risiko = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="Skala Nilai Risiko Bulan Ini",
    )
    realisasi_level_risiko = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Level Risiko Bulan Ini",
    )
    efektivitas_perlakuan_risiko = models.CharField(
        max_length=100,
        choices=EFFECTIVENESS_CHOICES,
        null=True,
        blank=True,
        verbose_name="Efektivitas Perlakuan Risiko",
    )
    realisasi_rencana_perlakuan = models.TextField(
        null=True,
        blank=True,
        verbose_name="Realisasi Rencana Perlakuan Risiko",
    )
    realisasi_output_perlakuan = models.TextField(
        null=True,
        blank=True,
        verbose_name="Realisasi Output Perlakuan Risiko",
    )
    realisasi_biaya_perlakuan = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Realisasi Biaya Perlakuan Risiko",
    )
    persentase_serapan_biaya = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Persentase Serapan Biaya",
    )
    realisasi_pic = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Realisasi PIC",
    )
    status_rencana_perlakuan = models.CharField(
        max_length=30,
        choices=TREATMENT_STATUS_CHOICES,
        null=True,
        blank=True,
        verbose_name="Status Rencana Perlakuan Risiko",
    )
    penjelasan_status_rencana = models.TextField(
        null=True,
        blank=True,
        verbose_name="Penjelasan Status Rencana Perlakuan",
    )
    progress_pelaksanaan_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Progress Pelaksanaan Bulan Ini (%)",
    )
    realisasi_threshold_kri = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Realisasi Threshold KRI Bulan Ini",
    )
    realisasi_threshold_kri_skor = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Skor Threshold KRI Bulan Ini",
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
            if self.risk_event.summary_id != self.report.reassessment_id:
                errors["risk_event"] = "Item risiko harus berasal dari profil risiko yang sama dengan report."
        if self.km_item_id and self.report_id:
            if self.km_item.bagian.kontrak_id != self.report.kontrak_manajemen_id:
                errors["km_item"] = "KM item harus berasal dari Kontrak Manajemen pada report ini."
        if self.residual_level and self.target_residual_level:
            if self.residual_level > self.target_residual_level and not self.escalation_note:
                errors["escalation_note"] = (
                    "Wajib isi catatan eskalasi jika residual masih di atas target residual."
                )
        if self.realisasi_nilai_probabilitas is not None:
            if self.realisasi_nilai_probabilitas < 0 or self.realisasi_nilai_probabilitas > 100:
                errors["realisasi_nilai_probabilitas"] = (
                    "Nilai probabilitas harus berada di antara 0 sampai 100."
                )
        if self.persentase_serapan_biaya is not None:
            if self.persentase_serapan_biaya < 0 or self.persentase_serapan_biaya > 100:
                errors["persentase_serapan_biaya"] = (
                    "Persentase serapan biaya harus berada di antara 0 sampai 100."
                )
        if self.progress_pelaksanaan_percent is not None:
            if self.progress_pelaksanaan_percent < 0 or self.progress_pelaksanaan_percent > 100:
                errors["progress_pelaksanaan_percent"] = (
                    "Progress pelaksanaan harus berada di antara 0 sampai 100."
                )
        if errors:
            raise ValidationError(errors)

    @property
    def quarter(self):
        if not self.report_id or not self.report.periode_id:
            return None
        return ((self.report.periode.tanggal_mulai.month - 1) // 3) + 1

    def _get_active_matrix(self):
        if self.risk_event_id and self.risk_event.summary.risk_matrix_id:
            return self.risk_event.summary.risk_matrix
        return RiskMatrix.objects.filter(aktif=True, is_default=True).first()

    def _calculate_realisasi(self):
        if self.realisasi_nilai_dampak is not None and self.realisasi_nilai_probabilitas is not None:
            self.realisasi_eksposur = (
                self.realisasi_nilai_dampak
                * (self.realisasi_nilai_probabilitas / Decimal("100"))
            ).quantize(Decimal("0.01"))
        else:
            self.realisasi_eksposur = None

        self.realisasi_skor_risiko = None
        self.realisasi_level_risiko = None
        if self.realisasi_skala_dampak_id and self.realisasi_skala_probabilitas_id:
            matrix = self._get_active_matrix()
            cell = (
                matrix.get_cell(self.realisasi_skala_dampak, self.realisasi_skala_probabilitas)
                if matrix
                else None
            )
            if cell:
                self.realisasi_skor_risiko = cell.skor
                self.realisasi_level_risiko = cell.level_risiko.nama

    def save(self, *args, **kwargs):
        self._calculate_realisasi()
        super().save(*args, **kwargs)


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


class MonthlyRiskReportChange(TimeStampedModel):
    CHANGE_TYPE_PROFILE = "perubahan_profil"
    CHANGE_TYPE_ADD_ITEM = "penambahan_item"
    CHANGE_TYPE_REMOVE_ITEM = "pengurangan_item"
    CHANGE_TYPE_STRATEGY = "perubahan_strategi"

    CHANGE_TYPE_CHOICES = [
        (CHANGE_TYPE_PROFILE, "Perubahan profil risiko"),
        (CHANGE_TYPE_ADD_ITEM, "Penambahan item risiko"),
        (CHANGE_TYPE_REMOVE_ITEM, "Pengurangan item risiko"),
        (CHANGE_TYPE_STRATEGY, "Perubahan strategi risiko"),
    ]

    report = models.ForeignKey(
        MonthlyRiskReport,
        on_delete=models.CASCADE,
        related_name="changes",
    )
    jenis_perubahan = models.CharField(
        max_length=30,
        choices=CHANGE_TYPE_CHOICES,
        verbose_name="Jenis Perubahan",
    )
    peristiwa_risiko_terdampak = models.TextField(
        null=True,
        blank=True,
        verbose_name="Peristiwa Risiko yang Terdampak atas Perubahan",
    )
    penjelasan = models.TextField(
        null=True,
        blank=True,
        verbose_name="Penjelasan",
    )

    class Meta:
        db_table = "mr_monthly_risk_report_change"
        verbose_name = "Ikhtisar Perubahan Profil dan Strategi Risiko"
        verbose_name_plural = "III.D - Ikhtisar Perubahan Profil dan Strategi Risiko"
        ordering = ["id"]

    def __str__(self):
        return self.get_jenis_perubahan_display()


class MonthlyRiskReportLossEvent(TimeStampedModel):
    SOURCE_INTERNAL = "internal"
    SOURCE_EXTERNAL = "external"

    SOURCE_CHOICES = [
        (SOURCE_INTERNAL, "Internal"),
        (SOURCE_EXTERNAL, "Eksternal"),
    ]

    YES_NO_CHOICES = [
        ("ya", "Ya"),
        ("tidak", "Tidak"),
    ]

    report = models.ForeignKey(
        MonthlyRiskReport,
        on_delete=models.CASCADE,
        related_name="loss_events",
    )
    nama_kejadian = models.TextField(verbose_name="Nama Kejadian")
    identifikasi_kejadian = models.TextField(
        null=True,
        blank=True,
        verbose_name="Identifikasi Kejadian",
    )
    kategori_kejadian = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Kategori Kejadian",
    )
    sumber_penyebab_kejadian = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        null=True,
        blank=True,
        verbose_name="Sumber Penyebab Kejadian",
    )
    penyebab_kejadian = models.TextField(
        null=True,
        blank=True,
        verbose_name="Penyebab Kejadian",
    )
    penanganan_saat_kejadian = models.TextField(
        null=True,
        blank=True,
        verbose_name="Penanganan Saat Kejadian",
    )
    deskripsi_kejadian_risk_event = models.TextField(
        null=True,
        blank=True,
        verbose_name="Deskripsi Kejadian - Risk Event",
    )
    kategori_risiko_bumn = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Kategori Risiko BUMN",
    )
    kategori_risiko_t2_t3_kbumn = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Kategori Risiko T2 & T3 KBUMN",
    )
    penjelasan_kerugian = models.TextField(
        null=True,
        blank=True,
        verbose_name="Penjelasan Kerugian",
    )
    nilai_kerugian = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Nilai Kerugian",
    )
    kejadian_berulang = models.CharField(
        max_length=10,
        choices=YES_NO_CHOICES,
        null=True,
        blank=True,
        verbose_name="Kejadian Berulang",
    )
    frekuensi_kejadian = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Frekuensi Kejadian",
    )
    mitigasi_direncanakan = models.TextField(
        null=True,
        blank=True,
        verbose_name="Mitigasi yang Direncanakan",
    )
    realisasi_mitigasi = models.TextField(
        null=True,
        blank=True,
        verbose_name="Realisasi Mitigasi",
    )
    perbaikan_mendatang = models.TextField(
        null=True,
        blank=True,
        verbose_name="Perbaikan Mendatang",
    )
    pihak_terkait = models.TextField(
        null=True,
        blank=True,
        verbose_name="Pihak Terkait",
    )
    status_asuransi = models.CharField(
        max_length=10,
        choices=YES_NO_CHOICES,
        null=True,
        blank=True,
        verbose_name="Status Asuransi",
    )
    nilai_premi = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Nilai Premi",
    )
    nilai_klaim = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Nilai Klaim",
    )

    class Meta:
        db_table = "mr_monthly_risk_report_loss_event"
        verbose_name = "Catatan Kejadian Kerugian"
        verbose_name_plural = "III.E - Catatan Kejadian Kerugian (Loss Event Database)"
        ordering = ["id"]

    def __str__(self):
        return self.nama_kejadian[:80]


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
