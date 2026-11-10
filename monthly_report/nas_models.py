"""NAS evidence metadata only. File bytes remain on Brightbox."""
from urllib.parse import urlsplit
import re
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction


def validate_nas_url(value):
    try:
        p = urlsplit(value)
        valid = (p.scheme == "https" and p.hostname == "brightbox.plnbatam.com"
                 and p.port in {None, 443, 5001} and not p.username and not p.password
                 and re.fullmatch(r"/sharing/[A-Za-z0-9_-]+/?", p.path)
                 and not p.query and not p.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ValidationError("Gunakan link HTTPS sharing Brightbox PLN Batam yang lengkap.")


class NASEvidenceLocation(models.Model):
    report = models.OneToOneField("monthly_report.MonthlyRiskReport", on_delete=models.PROTECT,
                                  related_name="nas_location", verbose_name="Laporan / bidang / periode")
    folder_path = models.CharField(max_length=700, verbose_name="Folder tujuan NAS",
        help_text="Salin path folder bidang dan bulan, diakhiri YYYY-MM. File Request harus dibuat pada folder ini.")
    upload_url = models.URLField(max_length=500, validators=[validate_nas_url], verbose_name="Link File Request (unggah)")
    enabled = models.BooleanField(default=True, verbose_name="Aktif")
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name = "Pengaturan Eviden NAS"
        verbose_name_plural = "Pengaturan Eviden NAS per Laporan"
    def __str__(self): return str(self.report)
    def clean(self):
        super().clean()
        if not self.report_id: return
        month = self.report.periode.tanggal_mulai.strftime("%Y-%m")
        path = self.folder_path.strip().rstrip("/")
        if (not path.startswith("/DIV MRK/3. Profil Risiko & Lap Risiko/")
                or ".." in path.split("/") or not path.endswith("/"+month)
                or "\\" in path):
            raise ValidationError({"folder_path": "Pilih folder bidang dengan bulan laporan yang sesuai: " + month})
        self.folder_path = path
    def save(self,*args,**kwargs):
        self.full_clean()
        super().save(*args,**kwargs)


class NASEvidence(models.Model):
    report = models.ForeignKey("monthly_report.MonthlyRiskReport", on_delete=models.PROTECT,
                              related_name="nas_evidences")
    location = models.ForeignKey(NASEvidenceLocation, on_delete=models.PROTECT)
    title = models.CharField(max_length=255, verbose_name="Judul eviden")
    read_url = models.URLField(max_length=500, validators=[validate_nas_url], verbose_name="Link baca hasil unggahan",
        help_text="Link yang dapat dibuka reviewer untuk melihat/mengunduh berkas; bukan link File Request.")
    relative_path = models.CharField(max_length=700, verbose_name="Subfolder / nama file eviden",
        help_text="Lokasi hasil unggahan di bawah folder tujuan, misalnya nama pengunggah/paket-eviden.zip.")
    description = models.TextField(blank=True, verbose_name="Keterangan / daftar isi berkas")
    report_scope = models.CharField(max_length=100, editable=False)
    folder_snapshot = models.CharField(max_length=700, editable=False)
    upload_url_snapshot = models.URLField(max_length=500, editable=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="nas_evidences_registered",editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    verified = models.BooleanField(default=False,editable=False)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name="nas_evidences_verified",editable=False)
    verified_at = models.DateTimeField(null=True,blank=True,editable=False)
    class Meta:
        ordering = ["created_at", "pk"]
        permissions = [("verify_nasevidence", "Dapat memverifikasi dan mencabut verifikasi eviden NAS")]
        verbose_name = "Eviden NAS"
        verbose_name_plural = "Eviden NAS"
    def __str__(self): return self.title
    def clean(self):
        super().clean()
        if self.location_id:
            if self.location.report_id != self.report_id:
                raise ValidationError("Folder NAS bukan milik laporan ini.")
            if not self.location.enabled:
                raise ValidationError("Pengaturan NAS belum aktif.")
            self.location.clean()
            if self.read_url.rstrip("/") == self.location.upload_url.rstrip("/"):
                raise ValidationError({"read_url": "Link unggah tidak dapat digunakan sebagai link baca eviden."})
        if NASEvidenceLocation.objects.filter(upload_url=self.read_url).exists():
            raise ValidationError({"read_url": "Link ini terdaftar sebagai File Request, bukan link baca."})
        parts = self.relative_path.replace("\\", "/").split("/")
        if (not self.relative_path.strip() or self.relative_path.startswith(("/", "\\"))
                or any(p in {"..", "."} for p in parts)):
            raise ValidationError({"relative_path": "Isi subfolder/nama file relatif yang valid."})
    def save(self,*args,**kwargs):
        from .models import MonthlyRiskReport
        with transaction.atomic():
            report=MonthlyRiskReport.objects.select_for_update().get(pk=self.report_id)
            if self.pk:
                raise ValidationError("Eviden NAS tersimpan tidak ditimpa. Tambahkan catatan eviden baru.")
            if report.status not in {"draft","revision"} or getattr(report,"is_locked",False):
                raise ValidationError("Pencatatan eviden hanya saat laporan Draft/Revisi dan tidak terkunci.")
            if self.verified or self.verified_by_id or self.verified_at:
                raise ValidationError("Gunakan proses verifikasi oleh petugas.")
            self.report_scope=f"{report.reassessment_id}:{report.periode_id}"
            self.folder_snapshot=self.location.folder_path
            self.upload_url_snapshot=self.location.upload_url
            self.full_clean()
            super().save(*args,**kwargs)
    def delete(self,*args,**kwargs):
        raise ValidationError("Eviden NAS diarsipkan; cabut verifikasi jika tidak valid.")


class NASEvidenceReview(models.Model):
    evidence=models.ForeignKey(NASEvidence,on_delete=models.PROTECT,related_name="reviews")
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    action=models.CharField(max_length=12,choices=[("verify","Verifikasi"),("revoke","Cabut verifikasi")])
    note=models.TextField()
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=["created_at","pk"]
