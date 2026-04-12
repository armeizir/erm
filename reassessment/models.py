from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.models import TimeStampedModel
from masterdata.models import (
    TahunBuku,
    PeriodeLaporan,
    UnitOrganisasi,
    SasaranBUMN,
    TaksonomiT3,
    KategoriRisiko,
    KategoriDampak,
    SkalaDampak,
    SkalaProbabilitas,
)
from km.models import KontrakManajemen, KontrakManajemenItem


class ReAssessment(TimeStampedModel):
    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_REVIEW_RKM = "review_rkm"
    STATUS_REJECTED_RKM = "rejected_rkm"
    STATUS_APPROVED_RKM = "approved_rkm"
    STATUS_REVIEW_KM = "review_km"
    STATUS_REJECTED_KM = "rejected_km"
    STATUS_APPROVED_KM = "approved_km"
    STATUS_LOCKED = "locked"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_REVIEW_RKM, "Review RKM"),
        (STATUS_REJECTED_RKM, "Rejected RKM"),
        (STATUS_APPROVED_RKM, "Approved RKM"),
        (STATUS_REVIEW_KM, "Review KM"),
        (STATUS_REJECTED_KM, "Rejected KM"),
        (STATUS_APPROVED_KM, "Approved KM"),
        (STATUS_LOCKED, "Locked"),
    ]

    kode = models.CharField(max_length=50, unique=True)
    judul = models.CharField(max_length=255)
    tahun_buku = models.ForeignKey(TahunBuku, on_delete=models.PROTECT)
    periode = models.ForeignKey(PeriodeLaporan, on_delete=models.PROTECT)
    unit = models.ForeignKey(UnitOrganisasi, on_delete=models.PROTECT)
    kontrak_manajemen = models.ForeignKey(KontrakManajemen, on_delete=models.PROTECT)
    versi = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_DRAFT)

    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ra_prepared",
    )
    reviewed_by_rkm = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ra_reviewed_rkm",
        null=True,
        blank=True,
    )
    approved_by_rkm = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ra_approved_rkm",
        null=True,
        blank=True,
    )
    reviewed_by_km = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ra_reviewed_km",
        null=True,
        blank=True,
    )
    approved_by_km = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ra_approved_km",
        null=True,
        blank=True,
    )

    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_rkm_at = models.DateTimeField(null=True, blank=True)
    approved_rkm_at = models.DateTimeField(null=True, blank=True)
    reviewed_km_at = models.DateTimeField(null=True, blank=True)
    approved_km_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)

    catatan_unit = models.TextField(null=True, blank=True)
    catatan_rkm = models.TextField(null=True, blank=True)
    catatan_km = models.TextField(null=True, blank=True)

    is_escalated = models.BooleanField(default=False)

    class Meta:
        db_table = "ra_reassessment"
        unique_together = [("tahun_buku", "periode", "unit", "versi")]

    def __str__(self):
        return f"{self.kode} - {self.judul}"

    @property
    def is_editable_by_unit(self):
        return self.status in {
            self.STATUS_DRAFT,
            self.STATUS_REJECTED_RKM,
            self.STATUS_REJECTED_KM,
        }

    @property
    def is_valid_for_analytics(self):
        return self.status in {
            self.STATUS_APPROVED_KM,
            self.STATUS_LOCKED,
        }

    def can_review_rkm(self):
        return self.status in {self.STATUS_SUBMITTED, self.STATUS_REVIEW_RKM}

    def can_review_km(self):
        return self.status in {self.STATUS_APPROVED_RKM, self.STATUS_REVIEW_KM}

    def can_lock(self):
        return self.status == self.STATUS_APPROVED_KM

    def clean(self):
        if self.kontrak_manajemen_id and self.unit_id:
            if self.kontrak_manajemen.unit_id != self.unit_id:
                raise ValidationError(
                    "Unit ReAssessment harus sama dengan unit pada Kontrak Manajemen."
                )

        if self.kontrak_manajemen_id and self.tahun_buku_id:
            if self.kontrak_manajemen.tahun_buku_id != self.tahun_buku_id:
                raise ValidationError(
                    "Tahun buku ReAssessment harus sama dengan tahun buku Kontrak Manajemen."
                )


