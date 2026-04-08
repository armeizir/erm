# kpmr/models.py
from django.conf import settings
from django.db import models
from core.models import TimeStampedModel
from masterdata.models import TahunBuku, PeriodeLaporan, UnitOrganisasi, KPMRParameter, KPMRParameterOpsi
from reassessment.models import ReAssessment, RiskEvent


class KPMRReview(TimeStampedModel):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("in_review", "In Review"),
        ("finalized", "Finalized"),
        ("approved", "Approved"),
    ]

    kode = models.CharField(max_length=50, unique=True)
    judul = models.CharField(max_length=255)
    tahun_buku = models.ForeignKey(TahunBuku, on_delete=models.PROTECT)
    periode = models.ForeignKey(PeriodeLaporan, on_delete=models.PROTECT)
    unit = models.ForeignKey(UnitOrganisasi, on_delete=models.PROTECT)
    reassessment = models.ForeignKey(ReAssessment, on_delete=models.PROTECT)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="draft")
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="kpmr_reviewed"
    )
    review_lead = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="kpmr_review_lead", null=True, blank=True
    )
    tanggal_review = models.DateField(null=True, blank=True)
    skor_total_kpmr = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    grade_kpmr = models.CharField(max_length=10, null=True, blank=True)
    skor_kinerja = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    skor_komposit = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    catatan_umum = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "kpmr_review"
        unique_together = [("tahun_buku", "periode", "unit")]


class KPMRAnswer(TimeStampedModel):
    review = models.ForeignKey(KPMRReview, on_delete=models.CASCADE, related_name="answers")
    parameter = models.ForeignKey(KPMRParameter, on_delete=models.PROTECT)
    selected_option = models.ForeignKey(
        KPMRParameterOpsi, on_delete=models.PROTECT, null=True, blank=True
    )
    nilai_hasil = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    nilai_berbobot = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    dokumen_referensi = models.TextField(null=True, blank=True)
    keterangan = models.TextField(null=True, blank=True)
    reviewer_note = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "kpmr_answer"
        unique_together = [("review", "parameter")]


class KPMRRiskReview(TimeStampedModel):
    review = models.ForeignKey(KPMRReview, on_delete=models.CASCADE, related_name="risk_reviews")
    risk_event = models.ForeignKey(RiskEvent, on_delete=models.PROTECT)
    hasil_review = models.CharField(max_length=50)
    temuan = models.TextField(null=True, blank=True)
    rekomendasi = models.TextField(null=True, blank=True)
    status_tindak_lanjut = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "kpmr_risk_review"


class KPMRSupportingDocument(models.Model):
    review = models.ForeignKey(KPMRReview, on_delete=models.CASCADE, related_name="documents")
    nama_dokumen = models.CharField(max_length=255)
    kategori = models.CharField(max_length=50)
    attachment = models.ForeignKey("core.Attachment", on_delete=models.PROTECT)
    keterangan = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "kpmr_supporting_document"