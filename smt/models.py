import uuid
from pathlib import Path
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone
from django.conf import settings
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
    revisi_sebelumnya = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True,
        related_name="revisi_lanjutan", editable=False,
        verbose_name="Revisi sebelumnya",
    )
    tujuan = models.TextField(blank=True)
    ruang_lingkup = models.TextField(blank=True)
    referensi = models.TextField(blank=True)
    tanggung_jawab = models.TextField(blank=True)
    langkah_kerja = models.TextField("Prosedur / langkah kerja", blank=True)
    catatan_revisi = models.TextField(blank=True)
    # SMT_APPROVAL_USERS_V1
    penyusun_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="smt_penyusun_documents", verbose_name="Nama Penyusun")
    verifikator_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="smt_verifikator_documents", verbose_name="Nama Verifikator")
    pengesah_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="smt_pengesah_documents", verbose_name="Nama Pengesah")
    # SMT_APPROVAL_METADATA_V1: identities from official document, not electronic signatures.
    penyusun_nama = models.CharField("Nama Penyusun", max_length=200, blank=True, default="")
    penyusun_jabatan = models.CharField("Jabatan Penyusun", max_length=255, blank=True, default="")
    penyusun_tanggal = models.DateField("Tanggal Penyusun", null=True, blank=True)
    verifikator_nama = models.CharField("Nama Verifikator", max_length=200, blank=True, default="")
    verifikator_jabatan = models.CharField("Jabatan Verifikator", max_length=255, blank=True, default="")
    verifikator_tanggal = models.DateField("Tanggal Verifikator", null=True, blank=True)
    pengesah_nama = models.CharField("Nama Pengesah", max_length=200, blank=True, default="")
    pengesah_jabatan = models.CharField("Jabatan Pengesah", max_length=255, blank=True, default="")
    pengesah_tanggal = models.DateField("Tanggal Pengesah", null=True, blank=True)
    dibuat_pada = models.DateTimeField(auto_now_add=True)
    diperbarui_pada = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nomor", "-dibuat_pada"]
        constraints = [models.UniqueConstraint(fields=["jenis", "nomor", "revisi"], name="smt_unique_document_revision"), models.UniqueConstraint(fields=["jenis", "nomor"], condition=models.Q(status="active"), name="smt_one_active_revision"), models.UniqueConstraint(fields=["revisi_sebelumnya"], condition=models.Q(revisi_sebelumnya__isnull=False), name="smt_one_successor_per_revision")]

    def __str__(self):
        return f"{self.nomor} — {self.judul} (Rev. {self.revisi})"

    def save(self, *args, **kwargs):
        # Keep the name printed on historical documents stable after user edits.
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        update_fields = kwargs.get('update_fields')
        additions = set()
        if self._state.adding and self.status == 'draft':
            self.penyusun_tanggal = timezone.localdate()
            additions.add('penyusun_tanggal')
        watched = ('judul', 'nomor', 'unit_pemilik_id', 'tujuan', 'ruang_lingkup',
                   'referensi', 'tanggung_jawab', 'langkah_kerja', 'catatan_revisi',
                   'penyusun_user_id',
                   'verifikator_jabatan', 'pengesah_jabatan')
        if previous and previous.status in {'draft', 'review'} and any(
            getattr(previous, f) != getattr(self, f) for f in watched
            if update_fields is None or f in update_fields or f.removesuffix('_id') in update_fields
        ):
            self.verifikator_tanggal = self.pengesah_tanggal = None
            additions.update({'verifikator_tanggal', 'pengesah_tanggal'})
            if self.status == 'review':
                self.status = 'draft'
                additions.add('status')
        for role in ('verifikator', 'pengesah'):
            key = role + '_jabatan'
            if previous and getattr(previous, key) != getattr(self, key) and (
                update_fields is None or key in update_fields
            ):
                setattr(self, role + '_user_id', None)
                setattr(self, role + '_nama', '')
                additions.update({role + '_user', role + '_nama'})
        for role in ('penyusun', 'verifikator', 'pengesah'):
            key = role + '_user'
            if update_fields is not None and key not in update_fields and key + '_id' not in update_fields:
                continue
            identity = getattr(self, key + '_id')
            before = getattr(previous, key + '_id') if previous else None
            if identity and (before != identity or not getattr(self, role + '_nama')):
                user = getattr(self, key)
                setattr(self, role + '_nama', user.get_full_name().strip() or user.get_username())
                additions.add(role + '_nama')
            elif previous and before and identity is None:
                setattr(self, role + '_nama', '')
                additions.add(role + '_nama')
        if self.status in {'draft', 'review'} and (
            update_fields is None or 'penyusun_user' in update_fields or 'penyusun_user_id' in update_fields
        ):
            changed = previous and previous.penyusun_user_id != self.penyusun_user_id
            if changed or not self.penyusun_jabatan:
                from .approval_positions import current_positions
                titles = list(current_positions().filter(user_id=self.penyusun_user_id)
                    .order_by('jabatan').values_list('jabatan', flat=True).distinct()) if self.penyusun_user_id else []
                value = '; '.join(titles)
                if len(value) > 255:
                    raise ValidationError('Gabungan jabatan penyusun melebihi 255 karakter; periksa riwayat jabatan.')
                self.penyusun_jabatan = value
                additions.add('penyusun_jabatan')
        if update_fields is not None:
            kwargs['update_fields'] = set(update_fields) | additions
        return super().save(*args, **kwargs)

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
