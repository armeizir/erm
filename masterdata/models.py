# masterdata/models.py
from django.db import models
from core.models import TimeStampedModel


class UnitOrganisasi(TimeStampedModel):
    JENIS_CHOICES = [
        ("direksi", "Direksi"),
        ("direktorat", "Direktorat"),
        ("bidang", "Bidang"),
        ("unit", "Unit"),
        ("divisi", "Divisi"),
        ("subunit", "Sub Unit"),
    ]

    kode = models.CharField(max_length=30, unique=True)
    nama = models.CharField(max_length=255)
    jenis_unit = models.CharField(max_length=30, choices=JENIS_CHOICES)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )
    aktif = models.BooleanField(default=True)

    class Meta:
        db_table = "md_unit_organisasi"
        ordering = ["kode"]


class CompanyCode(TimeStampedModel):
    code = models.CharField(max_length=10, unique=True, verbose_name="Company Code")
    description = models.CharField(max_length=255, verbose_name="Description")
    aktif = models.BooleanField(default=True)

    class Meta:
        db_table = "md_company_code"
        verbose_name = "Company Code"
        verbose_name_plural = "Organization — Company Code"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.description}"


class BusinessArea(TimeStampedModel):
    company = models.ForeignKey(
        CompanyCode,
        on_delete=models.PROTECT,
        related_name="business_areas",
        verbose_name="Company Code",
    )
    code = models.CharField(max_length=10, verbose_name="Business Area")
    description = models.CharField(max_length=255, verbose_name="Description")
    aktif = models.BooleanField(default=True)

    class Meta:
        db_table = "md_business_area"
        verbose_name = "Business Area"
        verbose_name_plural = "Organization — Business Area"
        unique_together = [("company", "code")]
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.description}"


class PersonnelArea(TimeStampedModel):
    code = models.CharField(max_length=10, unique=True, verbose_name="Personnel Area")
    description = models.CharField(max_length=255, verbose_name="Description")
    company = models.ForeignKey(
        CompanyCode,
        on_delete=models.PROTECT,
        related_name="personnel_areas",
        null=True,
        blank=True,
        verbose_name="Company Code",
    )
    aktif = models.BooleanField(default=True)

    class Meta:
        db_table = "md_personnel_area"
        verbose_name = "Personnel Area"
        verbose_name_plural = "Organization — Personnel Area"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.description}"


class PersonnelSubArea(TimeStampedModel):
    personnel_area = models.ForeignKey(
        PersonnelArea,
        on_delete=models.PROTECT,
        related_name="sub_areas",
        verbose_name="Personnel Area",
    )
    code = models.CharField(max_length=10, verbose_name="Personnel Sub Area")
    description = models.CharField(max_length=255, verbose_name="Description")
    aktif = models.BooleanField(default=True)

    class Meta:
        db_table = "md_personnel_sub_area"
        verbose_name = "Personnel Sub Area"
        verbose_name_plural = "Organization — Personnel Sub Area"
        unique_together = [("personnel_area", "code")]
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.description}"


class Directorate(TimeStampedModel):
    code = models.CharField(max_length=10, unique=True, verbose_name="Directorate Code")
    description = models.CharField(max_length=255, verbose_name="Description")
    aktif = models.BooleanField(default=True)

    class Meta:
        db_table = "md_directorate"
        verbose_name = "Directorate"
        verbose_name_plural = "Organization — Directorate"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.description}"


class Division(TimeStampedModel):
    code = models.CharField(max_length=10, unique=True, verbose_name="Division Code")
    description = models.CharField(max_length=255, verbose_name="Description")
    directorate = models.ForeignKey(
        Directorate,
        on_delete=models.PROTECT,
        related_name="divisions",
        null=True,
        blank=True,
        verbose_name="Directorate",
    )
    aktif = models.BooleanField(default=True)

    class Meta:
        db_table = "md_division"
        verbose_name = "Division"
        verbose_name_plural = "Organization — Division"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.description}"


class OrganizationUnit(TimeStampedModel):
    code = models.CharField(max_length=20, unique=True, verbose_name="Org Code")
    name = models.CharField(max_length=255, verbose_name="Name")
    company = models.ForeignKey(
        CompanyCode,
        on_delete=models.PROTECT,
        related_name="organization_units",
        null=True,
        blank=True,
        verbose_name="Company Code",
    )
    business_area = models.ForeignKey(
        BusinessArea,
        on_delete=models.PROTECT,
        related_name="organization_units",
        null=True,
        blank=True,
        verbose_name="Business Area",
    )
    personnel_area = models.ForeignKey(
        PersonnelArea,
        on_delete=models.PROTECT,
        related_name="organization_units",
        null=True,
        blank=True,
        verbose_name="Personnel Area",
    )
    personnel_sub_area = models.ForeignKey(
        PersonnelSubArea,
        on_delete=models.PROTECT,
        related_name="organization_units",
        null=True,
        blank=True,
        verbose_name="Personnel Sub Area",
    )
    directorate = models.ForeignKey(
        Directorate,
        on_delete=models.PROTECT,
        related_name="organization_units",
        null=True,
        blank=True,
        verbose_name="Directorate",
    )
    division = models.ForeignKey(
        Division,
        on_delete=models.PROTECT,
        related_name="organization_units",
        null=True,
        blank=True,
        verbose_name="Division",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="children",
        null=True,
        blank=True,
        verbose_name="Parent Org Code",
    )
    aktif = models.BooleanField(default=True)

    class Meta:
        db_table = "md_organization_unit"
        verbose_name = "Organization Unit"
        verbose_name_plural = "Organization — Organization Unit"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class TahunBuku(TimeStampedModel):
    tahun = models.PositiveIntegerField(unique=True)
    aktif = models.BooleanField(default=True)

    class Meta:
        db_table = "md_tahun_buku"
        ordering = ["-tahun"]

    def __str__(self):
        return str(self.tahun)


