# imports/models.py
from django.conf import settings
from django.db import models
from core.models import Attachment
from masterdata.models import TahunBuku, PeriodeLaporan, UnitOrganisasi


class ImportJob(models.Model):
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("processing", "Processing"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("partial", "Partial"),
    ]

    module_name = models.CharField(max_length=50)
    source_file = models.ForeignKey(Attachment, on_delete=models.PROTECT)
    tahun_buku = models.ForeignKey(TahunBuku, on_delete=models.PROTECT, null=True, blank=True)
    periode = models.ForeignKey(PeriodeLaporan, on_delete=models.PROTECT, null=True, blank=True)
    unit = models.ForeignKey(UnitOrganisasi, on_delete=models.PROTECT, null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="queued")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    executed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    summary_message = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "imp_job"


class ImportJobDetail(models.Model):
    STATUS_CHOICES = [
        ("success", "Success"),
        ("warning", "Warning"),
        ("error", "Error"),
    ]

    job = models.ForeignKey(ImportJob, on_delete=models.CASCADE, related_name="details")
    sheet_name = models.CharField(max_length=100, null=True, blank=True)
    row_number = models.PositiveIntegerField(null=True, blank=True)
    reference_key = models.CharField(max_length=100, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    message = models.TextField()
    raw_payload = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "imp_job_detail"