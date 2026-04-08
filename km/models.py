# km/models.py
from django.conf import settings
from django.db import models
from core.models import TimeStampedModel
from masterdata.models import TahunBuku, UnitOrganisasi, PeriodeLaporan


class KontrakManajemen(TimeStampedModel):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("reviewed", "Reviewed"),
        ("approved", "Approved"),
        ("archived", "Archived"),
    ]

    kode = models.CharField(max_length=50, unique=True)
    judul = models.CharField(max_length=255)
    tahun_buku = models.ForeignKey(TahunBuku, on_delete=models.PROTECT)
    unit = models.ForeignKey(UnitOrganisasi, on_delete=models.PROTECT)
    versi = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="draft")
    tanggal_berlaku = models.DateField(null=True, blank=True)
    tanggal_disetujui = models.DateField(null=True, blank=True)
    dibuat_oleh = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="km_dibuat"
    )
    disetujui_oleh = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="km_disetujui", null=True, blank=True
    )

    class Meta:
        db_table = "km_kontrak_manajemen"
        unique_together = [("tahun_buku", "unit", "versi")]


class KontrakManajemenBagian(models.Model):
    kontrak = models.ForeignKey(
        KontrakManajemen, on_delete=models.CASCADE, related_name="bagian_list"
    )
    kode_bagian = models.CharField(max_length=30)
    nama_bagian = models.CharField(max_length=255)
    urutan = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "km_bagian"
        unique_together = [("kontrak", "kode_bagian")]
        ordering = ["kontrak", "urutan"]


class KontrakManajemenItem(models.Model):
    ARAH_CHOICES = [
        ("maximize", "Maximize"),
        ("minimize", "Minimize"),
        ("milestone", "Milestone"),
        ("score", "Score"),
    ]

    bagian = models.ForeignKey(
        KontrakManajemenBagian, on_delete=models.CASCADE, related_name="item_list"
    )
    no_urut = models.CharField(max_length=30)
    indikator = models.CharField(max_length=255)
    formula = models.TextField(null=True, blank=True)
    satuan = models.CharField(max_length=50, null=True, blank=True)
    bobot = models.DecimalField(max_digits=8, decimal_places=2)
    target_tahunan = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    target_text = models.CharField(max_length=255, null=True, blank=True)
    arah_pencapaian = models.CharField(max_length=20, choices=ARAH_CHOICES)
    pic_unit = models.ForeignKey(
        UnitOrganisasi, on_delete=models.PROTECT, null=True, blank=True,
        related_name="km_item_pic"
    )
    keterangan = models.TextField(null=True, blank=True)
    aktif = models.BooleanField(default=True)

    class Meta:
        db_table = "km_item"
        unique_together = [("bagian", "no_urut")]
        ordering = ["bagian", "no_urut"]


class KontrakManajemenTargetPeriode(models.Model):
    km_item = models.ForeignKey(
        KontrakManajemenItem, on_delete=models.CASCADE, related_name="target_periode_list"
    )
    periode = models.ForeignKey(PeriodeLaporan, on_delete=models.PROTECT)
    target_nilai = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    target_text = models.CharField(max_length=255, null=True, blank=True)
    realisasi_nilai = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    realisasi_text = models.CharField(max_length=255, null=True, blank=True)
    nilai_capaian = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    keterangan = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "km_target_periode"
        unique_together = [("km_item", "periode")]