class PeriodeLaporan(TimeStampedModel):
    JENIS_CHOICES = [
        ("tahunan", "Tahunan"),
        ("triwulan", "Triwulan"),
        ("bulanan", "Bulanan"),
    ]

    tahun_buku = models.ForeignKey(TahunBuku, on_delete=models.PROTECT)
    kode_periode = models.CharField(max_length=20)
    nama_periode = models.CharField(max_length=100)
    jenis_periode = models.CharField(max_length=20, choices=JENIS_CHOICES)
    tanggal_mulai = models.DateField()
    tanggal_selesai = models.DateField()
    is_locked = models.BooleanField(default=False)

    class Meta:
        db_table = "md_periode_laporan"
        unique_together = [("tahun_buku", "kode_periode")]
        ordering = ["-tanggal_mulai"]

    def __str__(self):
        return self.nama_periode

    

class SasaranBUMN(models.Model):
    kode = models.CharField(max_length=50, unique=True)
    nama = models.CharField(max_length=255)
    deskripsi = models.TextField(blank=True, null=True)
    aktif = models.BooleanField(default=True)

    class Meta:
        db_table = "md_sasaran_bumn"


class TaksonomiT3(models.Model):
    kode = models.CharField(max_length=50, unique=True)
    nama = models.CharField(max_length=255)
    deskripsi = models.TextField(blank=True, null=True)
    aktif = models.BooleanField(default=True)

    class Meta:
        db_table = "md_taksonomi_t3"


class KategoriRisiko(models.Model):
    kode = models.CharField(max_length=50, unique=True)
    nama = models.CharField(max_length=255)
    deskripsi = models.TextField(blank=True, null=True)
    aktif = models.BooleanField(default=True)

    class Meta:
        db_table = "md_kategori_risiko"

    def __str__(self):
        return self.nama


class KategoriDampak(models.Model):
    kode = models.CharField(max_length=50, unique=True)
    nama = models.CharField(max_length=255)
    aktif = models.BooleanField(default=True)

    class Meta:
        db_table = "md_kategori_dampak"


class SkalaDampak(models.Model):
    kategori_dampak = models.ForeignKey(KategoriDampak, on_delete=models.PROTECT)
    level_skala = models.PositiveSmallIntegerField()
    label = models.CharField(max_length=100)
    nilai_min = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    nilai_max = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    deskripsi = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "md_skala_dampak"
        unique_together = [("kategori_dampak", "level_skala")]


class SkalaProbabilitas(models.Model):
    level_skala = models.PositiveSmallIntegerField(unique=True)
    label = models.CharField(max_length=100)
    nilai_min = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    nilai_max = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    deskripsi = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "md_skala_probabilitas"


class KPMRParameter(models.Model):
    kode = models.CharField(max_length=50, unique=True)
    kelompok = models.CharField(max_length=50)
    nama_parameter = models.CharField(max_length=255)
    deskripsi = models.TextField(blank=True, null=True)
    bobot = models.DecimalField(max_digits=8, decimal_places=2)
    urutan = models.PositiveIntegerField(default=1)
    aktif = models.BooleanField(default=True)

    class Meta:
        db_table = "md_parameter_kpmr"
        ordering = ["urutan", "kode"]


class KPMRParameterOpsi(models.Model):
    parameter = models.ForeignKey(KPMRParameter, on_delete=models.CASCADE, related_name="opsi_list")
    kode_opsi = models.CharField(max_length=10)
    label_opsi = models.CharField(max_length=255)
    nilai = models.DecimalField(max_digits=8, decimal_places=2)
    urutan = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "md_parameter_kpmr_opsi"
        unique_together = [("parameter", "kode_opsi")]
        ordering = ["parameter", "urutan"]

class MasterBUMN(models.Model):
    nama = models.CharField(max_length=200, unique=True)
    kode = models.CharField(max_length=50, unique=True)

    class Meta:
        verbose_name = "BUMN"
        verbose_name_plural = "MASTER — BUMN"
        ordering = ["nama"]

    def __str__(self):
        return f"{self.nama} ({self.kode})"
