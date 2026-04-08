# reassessment/models.py
from django.conf import settings
from django.db import models
from core.models import TimeStampedModel
from masterdata.models import (
    TahunBuku, PeriodeLaporan, UnitOrganisasi, SasaranBUMN, TaksonomiT3,
    KategoriRisiko, KategoriDampak, SkalaDampak, SkalaProbabilitas
)
from km.models import KontrakManajemen, KontrakManajemenItem


class ReAssessment(TimeStampedModel):
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
    versi = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="draft")
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ra_prepared"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="ra_reviewed", null=True, blank=True
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="ra_approved", null=True, blank=True
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    catatan = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "ra_reassessment"
        unique_together = [("tahun_buku", "periode", "unit", "versi")]


class RiskEvent(TimeStampedModel):
    STATUS_CHOICES = [
        ("aktif", "Aktif"),
        ("monitoring", "Monitoring"),
        ("closed", "Closed"),
    ]

    reassessment = models.ForeignKey(
        ReAssessment, on_delete=models.CASCADE, related_name="risk_events"
    )
    no_item = models.CharField(max_length=30)
    no_risiko = models.CharField(max_length=30)
    sasaran_bumn = models.ForeignKey(SasaranBUMN, on_delete=models.PROTECT, null=True, blank=True)
    km_item = models.ForeignKey(KontrakManajemenItem, on_delete=models.PROTECT, null=True, blank=True)
    taksonomi_t3 = models.ForeignKey(TaksonomiT3, on_delete=models.PROTECT, null=True, blank=True)
    kategori_risiko = models.ForeignKey(KategoriRisiko, on_delete=models.PROTECT, null=True, blank=True)
    kategori_dampak = models.ForeignKey(KategoriDampak, on_delete=models.PROTECT, null=True, blank=True)
    peristiwa_risiko = models.TextField()
    deskripsi_peristiwa = models.TextField(null=True, blank=True)
    deskripsi_dampak = models.TextField(null=True, blank=True)
    waktu_terpapar = models.CharField(max_length=100, null=True, blank=True)
    risk_owner = models.ForeignKey(
        UnitOrganisasi, on_delete=models.PROTECT, null=True, blank=True,
        related_name="owned_risks"
    )
    status_risiko = models.CharField(max_length=30, choices=STATUS_CHOICES, default="aktif")
    prioritas = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "ra_risk_event"
        unique_together = [("reassessment", "no_risiko")]
        ordering = ["reassessment", "no_item"]


class RiskCause(models.Model):
    risk_event = models.ForeignKey(
        RiskEvent, on_delete=models.CASCADE, related_name="causes"
    )
    kode_penyebab = models.CharField(max_length=30, null=True, blank=True)
    no_penyebab = models.CharField(max_length=30, null=True, blank=True)
    deskripsi_penyebab = models.TextField()
    urutan = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "ra_risk_cause"
        ordering = ["risk_event", "urutan"]


class RiskIndicator(models.Model):
    ARAH_CHOICES = [
        ("higher_better", "Higher Better"),
        ("lower_better", "Lower Better"),
        ("range", "Range"),
    ]

    risk_event = models.ForeignKey(
        RiskEvent, on_delete=models.CASCADE, related_name="indicators"
    )
    risk_cause = models.ForeignKey(
        RiskCause, on_delete=models.CASCADE, null=True, blank=True, related_name="indicators"
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


class ExistingControl(models.Model):
    risk_event = models.ForeignKey(
        RiskEvent, on_delete=models.CASCADE, related_name="existing_controls"
    )
    risk_cause = models.ForeignKey(
        RiskCause, on_delete=models.CASCADE, null=True, blank=True, related_name="controls"
    )
    jenis_control = models.CharField(max_length=100, null=True, blank=True)
    nama_control = models.CharField(max_length=255)
    deskripsi_control = models.TextField(null=True, blank=True)
    efektivitas_control = models.CharField(max_length=30, null=True, blank=True)
    pemilik_control = models.ForeignKey(
        UnitOrganisasi, on_delete=models.PROTECT, null=True, blank=True,
        related_name="controls_owned"
    )
    catatan = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "ra_existing_control"


class RiskAssessment(TimeStampedModel):
    TYPE_CHOICES = [
        ("inherent", "Inherent"),
        ("residual", "Residual"),
        ("target_residual", "Target Residual"),
    ]

    risk_event = models.ForeignKey(
        RiskEvent, on_delete=models.CASCADE, related_name="assessments"
    )
    periode = models.ForeignKey(PeriodeLaporan, on_delete=models.PROTECT)
    risk_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    nilai_dampak = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    skala_dampak = models.ForeignKey(SkalaDampak, on_delete=models.PROTECT, null=True, blank=True)
    nilai_probabilitas = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    skala_probabilitas = models.ForeignKey(
        SkalaProbabilitas, on_delete=models.PROTECT, null=True, blank=True
    )
    level_risiko = models.PositiveSmallIntegerField(null=True, blank=True)
    warna_level = models.CharField(max_length=20, null=True, blank=True)
    justifikasi = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "ra_risk_assessment"
        unique_together = [("risk_event", "periode", "risk_type")]


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
        RiskEvent, on_delete=models.CASCADE, related_name="treatment_plans"
    )
    risk_cause = models.ForeignKey(
        RiskCause, on_delete=models.CASCADE, null=True, blank=True, related_name="treatment_plans"
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
        UnitOrganisasi, on_delete=models.PROTECT, null=True, blank=True,
        related_name="treatment_plan_pic"
    )
    target_mulai = models.DateField(null=True, blank=True)
    target_selesai = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="planned")

    class Meta:
        db_table = "ra_treatment_plan"


class TreatmentTimeline(models.Model):
    treatment_plan = models.ForeignKey(
        TreatmentPlan, on_delete=models.CASCADE, related_name="timelines"
    )
    bulan_ke = models.PositiveSmallIntegerField()
    planned_flag = models.BooleanField(default=False)
    actual_flag = models.BooleanField(default=False)
    catatan = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "ra_treatment_timeline"
        unique_together = [("treatment_plan", "bulan_ke")]


class TreatmentProgress(models.Model):
    STATUS_CHOICES = [
        ("not_started", "Not Started"),
        ("on_progress", "On Progress"),
        ("done", "Done"),
        ("delayed", "Delayed"),
    ]

    treatment_plan = models.ForeignKey(
        TreatmentPlan, on_delete=models.CASCADE, related_name="progress_list"
    )
    periode = models.ForeignKey(PeriodeLaporan, on_delete=models.PROTECT)
    persentase_progress = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    status_realisasi = models.CharField(max_length=30, choices=STATUS_CHOICES)
    realisasi_biaya = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    eviden_attachment = models.ForeignKey(
        "core.Attachment", on_delete=models.SET_NULL, null=True, blank=True
    )
    catatan = models.TextField(null=True, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ra_treatment_progress"
        unique_together = [("treatment_plan", "periode")]