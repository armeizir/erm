import uuid
from pathlib import Path
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from .storage import PrivateDocumentStorage


def document_path(instance, filename):
    return f"documents/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


class Document(models.Model):
    class Kind(models.TextChoices):
        PI = "PI", "Prosedur Integrasi (PI)"
        IK = "IK", "Instruksi Kerja (IK)"
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        REVIEW = "review", "Dalam Review"
        ACTIVE = "active", "Berlaku"
        RETIRED = "retired", "Tidak Berlaku"
    jenis = models.CharField(max_length=2, choices=Kind.choices)
    nomor = models.CharField("Nomor dokumen", max_length=150)
    judul = models.CharField(max_length=255)
    unit_pemilik = models.ForeignKey("masterdata.OrganizationUnit", on_delete=models.PROTECT, verbose_name="Unit pemilik")
    revisi = models.CharField(max_length=30, default="00")
    tanggal_berlaku = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    prosedur_induk = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="instruksi_kerja", limit_choices_to={"jenis": "PI"}, verbose_name="Prosedur Integrasi terkait")
    tujuan = models.TextField(blank=True)
    ruang_lingkup = models.TextField(blank=True)
    referensi = models.TextField(blank=True)
    tanggung_jawab = models.TextField(blank=True)
    langkah_kerja = models.TextField("Prosedur / langkah kerja", blank=True)
    catatan_revisi = models.TextField(blank=True)
    dibuat_pada = models.DateTimeField(auto_now_add=True)
    diperbarui_pada = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nomor", "-dibuat_pada"]
        constraints = [models.UniqueConstraint(fields=["jenis", "nomor", "revisi"], name="smt_unique_document_revision"), models.UniqueConstraint(fields=["jenis", "nomor"], condition=models.Q(status="active"), name="smt_one_active_revision")]

    def __str__(self):
        return f"{self.nomor} — {self.judul} (Rev. {self.revisi})"

    def clean(self):
        super().clean()
        if self.jenis == self.Kind.PI and self.prosedur_induk_id:
            raise ValidationError({"prosedur_induk": "PI tidak mempunyai prosedur induk."})
        if self.prosedur_induk_id and (self.prosedur_induk_id == self.pk or self.prosedur_induk.jenis != self.Kind.PI):
            raise ValidationError({"prosedur_induk": "Pilih dokumen Prosedur Integrasi (PI)."})
        if self.status == self.Status.ACTIVE and not self.tanggal_berlaku:
            raise ValidationError({"tanggal_berlaku": "Tanggal berlaku wajib untuk dokumen berstatus Berlaku."})


class ProsedurIntegrasi(Document):
    class Meta:
        proxy = True
        verbose_name = "Prosedur Integrasi (PI)"
        verbose_name_plural = "Prosedur Integrasi (PI)"


class InstruksiKerja(Document):
    class Meta:
        proxy = True
        verbose_name = "Instruksi Kerja (IK)"
        verbose_name_plural = "Instruksi Kerja (IK)"


class Attachment(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="lampiran")
    nama = models.CharField("Nama lampiran", max_length=200)
    jenis = models.CharField(max_length=20, choices=[("utama", "Dokumen Utama"), ("pengesahan", "Lembar Pengesahan"), ("alur", "Diagram Alir"), ("form", "Formulir"), ("lain", "Lainnya")], default="utama")
    berkas = models.FileField(storage=PrivateDocumentStorage(), upload_to=document_path, validators=[FileExtensionValidator(["pdf", "doc", "docx", "xls", "xlsx", "png", "jpg", "jpeg"])])
    diunggah_pada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Lampiran"
        verbose_name_plural = "Lampiran dokumen"

    def __str__(self):
        return self.nama
