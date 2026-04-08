# corporate_risk/models.py
from django.conf import settings
from django.db import models
from core.models import TimeStampedModel
from masterdata.models import (
    TahunBuku, PeriodeLaporan, KategoriRisiko, TaksonomiT3,
    KategoriDampak, UnitOrganisasi, SkalaDampak, SkalaProbabilitas
)
from reassessment.models import RiskEvent


class CorporateRiskProfile(TimeStampedModel):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("aggregated", "Aggregated"),
        ("reviewed", "Reviewed"),
        ("approved", "Approved"),
        ("published", "Published"),
    ]

    kode = models.CharField(max_length=50, unique=True)
    judul = models.CharField(max_length=255)
    tahun_buku = models.ForeignKey(TahunBuku, on_delete=models.PROTECT)
    periode = models.ForeignKey(PeriodeLaporan, on_delete=models.PROTECT)
    nama_perusahaan = models.CharField(max_length=255, default="PT PLN Batam")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="draft")
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cr_prepared"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="cr_reviewed", null=True, blank=True
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="cr_approved", null=True, blank=True
    )
    catatan = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "cr_profile"
        unique_together = [("tahun_buku", "periode")]


class CorporateRiskItem(TimeStampedModel):
    profile = models.ForeignKey(
        CorporateRiskProfile, on_delete=models.CASCADE, related_name="items"
    )
    no_item = models.CharField(max_length=30)
    sasaran_korporat = models.CharField(max_length=255, null=True, blank=True)
    kategori_risiko = models.ForeignKey(KategoriRisiko, on_delete=models.PROTECT, null=True, blank=True)
    taksonomi_t3 = models.ForeignKey(TaksonomiT3, on_delete=models.PROTECT, null=True, blank=True)
    kategori_dampak = models.ForeignKey(KategoriDampak, on_delete=models.PROTECT, null=True, blank=True)
    peristiwa_risiko = models.TextField()
    deskripsi = models.TextField(null=True, blank=True)
    pemilik_risiko = models.ForeignKey(
        UnitOrganisasi, on_delete=models.PROTECT, null=True, blank=True,
        related_name="corporate_risk_owned"
    )
    status = models.CharField(max_length=30, default="aktif")
    prioritas = models.PositiveIntegerField(null=True, blank=True)
    catatan = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "cr_risk_item"
        unique_together = [("profile", "no_item")]


class CorporateRiskSource(models.Model):
    corporate_risk = models.ForeignKey(
        CorporateRiskItem, on_delete=models.CASCADE, related_name="sources"
    )
    risk_event = models.ForeignKey(RiskEvent, on_delete=models.PROTECT)
    unit = models.ForeignKey(UnitOrganisasi, on_delete=models.PROTECT)
    bobot_kontribusi = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    is_primary_source = models.BooleanField(default=False)
    keterangan = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "cr_risk_source"
        unique_together = [("corporate_risk", "risk_event")]


class CorporateRiskTarget(models.Model):
    corporate_risk = models.ForeignKey(
        CorporateRiskItem, on_delete=models.CASCADE, related_name="targets"
    )
    periode = models.ForeignKey(PeriodeLaporan, on_delete=models.PROTECT)
    target_dampak = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    target_skala_dampak = models.ForeignKey(
        SkalaDampak, on_delete=models.PROTECT, null=True, blank=True
    )
    target_probabilitas = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    target_skala_probabilitas = models.ForeignKey(
        SkalaProbabilitas, on_delete=models.PROTECT, null=True, blank=True
    )
    target_level_risiko = models.PositiveSmallIntegerField(null=True, blank=True)
    catatan = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "cr_risk_target"
        unique_together = [("corporate_risk", "periode")]


class CorporateRiskRealization(models.Model):
    corporate_risk = models.ForeignKey(
        CorporateRiskItem, on_delete=models.CASCADE, related_name="realizations"
    )
    periode = models.ForeignKey(PeriodeLaporan, on_delete=models.PROTECT)
    actual_dampak = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    actual_skala_dampak = models.ForeignKey(
        SkalaDampak, on_delete=models.PROTECT, null=True, blank=True
    )
    actual_probabilitas = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    actual_skala_probabilitas = models.ForeignKey(
        SkalaProbabilitas, on_delete=models.PROTECT, null=True, blank=True
    )
    actual_level_risiko = models.PositiveSmallIntegerField(null=True, blank=True)
    realisasi_perlakuan = models.TextField(null=True, blank=True)
    realisasi_biaya = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    status_monitoring = models.CharField(max_length=30, null=True, blank=True)
    catatan = models.TextField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cr_risk_realization"
        unique_together = [("corporate_risk", "periode")]


class CorporateTreatmentPlan(TimeStampedModel):
    corporate_risk = models.ForeignKey(
        CorporateRiskItem, on_delete=models.CASCADE, related_name="treatment_plans"
    )
    rencana = models.TextField()
    output = models.TextField(null=True, blank=True)
    anggaran = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    pic = models.ForeignKey(
        UnitOrganisasi, on_delete=models.PROTECT, null=True, blank=True,
        related_name="corporate_treatment_pic"
    )
    timeline_mulai = models.DateField(null=True, blank=True)
    timeline_selesai = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, default="planned")

    class Meta:
        db_table = "cr_treatment_plan"