class RiskEvent(TimeStampedModel):
    STATUS_CHOICES = [
        ("aktif", "Aktif"),
        ("monitoring", "Monitoring"),
        ("closed", "Closed"),
    ]

    CONFIDENCE_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ]

    reassessment = models.ForeignKey(
        ReAssessment,
        on_delete=models.CASCADE,
        related_name="risk_events",
    )
    no_item = models.CharField(max_length=30)
    no_risiko = models.CharField(max_length=30)

    sasaran_bumn = models.ForeignKey(
        SasaranBUMN,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    km_item = models.ForeignKey(
        KontrakManajemenItem,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="risk_events",
    )
    taksonomi_t3 = models.ForeignKey(
        TaksonomiT3,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    kategori_risiko = models.ForeignKey(
        KategoriRisiko,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    kategori_dampak = models.ForeignKey(
        KategoriDampak,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    peristiwa_risiko = models.TextField()
    deskripsi_peristiwa = models.TextField(null=True, blank=True)
    deskripsi_dampak = models.TextField(null=True, blank=True)
    waktu_terpapar = models.CharField(max_length=100, null=True, blank=True)

    risk_owner = models.ForeignKey(
        UnitOrganisasi,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="owned_risks",
    )

    status_risiko = models.CharField(max_length=30, choices=STATUS_CHOICES, default="aktif")
    prioritas = models.PositiveIntegerField(null=True, blank=True)

    confidence_level = models.CharField(
        max_length=10,
        choices=CONFIDENCE_CHOICES,
        default="medium",
    )
    is_key_risk = models.BooleanField(default=False)
    escalate_to_km = models.BooleanField(default=False)
    catatan_validasi = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "ra_risk_event"
        unique_together = [("reassessment", "no_risiko")]
        ordering = ["reassessment", "no_item"]

    def __str__(self):
        return f"{self.no_risiko} - {self.peristiwa_risiko[:80]}"

    def clean(self):
        if self.km_item_id and self.reassessment_id:
            km_kontrak_id = self.reassessment.kontrak_manajemen_id
            if self.km_item.bagian.kontrak_id != km_kontrak_id:
                raise ValidationError(
                    "KM Item harus berasal dari Kontrak Manajemen yang sama."
                )

        if self.risk_owner_id and self.reassessment_id:
            if self.risk_owner_id != self.reassessment.unit_id:
                raise ValidationError(
                    "Risk owner harus sama dengan unit ReAssessment."
                )


class RiskCause(models.Model):
    risk_event = models.ForeignKey(
        RiskEvent,
        on_delete=models.CASCADE,
        related_name="causes",
    )
    kode_penyebab = models.CharField(max_length=30, null=True, blank=True)
    no_penyebab = models.CharField(max_length=30, null=True, blank=True)
    deskripsi_penyebab = models.TextField()
    urutan = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "ra_risk_cause"
        ordering = ["risk_event", "urutan"]

    def __str__(self):
        return f"{self.risk_event.no_risiko} - Penyebab {self.urutan}"


class RiskIndicator(models.Model):
    ARAH_CHOICES = [
        ("higher_better", "Higher Better"),
        ("lower_better", "Lower Better"),
        ("range", "Range"),
    ]

    risk_event = models.ForeignKey(
        RiskEvent,
        on_delete=models.CASCADE,
        related_name="indicators",
    )
    risk_cause = models.ForeignKey(
        RiskCause,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="indicators",
    )
    nama_kri = models.CharField(max_length=255)
    satuan = models.CharField(max_length=50, null=True, blank=True)
    threshold_aman = models.CharField(max_length=100, null=True, blank=True)
    threshold_hati_hati = models.CharField(max_length=100, null=True, blank=True)
    threshold_bahaya = models.CharField(max_length=100, null=True, blank=True)
    arah_threshold = models.CharField(max_length=20, choices=ARAH_CHOICES, null=True, blank=True)
    nilai_aktual = models.CharField(max_length=100, null=True, blank=True)
    status_threshold = models.CharField(max_length=30, null=True, blank=True)
    catatan = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "ra_risk_indicator"

    def __str__(self):
        return self.nama_kri


class ExistingControl(models.Model):
    risk_event = models.ForeignKey(
        RiskEvent,
        on_delete=models.CASCADE,
        related_name="existing_controls",
    )
    risk_cause = models.ForeignKey(
        RiskCause,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="controls",
    )
    jenis_control = models.CharField(max_length=100, null=True, blank=True)
    nama_control = models.CharField(max_length=255)
    deskripsi_control = models.TextField(null=True, blank=True)
    efektivitas_control = models.CharField(max_length=30, null=True, blank=True)
    pemilik_control = models.ForeignKey(
        UnitOrganisasi,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="controls_owned",
    )
    catatan = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "ra_existing_control"

    def __str__(self):
        return self.nama_control


class RiskAssessment(TimeStampedModel):
    TYPE_CHOICES = [
        ("inherent", "Inherent"),
        ("residual", "Residual"),
        ("target_residual", "Target Residual"),
    ]

    risk_event = models.ForeignKey(
        RiskEvent,
        on_delete=models.CASCADE,
        related_name="assessments",
    )
    periode = models.ForeignKey(PeriodeLaporan, on_delete=models.PROTECT)
    risk_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    nilai_dampak = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    skala_dampak = models.ForeignKey(
        SkalaDampak,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    nilai_probabilitas = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    skala_probabilitas = models.ForeignKey(
        SkalaProbabilitas,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    level_risiko = models.PositiveSmallIntegerField(null=True, blank=True)
    warna_level = models.CharField(max_length=20, null=True, blank=True)
    justifikasi = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "ra_risk_assessment"
        unique_together = [("risk_event", "periode", "risk_type")]

    def __str__(self):
        return f"{self.risk_event.no_risiko} - {self.risk_type}"


class TreatmentPlan(TimeStampedModel):
    OPSI_CHOICES = [
        ("avoid", "Avoid"),
        ("reduce", "Reduce"),
        ("transfer", "Transfer"),
        ("accept", "Accept"),
    ]
    STATUS_CHOICES = [
        ("planned", "Planned"),
        ("on_progress", "On Progress"),
        ("done", "Done"),
        ("cancelled", "Cancelled"),
    ]

    risk_event = models.ForeignKey(
        RiskEvent,
        on_delete=models.CASCADE,
        related_name="treatment_plans",
    )
    risk_cause = models.ForeignKey(
        RiskCause,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="treatment_plans",
    )
    opsi_perlakuan = models.CharField(max_length=20, choices=OPSI_CHOICES)
    jenis_rencana = models.CharField(max_length=100, null=True, blank=True)
    rencana_perlakuan = models.TextField()
    output_perlakuan = models.TextField(null=True, blank=True)
    anggaran = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    ai = models.CharField(max_length=100, null=True, blank=True)
    ao = models.CharField(max_length=100, null=True, blank=True)
    jenis_program_rkap = models.CharField(max_length=100, null=True, blank=True)
    pic = models.ForeignKey(
        UnitOrganisasi,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="treatment_plan_pic",
    )
    target_mulai = models.DateField(null=True, blank=True)
    target_selesai = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="planned")

    class Meta:
        db_table = "ra_treatment_plan"

    def __str__(self):
        return f"Treatment - {self.risk_event.no_risiko}"


class TreatmentTimeline(models.Model):
    treatment_plan = models.ForeignKey(
        TreatmentPlan,
        on_delete=models.CASCADE,
        related_name="timelines",
    )
    bulan_ke = models.PositiveSmallIntegerField()
    planned_flag = models.BooleanField(default=False)
    actual_flag = models.BooleanField(default=False)
    catatan = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "ra_treatment_timeline"
        unique_together = [("treatment_plan", "bulan_ke")]

    def __str__(self):
        return f"{self.treatment_plan_id} - Bulan {self.bulan_ke}"


class TreatmentProgress(models.Model):
    STATUS_CHOICES = [
        ("not_started", "Not Started"),
        ("on_progress", "On Progress"),
        ("done", "Done"),
        ("delayed", "Delayed"),
    ]

    treatment_plan = models.ForeignKey(
        TreatmentPlan,
        on_delete=models.CASCADE,
        related_name="progress_list",
    )
    periode = models.ForeignKey(PeriodeLaporan, on_delete=models.PROTECT)
    persentase_progress = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    status_realisasi = models.CharField(max_length=30, choices=STATUS_CHOICES)
    realisasi_biaya = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    eviden_attachment = models.ForeignKey(
        "core.Attachment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    catatan = models.TextField(null=True, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ra_treatment_progress"
        unique_together = [("treatment_plan", "periode")]

    def __str__(self):
        return f"{self.treatment_plan_id} - {self.periode_id}"


class ReAssessmentWorkflowLog(models.Model):
    ACTION_SUBMIT = "submit"
    ACTION_REVIEW_RKM = "review_rkm"
    ACTION_APPROVE_RKM = "approve_rkm"
    ACTION_REJECT_RKM = "reject_rkm"
    ACTION_REVIEW_KM = "review_km"
    ACTION_APPROVE_KM = "approve_km"
    ACTION_REJECT_KM = "reject_km"
    ACTION_LOCK = "lock"
    ACTION_RETURN_TO_UNIT = "return_to_unit"

    ACTION_CHOICES = [
        (ACTION_SUBMIT, "Submit"),
        (ACTION_REVIEW_RKM, "Review RKM"),
        (ACTION_APPROVE_RKM, "Approve RKM"),
        (ACTION_REJECT_RKM, "Reject RKM"),
        (ACTION_REVIEW_KM, "Review KM"),
        (ACTION_APPROVE_KM, "Approve KM"),
        (ACTION_REJECT_KM, "Reject KM"),
        (ACTION_LOCK, "Lock"),
        (ACTION_RETURN_TO_UNIT, "Return To Unit"),
    ]

    reassessment = models.ForeignKey(
        ReAssessment,
        on_delete=models.CASCADE,
        related_name="workflow_logs",
    )
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    from_status = models.CharField(max_length=30, null=True, blank=True)
    to_status = models.CharField(max_length=30)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ra_workflow_logs",
    )
    note = models.TextField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    acted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ra_workflow_log"
        ordering = ["-acted_at"]

    def __str__(self):
        return f"{self.reassessment.kode} - {self.action}"