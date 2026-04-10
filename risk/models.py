from decimal import Decimal
import string

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.db import models


# =========================================================
# MASTER DATA
# =========================================================

class TaksonomiT3(models.Model):
    kode = models.CharField(max_length=50, unique=True, verbose_name="Kode")
    nama = models.CharField(max_length=255, verbose_name="Nama Taksonomi T3")
    deskripsi = models.TextField(blank=True, null=True, verbose_name="Deskripsi")
    aktif = models.BooleanField(default=True, verbose_name="Aktif")

    class Meta:
        verbose_name = "Master Taksonomi T3"
        verbose_name_plural = "MASTER — Taksonomi T3"
        ordering = ["kode"]

    def __str__(self):
        return f"{self.kode} - {self.nama}"


class KategoriRisiko(models.Model):
    kode = models.CharField(max_length=50, unique=True, verbose_name="Kode")
    nama = models.CharField(max_length=255, verbose_name="Nama Kategori Risiko")
    deskripsi = models.TextField(blank=True, null=True, verbose_name="Deskripsi")
    aktif = models.BooleanField(default=True, verbose_name="Aktif")

    class Meta:
        verbose_name = "Master Kategori Risiko"
        verbose_name_plural = "MASTER — Kategori Risiko"
        ordering = ["kode"]

    def __str__(self):
        return f"{self.kode} - {self.nama}"


class SasaranKBUMN(models.Model):
    kode = models.CharField(max_length=50, unique=True, verbose_name="Kode")
    nama = models.CharField(max_length=255, verbose_name="Nama Sasaran KBUMN")
    deskripsi = models.TextField(blank=True, null=True, verbose_name="Deskripsi")
    aktif = models.BooleanField(default=True, verbose_name="Aktif")

    class Meta:
        verbose_name = "Master Sasaran KBUMN"
        verbose_name_plural = "MASTER — Sasaran KBUMN"
        ordering = ["kode"]

    def __str__(self):
        return f"{self.kode} - {self.nama}"


class MasterJenisExistingControl(models.Model):
    nama = models.CharField(max_length=100, unique=True)
    aktif = models.BooleanField(default=True)
    urutan = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "MASTER — Jenis Existing Control"
        verbose_name_plural = "MASTER — Jenis Existing Control"
        ordering = ["urutan", "nama"]

    def __str__(self):
        return self.nama


class MasterEfektivitasKontrol(models.Model):
    nama = models.CharField(max_length=100, unique=True)
    aktif = models.BooleanField(default=True)
    urutan = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "MASTER — Penilaian Efektivitas Kontrol"
        verbose_name_plural = "MASTER — Penilaian Efektivitas Kontrol"
        ordering = ["urutan", "nama"]

    def __str__(self):
        return self.nama


class MasterKategoriDampak(models.Model):
    nama = models.CharField(max_length=100, unique=True)
    aktif = models.BooleanField(default=True)
    urutan = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "MASTER — Kategori Dampak"
        verbose_name_plural = "MASTER — Kategori Dampak"
        ordering = ["urutan", "nama"]

    def __str__(self):
        return self.nama


class MasterSkalaDampak(models.Model):
    nama = models.CharField(max_length=100, unique=True)
    aktif = models.BooleanField(default=True)
    urutan = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "MASTER — Skala Dampak"
        verbose_name_plural = "MASTER — Skala Dampak"
        ordering = ["urutan", "nama"]

    def __str__(self):
        return self.nama


class MasterSkalaProbabilitas(models.Model):
    nama = models.CharField(max_length=100, unique=True)
    aktif = models.BooleanField(default=True)
    urutan = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "MASTER — Skala Probabilitas"
        verbose_name_plural = "MASTER — Skala Probabilitas"
        ordering = ["urutan", "nama"]

    def __str__(self):
        return self.nama


class MasterOpsiPerlakuanRisiko(models.Model):
    nama = models.CharField(max_length=100, unique=True)
    aktif = models.BooleanField(default=True)
    urutan = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "MASTER — Opsi Perlakuan Risiko"
        verbose_name_plural = "MASTER — Opsi Perlakuan Risiko"
        ordering = ["urutan", "nama"]

    def __str__(self):
        return self.nama


class MasterJenisRencanaPerlakuanRisiko(models.Model):
    nama = models.CharField(max_length=150, unique=True)
    aktif = models.BooleanField(default=True)
    urutan = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "MASTER — Jenis Rencana Perlakuan Risiko"
        verbose_name_plural = "MASTER — Jenis Rencana Perlakuan Risiko"
        ordering = ["urutan", "nama"]

    def __str__(self):
        return self.nama


class MasterPosAnggaran(models.Model):
    nama = models.CharField(max_length=100, unique=True)
    aktif = models.BooleanField(default=True)
    urutan = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "MASTER — Pos Anggaran"
        verbose_name_plural = "MASTER — Pos Anggaran"
        ordering = ["urutan", "nama"]

    def __str__(self):
        return self.nama


class MasterJenisProgramRKAP(models.Model):
    nama = models.CharField(max_length=150, unique=True)
    aktif = models.BooleanField(default=True)
    urutan = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "MASTER — Jenis Program Dalam RKAP"
        verbose_name_plural = "MASTER — Jenis Program Dalam RKAP"
        ordering = ["urutan", "nama"]

    def __str__(self):
        return self.nama


class MasterLevelRisiko(models.Model):
    kode = models.CharField(max_length=50, unique=True, verbose_name="Kode")
    nama = models.CharField(max_length=100, verbose_name="Nama Level Risiko")
    warna_hex = models.CharField(max_length=7, null=True, blank=True, verbose_name="Warna")
    aktif = models.BooleanField(default=True, verbose_name="Aktif")
    urutan = models.PositiveIntegerField(default=1, verbose_name="Urutan")

    class Meta:
        verbose_name = "MASTER — Level Risiko"
        verbose_name_plural = "MASTER — Level Risiko"
        ordering = ["urutan", "nama"]

    def __str__(self):
        return self.nama


class RiskMatrix(models.Model):
    kode = models.CharField(max_length=50, unique=True, verbose_name="Kode")
    nama = models.CharField(max_length=100, verbose_name="Nama Matriks Risiko")
    ukuran = models.PositiveSmallIntegerField(default=5, verbose_name="Ukuran")
    aktif = models.BooleanField(default=True, verbose_name="Aktif")
    is_default = models.BooleanField(default=False, verbose_name="Default")

    class Meta:
        verbose_name = "MASTER — Matriks Risiko"
        verbose_name_plural = "MASTER — Matriks Risiko"
        ordering = ["kode", "nama"]

    def __str__(self):
        return f"{self.kode} - {self.nama}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            RiskMatrix.objects.exclude(pk=self.pk).update(is_default=False)

    def get_cell(self, skala_dampak, skala_probabilitas):
        return self.cells.select_related("level_risiko").filter(
            skala_dampak=skala_dampak,
            skala_probabilitas=skala_probabilitas,
            aktif=True,
        ).first()


class RiskMatrixCell(models.Model):
    matrix = models.ForeignKey(
        "RiskMatrix",
        on_delete=models.CASCADE,
        related_name="cells",
        verbose_name="Matriks Risiko",
    )
    skala_dampak = models.ForeignKey(
        "MasterSkalaDampak",
        on_delete=models.PROTECT,
        related_name="risk_matrix_cells_dampak",
        verbose_name="Skala Dampak",
    )
    skala_probabilitas = models.ForeignKey(
        "MasterSkalaProbabilitas",
        on_delete=models.PROTECT,
        related_name="risk_matrix_cells_probabilitas",
        verbose_name="Skala Probabilitas",
    )
    skor = models.PositiveSmallIntegerField(verbose_name="Skor")
    level_risiko = models.ForeignKey(
        "MasterLevelRisiko",
        on_delete=models.PROTECT,
        related_name="risk_matrix_cells",
        verbose_name="Level Risiko",
    )
    warna_hex = models.CharField(max_length=7, null=True, blank=True, verbose_name="Warna")
    aktif = models.BooleanField(default=True, verbose_name="Aktif")

    class Meta:
        verbose_name = "MASTER — Sel Matriks Risiko"
        verbose_name_plural = "MASTER — Sel Matriks Risiko"
        ordering = ["matrix", "skala_probabilitas__urutan", "skala_dampak__urutan"]
        constraints = [
            models.UniqueConstraint(
                fields=["matrix", "skala_dampak", "skala_probabilitas"],
                name="unik_sel_matrix_per_dampak_probabilitas",
            )
        ]

    def __str__(self):
        return (
            f"{self.matrix.kode} | Dampak={self.skala_dampak} | "
            f"Probabilitas={self.skala_probabilitas}"
        )


# =========================================================
# PENUGASAN USER UNIT BISNIS
# =========================================================

class PenugasanUnitBisnis(models.Model):
    ROLE_PAIRING_OFFICER = "PAIRING_OFFICER"
    ROLE_RISK_CHAMPION = "RISK_CHAMPION"
    ROLE_RISK_OFFICER = "RISK_OFFICER"

    ROLE_CHOICES = [
        (ROLE_PAIRING_OFFICER, "Pairing Officer"),
        (ROLE_RISK_CHAMPION, "Risk Champion"),
        (ROLE_RISK_OFFICER, "Risk Officer"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="penugasan_unit_bisnis",
        verbose_name="User",
    )
    unit_bisnis = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name="penugasan_pengguna",
        verbose_name="Bidang / Unit Bisnis",
    )
    peran = models.CharField(
        max_length=30,
        choices=ROLE_CHOICES,
        verbose_name="Peran",
    )
    aktif = models.BooleanField(default=True, verbose_name="Aktif")
    catatan = models.CharField(max_length=255, blank=True, null=True, verbose_name="Catatan")
    dibuat_pada = models.DateTimeField(auto_now_add=True, verbose_name="Dibuat Pada")

    class Meta:
        verbose_name = "Penugasan User Unit Bisnis"
        verbose_name_plural = "MASTER — Penugasan User Unit Bisnis"
        ordering = ["unit_bisnis__name", "peran", "user__username"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "unit_bisnis", "peran"],
                name="unik_user_unit_bisnis_peran",
            )
        ]

    def clean(self):
        super().clean()

        if not self.aktif:
            return

        if self.peran in {self.ROLE_PAIRING_OFFICER, self.ROLE_RISK_CHAMPION}:
            existing = PenugasanUnitBisnis.objects.filter(
                unit_bisnis=self.unit_bisnis,
                peran=self.peran,
                aktif=True,
            ).exclude(pk=self.pk)
            if existing.exists():
                role_name = self.get_peran_display()
                raise ValidationError({
                    "peran": f"Unit bisnis ini sudah memiliki {role_name} aktif."
                })

    @property
    def nama_peran(self):
        return self.get_peran_display()

    def __str__(self):
        return f"{self.unit_bisnis.name} - {self.get_peran_display()} - {self.user.get_username()}"


# =========================================================
# KONTRAK MANAJEMEN UNIT / BIDANG
# =========================================================

class KontrakManajemen(models.Model):
    STATUS_CHOICES = [
        ("Draft", "Draft"),
        ("Final", "Final"),
    ]

    judul = models.CharField(max_length=200, verbose_name="Judul Kontrak")
    tahun = models.PositiveIntegerField(verbose_name="Tahun")
    unit_bisnis = models.ForeignKey(
        Group,
        on_delete=models.PROTECT,
        related_name="kontrak_manajemen",
        verbose_name="Bidang / Unit Bisnis",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Draft",
        verbose_name="Status",
    )
    dibuat_pada = models.DateTimeField(auto_now_add=True, verbose_name="Dibuat Pada")

    class Meta:
        verbose_name = "Kontrak Manajemen Unit/Bidang"
        verbose_name_plural = "TRANSAKSI UNIT — Kontrak Manajemen"
        ordering = ["-tahun", "judul"]
        constraints = [
            models.UniqueConstraint(
                fields=["judul", "tahun", "unit_bisnis"],
                name="unik_kontrak_manajemen_per_tahun_unit",
            )
        ]

    def __str__(self):
        return f"{self.judul} ({self.tahun})"


class BagianKontrakManajemen(models.Model):
    kontrak = models.ForeignKey(
        "KontrakManajemen",
        on_delete=models.CASCADE,
        related_name="bagian",
        verbose_name="Kontrak Manajemen",
    )
    kode_bagian = models.CharField(max_length=5, verbose_name="Kode Bagian")
    nama_bagian = models.CharField(max_length=255, verbose_name="Nama Bagian")

    class Meta:
        verbose_name = "Bagian Kontrak"
        verbose_name_plural = "TRANSAKSI UNIT — Bagian Kontrak"
        ordering = ["kontrak", "kode_bagian"]
        constraints = [
            models.UniqueConstraint(
                fields=["kontrak", "kode_bagian"],
                name="unik_bagian_per_kontrak",
            )
        ]

    def __str__(self):
        return f"{self.kode_bagian}. {self.nama_bagian}"


class ItemKontrakManajemen(models.Model):
    bagian = models.ForeignKey(
        "BagianKontrakManajemen",
        on_delete=models.CASCADE,
        related_name="item",
        verbose_name="Bagian Kontrak",
    )
    no_urut = models.PositiveIntegerField(verbose_name="No Urut")
    indikator_kinerja_kunci = models.TextField(verbose_name="Indikator Kinerja Kunci")
    formula = models.TextField(null=True, blank=True, verbose_name="Formula")
    satuan = models.CharField(max_length=50, null=True, blank=True, verbose_name="Satuan")
    bobot = models.DecimalField(max_digits=6, decimal_places=2, default=0, verbose_name="Bobot")
    target = models.CharField(max_length=255, null=True, blank=True, verbose_name="Target")

    class Meta:
        verbose_name = "Item Kontrak"
        verbose_name_plural = "TRANSAKSI UNIT — Item Kontrak"
        ordering = ["bagian", "no_urut"]
        constraints = [
            models.UniqueConstraint(
                fields=["bagian", "no_urut"],
                name="unik_item_kontrak_per_bagian",
            )
        ]

    def __str__(self):
        return f"{self.bagian.kode_bagian}.{self.no_urut}"
    
# ===== RKM (BARU) =====

class RKMSummary(models.Model):
    STATUS_CHOICES = [
        ("Draft", "Draft"),
        ("Final", "Final"),
    ]

    STATUS_PENGAJUAN_CHOICES = [
        ("Belum", "Belum"),
        ("Diajukan", "Diajukan"),
        ("Terlambat", "Terlambat"),
        ("Disetujui", "Disetujui"),
    ]

    judul = models.CharField(max_length=200, verbose_name="Judul RKM")
    tahun = models.PositiveIntegerField(verbose_name="Tahun")
    bulan = models.PositiveSmallIntegerField(verbose_name="Bulan")

    unit_bisnis = models.ForeignKey(
        Group,
        on_delete=models.PROTECT,
        related_name="rkm_summary",
        verbose_name="Bidang / Unit Bisnis",
    )

    kontrak_manajemen = models.ForeignKey(
        "KontrakManajemen",
        on_delete=models.PROTECT,
        related_name="rkm_summary",
        verbose_name="Kontrak Manajemen",
    )

    tanggal_mulai = models.DateField(
        null=True,
        blank=True,
        verbose_name="Tanggal Mulai",
    )

    tanggal_selesai = models.DateField(
        null=True,
        blank=True,
        verbose_name="Tanggal Selesai",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Draft",
        verbose_name="Status",
    )

    # =============================
    # TAMBAHAN RKM (PENTING)
    # =============================

    pic = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="PIC",
    )

    deadline_pengajuan = models.DateField(
        null=True,
        blank=True,
        verbose_name="Deadline Pengajuan Re-Assessment",
    )

    tanggal_pengajuan = models.DateField(
        null=True,
        blank=True,
        verbose_name="Tanggal Pengajuan",
    )

    status_pengajuan = models.CharField(
        max_length=20,
        choices=STATUS_PENGAJUAN_CHOICES,
        default="Belum",
        verbose_name="Status Pengajuan",
    )

    dibuat_pada = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Dibuat Pada",
    )

    class Meta:
        verbose_name = "RKM Unit/Bidang"
        verbose_name_plural = "TRANSAKSI UNIT — RKM"
        ordering = ["-tahun", "bulan", "judul"]
        constraints = [
            models.UniqueConstraint(
                fields=["tahun", "bulan", "unit_bisnis", "kontrak_manajemen"],
                name="unik_rkm_per_bulan_unit_km",
            )
        ]

    def __str__(self):
        return f"{self.judul} ({self.bulan}/{self.tahun})"

    @property
    def pairing_officer(self):
        return PenugasanUnitBisnis.objects.filter(
            unit_bisnis=self.unit_bisnis,
            peran=PenugasanUnitBisnis.ROLE_PAIRING_OFFICER,
            aktif=True,
        ).select_related("user").first()


    # =============================
    # VALIDASI
    # =============================

    def clean(self):
        if self.tanggal_mulai and self.tanggal_selesai:
            if self.tanggal_selesai < self.tanggal_mulai:
                raise ValidationError(
                    "Tanggal selesai tidak boleh lebih kecil dari tanggal mulai."
                )

    # =============================
    # AUTO STATUS PENGAJUAN
    # =============================

    def save(self, *args, **kwargs):
        from datetime import date

        if self.deadline_pengajuan:
            if not self.tanggal_pengajuan:
                if date.today() > self.deadline_pengajuan:
                    self.status_pengajuan = "Terlambat"
                else:
                    self.status_pengajuan = "Belum"
            else:
                if self.tanggal_pengajuan <= self.deadline_pengajuan:
                    self.status_pengajuan = "Diajukan"
                else:
                    self.status_pengajuan = "Terlambat"

        super().save(*args, **kwargs)

    # =============================
    # GENERATE ITEM DARI KM
    # =============================

    def generate_items_from_km(self):
        km_items = ItemKontrakManajemen.objects.filter(
            bagian__kontrak=self.kontrak_manajemen
        ).order_by("bagian__kode_bagian", "no_urut")

        created_count = 0
        no = 1

        for km_item in km_items:
            _, created = RKMItem.objects.get_or_create(
                summary=self,
                km_item=km_item,
                defaults={
                    "no_item": no,
                    "sasaran": km_item.indikator_kinerja_kunci,
                }
            )
            if created:
                created_count += 1
                no += 1

        return created_count
    
class RKMItem(models.Model):
    summary = models.ForeignKey(
        "RKMSummary",
        on_delete=models.CASCADE,
        related_name="item",
        verbose_name="Summary RKM",
    )
    no_item = models.PositiveIntegerField(verbose_name="No Item")
    km_item = models.ForeignKey(
        "ItemKontrakManajemen",
        on_delete=models.PROTECT,
        related_name="rkm_item",
        verbose_name="Item KM",
    )

    sasaran = models.TextField(blank=True, null=True, verbose_name="Sasaran / KPI")
    target_bulanan = models.CharField(max_length=255, blank=True, null=True, verbose_name="Target Bulanan")
    realisasi = models.CharField(max_length=255, blank=True, null=True, verbose_name="Realisasi")
    deviasi = models.CharField(max_length=255, blank=True, null=True, verbose_name="Deviasi")
    keterangan = models.TextField(blank=True, null=True, verbose_name="Keterangan")

    class Meta:
        verbose_name = "Item RKM"
        verbose_name_plural = "TRANSAKSI UNIT — Item RKM"
        ordering = ["summary", "no_item"]
        constraints = [
            models.UniqueConstraint(
                fields=["summary", "no_item"],
                name="unik_item_rkm_per_summary",
            ),
            models.UniqueConstraint(
                fields=["summary", "km_item"],
                name="unik_km_item_per_rkm",
            ),
        ]

    def __str__(self):
        return f"{self.summary} - {self.no_item}"

    def save(self, *args, **kwargs):
        if not self.sasaran and self.km_item:
            self.sasaran = self.km_item.indikator_kinerja_kunci
        super().save(*args, **kwargs)

# =========================================================
# PROFIL RISIKO UNIT / BIDANG (RE-ASSESSMENT)
# =========================================================

class ReAssessmentSummary(models.Model):
    judul = models.CharField(max_length=200, verbose_name="Judul Re-Assessment")
    tahun = models.PositiveIntegerField(verbose_name="Tahun")
    unit_bisnis = models.ForeignKey(
        Group,
        on_delete=models.PROTECT,
        related_name="reassessment_summary",
        verbose_name="Bidang / Unit Bisnis",
    )
    kontrak_manajemen = models.ForeignKey(
        "KontrakManajemen",
        on_delete=models.PROTECT,
        related_name="reassessment_summary",
        verbose_name="Kontrak Manajemen",
    )
    dibuat_pada = models.DateTimeField(auto_now_add=True, verbose_name="Dibuat Pada")
    risk_matrix = models.ForeignKey(
        "RiskMatrix",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reassessment_summaries",
        verbose_name="Matriks Risiko",
    )
    rkm = models.ForeignKey(
        "RKMSummary",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reassessments",
        verbose_name="RKM",
    )

    class Meta:
        verbose_name = "Profil Risiko Unit/Bidang"
        verbose_name_plural = "TRANSAKSI UNIT — Profil Risiko (Re-Assessment)"
        ordering = ["-tahun", "judul"]

    def __str__(self):
        return self.judul


class ReAssessmentItem(models.Model):
    summary = models.ForeignKey(
        ReAssessmentSummary,
        on_delete=models.CASCADE,
        related_name="item",
        verbose_name="Summary",
    )
    no_item = models.PositiveIntegerField(verbose_name="No Item")

    unit_bisnis = models.ForeignKey(
        Group,
        on_delete=models.PROTECT,
        related_name="reassessment_item",
        verbose_name="Bidang / Unit Bisnis",
        editable=False,
    )

    km_item = models.ForeignKey(
        ItemKontrakManajemen,
        on_delete=models.PROTECT,
        related_name="reassessment_item",
        verbose_name="Sasaran PLN Batam (KM Unit/Bidang)",
    )

    sasaran_kbumn = models.ForeignKey(
        SasaranKBUMN,
        on_delete=models.PROTECT,
        related_name="reassessment_item",
        blank=True,
        null=True,
        verbose_name="Sasaran KBUMN",
    )

    taksonomi_t3 = models.ForeignKey(
        TaksonomiT3,
        on_delete=models.PROTECT,
        related_name="reassessment_item",
        blank=True,
        null=True,
        verbose_name="Taksonomi Risiko PLN (T3)",
    )

    kategori_risiko = models.ForeignKey(
        KategoriRisiko,
        on_delete=models.PROTECT,
        related_name="reassessment_item",
        blank=True,
        null=True,
        verbose_name="Kategori Risiko",
    )

    no_risiko = models.PositiveIntegerField(verbose_name="No Risiko")
    peristiwa_risiko = models.TextField(verbose_name="Peristiwa Risiko")
    deskripsi_peristiwa_risiko = models.TextField(verbose_name="Deskripsi Peristiwa Risiko")

    no_penyebab_risiko = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        verbose_name="No Penyebab Risiko",
    )
    penyebab_risiko = models.TextField(
        null=True,
        blank=True,
        verbose_name="Penyebab Risiko",
    )

    key_risk_indicators = models.TextField(
        null=True,
        blank=True,
        verbose_name="Key Risk Indicators",
    )
    unit_satuan_kri = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Unit Satuan KRI",
    )

    threshold_aman = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Threshold Aman",
    )
    threshold_hati_hati = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Threshold Hati-Hati",
    )
    threshold_bahaya = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Threshold Bahaya",
    )

    jenis_existing_control = models.ForeignKey(
        "MasterJenisExistingControl",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Jenis Existing Control",
    )
    existing_control = models.TextField(
        null=True,
        blank=True,
        verbose_name="Existing Control",
    )
    penilaian_efektivitas_kontrol = models.ForeignKey(
        "MasterEfektivitasKontrol",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Penilaian Efektivitas Kontrol",
    )

    kategori_dampak = models.ForeignKey(
        "MasterKategoriDampak",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Kategori Dampak",
    )
    deskripsi_dampak = models.TextField(
        null=True,
        blank=True,
        verbose_name="Deskripsi Dampak",
    )
    perkiraan_waktu_terpapar_risiko = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Perkiraan Waktu Terpapar Risiko",
    )
    asumsi_perhitungan_dampak = models.TextField(
        null=True,
        blank=True,
        verbose_name="Asumsi Perhitungan Dampak Kuantitatif / Penjelasan Dampak Kualitatif",
    )

    nilai_dampak = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Nilai Dampak",
    )
    nilai_dampak_q1 = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Nilai Dampak Q1",
    )
    nilai_dampak_q2 = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Nilai Dampak Q2",
    )
    nilai_dampak_q3 = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Nilai Dampak Q3",
    )
    nilai_dampak_q4 = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Nilai Dampak Q4",
    )

    skala_dampak_q1 = models.ForeignKey(
        "MasterSkalaDampak",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="dampak_q1",
        verbose_name="Skala Dampak Q1",
    )
    skala_dampak_q2 = models.ForeignKey(
        "MasterSkalaDampak",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="dampak_q2",
        verbose_name="Skala Dampak Q2",
    )
    skala_dampak_q3 = models.ForeignKey(
        "MasterSkalaDampak",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="dampak_q3",
        verbose_name="Skala Dampak Q3",
    )
    skala_dampak_q4 = models.ForeignKey(
        "MasterSkalaDampak",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="dampak_q4",
        verbose_name="Skala Dampak Q4",
    )

    nilai_probabilitas = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Nilai Probabilitas",
    )
    nilai_probabilitas_q1 = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Nilai Probabilitas Q1",
    )
    nilai_probabilitas_q2 = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Nilai Probabilitas Q2",
    )
    nilai_probabilitas_q3 = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Nilai Probabilitas Q3",
    )
    nilai_probabilitas_q4 = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Nilai Probabilitas Q4",
    )

    skala_probabilitas = models.ForeignKey(
        "MasterSkalaProbabilitas",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Skala Probabilitas",
    )
    skala_probabilitas_q1 = models.ForeignKey(
        "MasterSkalaProbabilitas",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="probabilitas_q1",
        verbose_name="Skala Probabilitas Q1",
    )
    skala_probabilitas_q2 = models.ForeignKey(
        "MasterSkalaProbabilitas",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="probabilitas_q2",
        verbose_name="Skala Probabilitas Q2",
    )
    skala_probabilitas_q3 = models.ForeignKey(
        "MasterSkalaProbabilitas",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="probabilitas_q3",
        verbose_name="Skala Probabilitas Q3",
    )
    skala_probabilitas_q4 = models.ForeignKey(
        "MasterSkalaProbabilitas",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="probabilitas_q4",
        verbose_name="Skala Probabilitas Q4",
    )

    eksposur_risiko_q1 = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Eksposur Risiko Q1",
    )
    eksposur_risiko_q2 = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Eksposur Risiko Q2",
    )
    eksposur_risiko_q3 = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Eksposur Risiko Q3",
    )
    eksposur_risiko_q4 = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Eksposur Risiko Q4",
    )

    skala_risiko_q1 = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Skala Risiko Q1",
    )
    skala_risiko_q2 = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Skala Risiko Q2",
    )
    skala_risiko_q3 = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Skala Risiko Q3",
    )
    skala_risiko_q4 = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Skala Risiko Q4",
    )

    level_nilai_risiko_q1 = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Level Risiko Q1",
    )
    level_nilai_risiko_q2 = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Level Risiko Q2",
    )
    level_nilai_risiko_q3 = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Level Risiko Q3",
    )
    level_nilai_risiko_q4 = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Level Risiko Q4",
    )

    opsi_perlakuan_risiko = models.ForeignKey(
        "MasterOpsiPerlakuanRisiko",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Opsi Perlakuan Risiko",
    )
    jenis_rencana_perlakuan_risiko = models.ManyToManyField(
        "MasterJenisRencanaPerlakuanRisiko",
        blank=True,
        verbose_name="Jenis Rencana Perlakuan Risiko",
    )
    rencana_perlakuan_risiko = models.TextField(
        null=True,
        blank=True,
        verbose_name="Rencana Perlakuan Risiko",
    )
    output_perlakuan_risiko = models.TextField(
        null=True,
        blank=True,
        verbose_name="Output Perlakuan Risiko",
    )
    biaya_perlakuan_risiko = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Biaya Perlakuan Risiko",
    )
    pos_anggaran = models.ForeignKey(
        "MasterPosAnggaran",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Pos Anggaran",
    )
    prk = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="PRK",
    )
    jenis_program_dalam_rkap = models.ForeignKey(
        "MasterJenisProgramRKAP",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Jenis Program Dalam RKAP",
    )
    pic = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="PIC",
    )

    timeline_1 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 1")
    timeline_2 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 2")
    timeline_3 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 3")
    timeline_4 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 4")
    timeline_5 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 5")
    timeline_6 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 6")
    timeline_7 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 7")
    timeline_8 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 8")
    timeline_9 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 9")
    timeline_10 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 10")
    timeline_11 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 11")
    timeline_12 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 12")

    class Meta:
        verbose_name = "Item Risiko Unit/Bidang"
        verbose_name_plural = "TRANSAKSI UNIT — Item Re-Assessment"
        ordering = ["summary", "no_item"]
        constraints = [
            models.UniqueConstraint(
                fields=["summary", "no_item"],
                name="unik_reassessment_item_per_summary",
            ),
            models.UniqueConstraint(
                fields=["summary", "no_risiko"],
                name="unik_reassessment_risiko_per_summary",
            ),
        ]

    def clean(self):
        if self.km_item and self.summary:
            if self.km_item.bagian.kontrak_id != self.summary.kontrak_manajemen_id:
                raise ValidationError(
                    "KM Item harus berasal dari Kontrak Manajemen yang sama dengan Summary."
                )

        if self.summary and self.summary.rkm:
            if self.summary.rkm.unit_bisnis_id != self.unit_bisnis_id:
                raise ValidationError(
                    "Unit bisnis Re-Assessment harus sama dengan unit bisnis RKM."
                )

            if self.summary.rkm.kontrak_manajemen_id != self.summary.kontrak_manajemen_id:
                raise ValidationError(
                    "Kontrak Manajemen Re-Assessment harus sama dengan Kontrak Manajemen pada RKM."
                )
        
    def _get_active_matrix(self):
        if self.summary and self.summary.risk_matrix_id:
            return self.summary.risk_matrix
        return RiskMatrix.objects.filter(aktif=True, is_default=True).first()

    def _assign_matrix_result(self, quarter):
        skala_dampak = getattr(self, f"skala_dampak_q{quarter}", None)
        skala_probabilitas = getattr(self, f"skala_probabilitas_q{quarter}", None)

        if not skala_dampak or not skala_probabilitas:
            setattr(self, f"skala_risiko_q{quarter}", None)
            setattr(self, f"level_nilai_risiko_q{quarter}", None)
            return

        matrix = self._get_active_matrix()
        if not matrix:
            return

        cell = matrix.get_cell(skala_dampak, skala_probabilitas)
        if not cell:
            raise ValidationError(
                f"Matrix cell tidak ditemukan untuk Q{quarter}: "
                f"Dampak={skala_dampak} Probabilitas={skala_probabilitas}"
            )

        setattr(self, f"skala_risiko_q{quarter}", str(cell.skor))
        setattr(self, f"level_nilai_risiko_q{quarter}", cell.level_risiko.nama)

    @property
    def kode_penyebab_risiko(self):
        if not self.summary:
            return ""
        bidang = self.summary.unit_bisnis.name if self.summary.unit_bisnis else ""
        no_risiko = self.no_risiko or ""
        no_penyebab = self.no_penyebab_risiko or ""
        return f"{bidang}-{no_risiko}-{no_penyebab}"

    def save(self, *args, **kwargs):
        if not self.unit_bisnis_id and self.summary_id:
            self.unit_bisnis = self.summary.unit_bisnis

        if not self.no_penyebab_risiko:
            count = ReAssessmentItem.objects.filter(
                summary=self.summary,
                no_risiko=self.no_risiko,
            ).exclude(pk=self.pk).count()
            self.no_penyebab_risiko = string.ascii_uppercase[count]

        if self.nilai_dampak is not None and self.nilai_dampak_q1 is None:
            self.nilai_dampak_q1 = self.nilai_dampak

        if self.nilai_probabilitas is not None:
            q1 = self.nilai_probabilitas
            q2 = (q1 * Decimal("0.75")).quantize(Decimal("0.01"))
            q3 = (q2 * Decimal("0.75")).quantize(Decimal("0.01"))
            q4 = (q3 * Decimal("0.75")).quantize(Decimal("0.01"))

            self.nilai_probabilitas_q1 = q1
            self.nilai_probabilitas_q2 = q2
            self.nilai_probabilitas_q3 = q3
            self.nilai_probabilitas_q4 = q4

        if self.nilai_dampak_q1 is not None and self.nilai_probabilitas_q1 is not None:
            self.eksposur_risiko_q1 = (
                self.nilai_dampak_q1 * (self.nilai_probabilitas_q1 / Decimal("100"))
            ).quantize(Decimal("0.01"))
        else:
            self.eksposur_risiko_q1 = None

        if self.nilai_dampak_q2 is not None and self.nilai_probabilitas_q2 is not None:
            self.eksposur_risiko_q2 = (
                self.nilai_dampak_q2 * (self.nilai_probabilitas_q2 / Decimal("100"))
            ).quantize(Decimal("0.01"))
        else:
            self.eksposur_risiko_q2 = None

        if self.nilai_dampak_q3 is not None and self.nilai_probabilitas_q3 is not None:
            self.eksposur_risiko_q3 = (
                self.nilai_dampak_q3 * (self.nilai_probabilitas_q3 / Decimal("100"))
            ).quantize(Decimal("0.01"))
        else:
            self.eksposur_risiko_q3 = None

        if self.nilai_dampak_q4 is not None and self.nilai_probabilitas_q4 is not None:
            self.eksposur_risiko_q4 = (
                self.nilai_dampak_q4 * (self.nilai_probabilitas_q4 / Decimal("100"))
            ).quantize(Decimal("0.01"))
        else:
            self.eksposur_risiko_q4 = None

        for q in range(1, 5):
            self._assign_matrix_result(q)

        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def no_km_kpi(self):
        return self.km_item.no_urut if self.km_item else None

    @property
    def sasaran_pln_batam(self):
        return self.km_item.indikator_kinerja_kunci if self.km_item else ""

    def __str__(self):
        return f"{self.summary} - {self.no_item}"



# =========================================================
# KPMR UNIT / BIDANG
# =========================================================

class KPMRSummary(models.Model):
    judul = models.CharField(max_length=200, verbose_name="Judul KPMR")
    tahun = models.PositiveIntegerField(verbose_name="Tahun")
    unit_bisnis = models.ForeignKey(
        Group,
        on_delete=models.PROTECT,
        related_name="kpmr_summary",
        verbose_name="Bidang / Unit Bisnis",
    )
    reassessment = models.ForeignKey(
        ReAssessmentSummary,
        on_delete=models.PROTECT,
        related_name="kpmr_summary",
        verbose_name="Re-Assessment",
    )
    dibuat_pada = models.DateTimeField(auto_now_add=True, verbose_name="Dibuat Pada")

    class Meta:
        verbose_name = "KPMR Unit/Bidang"
        verbose_name_plural = "TRANSAKSI UNIT — KPMR"
        ordering = ["-tahun", "judul"]

    def __str__(self):
        return self.judul

    @property
    def rkm(self):
        return self.reassessment.rkm if self.reassessment else None

    def _calculate_auto_score(self, reassessment_item):
        score = 0

        if reassessment_item.peristiwa_risiko:
            score += 20
        if reassessment_item.penyebab_risiko:
            score += 20
        if reassessment_item.skala_dampak_q1 and reassessment_item.skala_probabilitas_q1:
            score += 20
        if reassessment_item.rencana_perlakuan_risiko:
            score += 20
        if reassessment_item.output_perlakuan_risiko:
            score += 20

        return score

    def _calculate_auto_status(self, reassessment_item):
        score = self._calculate_auto_score(reassessment_item)
        if score >= 90:
            return "Sesuai"
        if score >= 60:
            return "Perlu Perbaikan"
        return "Tidak Sesuai"

    def _build_auto_note(self, reassessment_item):
        notes = []

        if not reassessment_item.peristiwa_risiko:
            notes.append("Peristiwa risiko belum diisi")
        if not reassessment_item.penyebab_risiko:
            notes.append("Penyebab risiko belum diisi")
        if not (reassessment_item.skala_dampak_q1 and reassessment_item.skala_probabilitas_q1):
            notes.append("Penilaian dampak/probabilitas belum lengkap")
        if not reassessment_item.rencana_perlakuan_risiko:
            notes.append("Rencana perlakuan risiko belum diisi")
        if not reassessment_item.output_perlakuan_risiko:
            notes.append("Output perlakuan risiko belum diisi")

        if not notes:
            return "Dihitung otomatis dari Re-Assessment"

        return "; ".join(notes)

    def generate_items_from_reassessment(self):
        reassessment_items = self.reassessment.item.all().order_by("no_item")
        created_or_updated_count = 0

        existing_ids = set(
            self.item.values_list("reassessment_item_id", flat=True)
        )
        current_ids = set()

        for reassessment_item in reassessment_items:
            current_ids.add(reassessment_item.id)

            defaults = {
                "no_item": reassessment_item.no_item,
                "perlakuan_risiko": reassessment_item.rencana_perlakuan_risiko or "",
                "bukti": reassessment_item.output_perlakuan_risiko or "",
                "nilai_kpmr": self._calculate_auto_score(reassessment_item),
                "status_kpmr": self._calculate_auto_status(reassessment_item),
                "catatan": self._build_auto_note(reassessment_item),
            }

            KPMRItem.objects.update_or_create(
                summary=self,
                reassessment_item=reassessment_item,
                defaults=defaults,
            )
            created_or_updated_count += 1

        # Hapus item yang sumber reassessment-nya sudah tidak ada
        stale_ids = existing_ids - current_ids
        if stale_ids:
            self.item.filter(reassessment_item_id__in=stale_ids).delete()

        return created_or_updated_count

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if self.reassessment_id:
            self.unit_bisnis = self.reassessment.unit_bisnis

            if not self.tahun:
                self.tahun = self.reassessment.tahun

            if not self.judul:
                self.judul = f"KPMR {self.reassessment.unit_bisnis.name} {self.reassessment.tahun}"

        super().save(*args, **kwargs)

        # Auto-generate item setiap save
        if self.reassessment_id:
            self.generate_items_from_reassessment()

class KPMRItem(models.Model):
    STATUS_CHOICES = [
        ("Sesuai", "Sesuai"),
        ("Tidak Sesuai", "Tidak Sesuai"),
        ("Perlu Perbaikan", "Perlu Perbaikan"),
    ]

    summary = models.ForeignKey(
        KPMRSummary,
        on_delete=models.CASCADE,
        related_name="item",
        verbose_name="Summary KPMR",
    )

    no_item = models.PositiveIntegerField(verbose_name="No Item")
    reassessment_item = models.ForeignKey(
        ReAssessmentItem,
        on_delete=models.PROTECT,
        related_name="kpmr_item",
        verbose_name="Re-Assessment Item",
    )
    perlakuan_risiko = models.TextField(blank=True, null=True, verbose_name="Perlakuan Risiko")
    bukti = models.TextField(blank=True, null=True, verbose_name="Bukti")
    nilai_kpmr = models.IntegerField(blank=True, null=True, verbose_name="Nilai KPMR")
    status_kpmr = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default="Perlu Perbaikan",
        verbose_name="Status KPMR",
    )
    catatan = models.TextField(blank=True, null=True, verbose_name="Catatan")

    class Meta:
        verbose_name = "Item KPMR"
        verbose_name_plural = "TRANSAKSI UNIT — Item KPMR"
        ordering = ["summary", "no_item"]
        constraints = [
            models.UniqueConstraint(
                fields=["summary", "reassessment_item"],
                name="unik_kpmr_item_per_summary",
            ),
            models.UniqueConstraint(
                fields=["summary", "no_item"],
                name="unik_no_item_kpmr_per_summary",
            ),
        ]

    def __str__(self):
        return f"{self.summary} - {self.no_item}"


# =========================================================
# PROFIL RISIKO KORPORAT
# =========================================================

class ProfilRisikoKorporatSummary(models.Model):
    STATUS_CHOICES = [
        ("Draft", "Draft"),
        ("Final", "Final"),
    ]

    judul = models.CharField(max_length=200, verbose_name="Judul Profil Risiko Korporat")
    tahun = models.PositiveIntegerField(verbose_name="Tahun")
    nama_perusahaan = models.CharField(
        max_length=200,
        default="PT PLN Batam",
        verbose_name="Nama BUMN",
    )
    kode_perusahaan = models.CharField(
        max_length=50,
        default="PLNBATAM",
        verbose_name="Kode BUMN",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Draft",
        verbose_name="Status",
    )
    catatan = models.TextField(blank=True, null=True, verbose_name="Catatan")
    dibuat_pada = models.DateTimeField(auto_now_add=True, verbose_name="Dibuat Pada")

    class Meta:
        verbose_name = "Profil Risiko Korporat"
        verbose_name_plural = "KORPORAT — Profil Risiko"
        ordering = ["-tahun", "judul"]

    def __str__(self):
        return f"{self.judul} ({self.tahun})"


class ProfilRisikoKorporatItem(models.Model):
    summary = models.ForeignKey(
        ProfilRisikoKorporatSummary,
        on_delete=models.CASCADE,
        related_name="item",
        verbose_name="Summary",
    )
    no_item = models.PositiveIntegerField(verbose_name="No Item")
    no_risiko = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="No Risiko",
    )

    bumn = models.ForeignKey(
        "masterdata.MasterBUMN",
        on_delete=models.PROTECT,
        verbose_name="Nama BUMN",
        default=1,
    )

    sasaran_korporat = models.TextField(verbose_name="Sasaran BUMN")

    sasaran_kbumn = models.ForeignKey(
        "SasaranKBUMN",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        verbose_name="Sasaran KBUMN",
    )

    kategori_risiko = models.ForeignKey(
        "KategoriRisiko",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        verbose_name="Kategori Risiko BUMN",
    )

    taksonomi_t3 = models.ForeignKey(
        "TaksonomiT3",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        verbose_name="Kategori Risiko T2 & T3",
    )

    peristiwa_risiko = models.TextField(verbose_name="Peristiwa Risiko")

    deskripsi_peristiwa_risiko = models.TextField(
        blank=True,
        null=True,
        verbose_name="Deskripsi Peristiwa Risiko",
    )

    dampak = models.IntegerField(blank=True, null=True, verbose_name="Dampak Inheren")
    kemungkinan = models.IntegerField(blank=True, null=True, verbose_name="Kemungkinan Inheren")
    level_risiko = models.IntegerField(blank=True, null=True, verbose_name="Level Risiko Inheren")
    matrix_cell_inheren = models.ForeignKey(
        "RiskMatrixCell",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="profil_risiko_korporat_inheren",
        verbose_name="Sel Matriks Inheren",
    )

    residual_dampak = models.IntegerField(blank=True, null=True, verbose_name="Dampak Residual")
    residual_kemungkinan = models.IntegerField(blank=True, null=True, verbose_name="Kemungkinan Residual")
    residual_level_risiko = models.IntegerField(blank=True, null=True, verbose_name="Level Risiko Residual")
    matrix_cell_residual = models.ForeignKey(
        "RiskMatrixCell",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="profil_risiko_korporat_residual",
        verbose_name="Sel Matriks Residual",
    )

    pemilik_risiko = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Pemilik Risiko",
    )

    status = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Status",
    )

    class Meta:
        verbose_name = "Item Risiko Korporat"
        verbose_name_plural = "KORPORAT — Item Risiko"
        ordering = ["summary", "no_item"]
        constraints = [
            models.UniqueConstraint(
                fields=["summary", "no_item"],
                name="unik_item_profil_risiko_korporat",
            ),
            models.UniqueConstraint(
                fields=["summary", "no_risiko"],
                name="unik_no_risiko_korporat_per_summary",
            ),
        ]

    @staticmethod
    def _get_default_matrix():
        return (
            RiskMatrix.objects.filter(is_default=True, aktif=True).first()
            or RiskMatrix.objects.filter(aktif=True).first()
        )

    @classmethod
    def _resolve_matrix_cell(cls, matrix, dampak, kemungkinan):
        if not matrix or dampak is None or kemungkinan is None:
            return None
        return matrix.cells.select_related("level_risiko").filter(
            skala_dampak__urutan=dampak,
            skala_probabilitas__urutan=kemungkinan,
            aktif=True,
        ).first()

    def _sync_matrix_values(self, matrix, dampak, kemungkinan, matrix_field_name, level_field_name):
        cell = self._resolve_matrix_cell(matrix, dampak, kemungkinan)
        setattr(self, matrix_field_name, cell)
        if cell:
            setattr(self, level_field_name, cell.skor)
        elif dampak is not None and kemungkinan is not None:
            setattr(self, level_field_name, dampak * kemungkinan)
        else:
            setattr(self, level_field_name, None)

    def save(self, *args, **kwargs):
        if self.no_risiko is None:
            last_no = ProfilRisikoKorporatItem.objects.filter(
                summary=self.summary
            ).exclude(pk=self.pk).aggregate(
                models.Max("no_risiko")
            )["no_risiko__max"] or 0
            self.no_risiko = last_no + 1

        matrix = self._get_default_matrix()
        self._sync_matrix_values(
            matrix, self.dampak, self.kemungkinan,
            "matrix_cell_inheren", "level_risiko"
        )
        self._sync_matrix_values(
            matrix, self.residual_dampak, self.residual_kemungkinan,
            "matrix_cell_residual", "residual_level_risiko"
        )

        super().save(*args, **kwargs)

    def get_mode_tuple(self, mode="inheren"):
        if mode == "residual":
            return (
                self.residual_dampak,
                self.residual_kemungkinan,
                self.residual_level_risiko,
                self.matrix_cell_residual,
            )
        return (
            self.dampak,
            self.kemungkinan,
            self.level_risiko,
            self.matrix_cell_inheren,
        )

    def get_level_name(self, mode="inheren"):
        cell = self.matrix_cell_residual if mode == "residual" else self.matrix_cell_inheren
        if cell and cell.level_risiko_id:
            return cell.level_risiko.nama
        return None

    def get_level_color(self, mode="inheren"):
        cell = self.matrix_cell_residual if mode == "residual" else self.matrix_cell_inheren
        if cell:
            return cell.warna_hex or getattr(cell.level_risiko, "warna_hex", None)
        return None

    @property
    def nama_bumn(self):
        return self.bumn.nama if self.bumn_id else ""

    @property
    def kode_bumn(self):
        return self.bumn.kode if self.bumn_id else ""

    def __str__(self):
        return f"{self.summary} - {self.no_item}"


class ProfilRisikoKorporatPenyebab(models.Model):
    risiko_korporat = models.ForeignKey(
        "ProfilRisikoKorporatItem",
        on_delete=models.CASCADE,
        related_name="daftar_penyebab",
        verbose_name="Risiko Korporat",
    )

    urutan = models.PositiveIntegerField(default=1, verbose_name="Urutan")

    no_penyebab_risiko = models.CharField(
        max_length=5,
        blank=True,
        verbose_name="No Penyebab",
    )

    kode_penyebab_risiko = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Kode Penyebab Risiko",
    )

    # ========================
    # PENYEBAB & KRI
    # ========================
    penyebab_risiko = models.TextField(blank=True, null=True)
    key_risk_indicators = models.TextField(
        blank=True,
        null=True,
        verbose_name="Key Risk Indicators",
    )
    unit_satuan_kri = models.CharField(max_length=50, blank=True, null=True)

    threshold_aman = models.CharField(max_length=50, blank=True, null=True)
    threshold_hati_hati = models.CharField(max_length=50, blank=True, null=True)
    threshold_bahaya = models.CharField(max_length=50, blank=True, null=True)

    # ========================
    # CONTROL
    # ========================
    jenis_existing_control = models.ForeignKey(
        "MasterJenisExistingControl",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
    )

    existing_control = models.TextField(blank=True, null=True)

    penilaian_efektivitas_kontrol = models.ForeignKey(
        "MasterEfektivitasKontrol",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
    )

    # ========================
    # DAMPAK
    # ========================
    kategori_dampak = models.ForeignKey(
        "MasterKategoriDampak",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
    )

    deskripsi_dampak = models.TextField(blank=True, null=True)

    perkiraan_waktu_terpapar = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ["risiko_korporat", "urutan"]
        verbose_name = "Penyebab Risiko"
        verbose_name_plural = "Penyebab Risiko (Multi Input)"

    def save(self, *args, **kwargs):
        # Auto A, B, C, D
        if not self.no_penyebab_risiko:
            self.no_penyebab_risiko = string.ascii_uppercase[self.urutan - 1]

        # Auto kode: 1-UBBES-1
        if not self.kode_penyebab_risiko and self.risiko_korporat_id:
            no_risiko = self.risiko_korporat.no_risiko or 0
            bumn = self.risiko_korporat.bumn.kode if self.risiko_korporat.bumn else "BUMN"
            self.kode_penyebab_risiko = f"{no_risiko}-{bumn}-{self.urutan}"

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.risiko_korporat} - {self.no_penyebab_risiko}"

class RisikoInherenKuantitatif(models.Model):
    risiko_korporat = models.OneToOneField(
        "ProfilRisikoKorporatItem",
        on_delete=models.CASCADE,
        related_name="inheren_kuantitatif",
        verbose_name="Risiko Korporat",
    )

    nilai_dampak = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Nilai Dampak",
    )
    probabilitas = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Probabilitas (%)",
    )
    eksposur = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Eksposur Risiko",
    )
    keterangan = models.TextField(
        blank=True,
        null=True,
        verbose_name="Keterangan",
    )

    class Meta:
        verbose_name = "Risiko Inheren Kuantitatif"
        verbose_name_plural = "KORPORAT — Risiko Inheren Kuantitatif"

    def save(self, *args, **kwargs):
        if self.nilai_dampak is not None and self.probabilitas is not None:
            self.eksposur = (
                self.nilai_dampak * (self.probabilitas / Decimal("100"))
            ).quantize(Decimal("0.01"))
        else:
            self.eksposur = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Kuantitatif - {self.risiko_korporat}"


class RencanaPerlakuanRisikoKorporat(models.Model):
    risiko_korporat = models.ForeignKey(
        "ProfilRisikoKorporatItem",
        on_delete=models.CASCADE,
        related_name="rencana_perlakuan_items",
        verbose_name="Risiko Korporat",
    )

    urutan = models.PositiveIntegerField(default=1, verbose_name="Urutan")

    opsi_perlakuan_risiko = models.ForeignKey(
        "MasterOpsiPerlakuanRisiko",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Opsi Perlakuan Risiko",
    )
    jenis_rencana_perlakuan_risiko = models.ManyToManyField(
        "MasterJenisRencanaPerlakuanRisiko",
        blank=True,
        verbose_name="Jenis Rencana Perlakuan Risiko",
    )
    rencana_perlakuan_risiko = models.TextField(
        null=True,
        blank=True,
        verbose_name="Rencana Perlakuan Risiko",
    )
    output_perlakuan_risiko = models.TextField(
        null=True,
        blank=True,
        verbose_name="Output Perlakuan Risiko",
    )
    biaya_perlakuan_risiko = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Biaya Perlakuan Risiko",
    )
    pos_anggaran = models.ForeignKey(
        "MasterPosAnggaran",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Pos Anggaran",
    )
    prk = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="PRK",
    )
    jenis_program_dalam_rkap = models.ForeignKey(
        "MasterJenisProgramRKAP",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Jenis Program Dalam RKAP",
    )
    pic = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="PIC",
    )

    timeline_1 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 1")
    timeline_2 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 2")
    timeline_3 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 3")
    timeline_4 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 4")
    timeline_5 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 5")
    timeline_6 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 6")
    timeline_7 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 7")
    timeline_8 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 8")
    timeline_9 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 9")
    timeline_10 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 10")
    timeline_11 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 11")
    timeline_12 = models.PositiveSmallIntegerField(default=0, verbose_name="Bulan 12")

    status = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Status",
    )
    keterangan = models.TextField(
        null=True,
        blank=True,
        verbose_name="Keterangan",
    )

    class Meta:
        verbose_name = "Rencana Perlakuan Risiko Korporat"
        verbose_name_plural = "KORPORAT — Rencana Perlakuan Risiko"
        ordering = ["risiko_korporat", "urutan"]

    def __str__(self):
        return f"Rencana Perlakuan - {self.risiko_korporat} - {self.urutan}"


class ProfilRisikoKorporatSumber(models.Model):
    risiko_korporat = models.ForeignKey(
        ProfilRisikoKorporatItem,
        on_delete=models.CASCADE,
        related_name="sumber_risiko",
        verbose_name="Risiko Korporat",
    )
    reassessment_item = models.ForeignKey(
        ReAssessmentItem,
        on_delete=models.PROTECT,
        related_name="mendukung_risiko_korporat",
        verbose_name="Risiko Bidang / Unit (Re-Assessment)",
    )

    no_penyebab_risiko = models.CharField(
        max_length=10,
        blank=True,
        verbose_name="No Penyebab Risiko",
    )
    kode_penyebab_risiko = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Kode Penyebab Risiko",
    )
    penyebab_risiko = models.TextField(
        blank=True,
        null=True,
        verbose_name="Penyebab Risiko",
    )
    keterangan = models.TextField(
        blank=True,
        null=True,
        verbose_name="Keterangan",
    )

    class Meta:
        verbose_name = "Sumber Risiko Korporat"
        verbose_name_plural = "KORPORAT — Sumber Risiko"
        constraints = [
            models.UniqueConstraint(
                fields=["risiko_korporat", "reassessment_item"],
                name="unik_sumber_risiko_korporat",
            )
        ]

    def save(self, *args, **kwargs):
        if not self.no_penyebab_risiko:
            count = ProfilRisikoKorporatSumber.objects.filter(
                risiko_korporat=self.risiko_korporat
            ).exclude(pk=self.pk).count()
            self.no_penyebab_risiko = string.ascii_uppercase[count]

        if not self.penyebab_risiko and self.reassessment_item_id:
            self.penyebab_risiko = self.reassessment_item.penyebab_risiko

        if not self.kode_penyebab_risiko and self.reassessment_item_id:
            self.kode_penyebab_risiko = self.reassessment_item.kode_penyebab_risiko

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.risiko_korporat} <- {self.reassessment_item}"

# =========================================================
# KPMR PLN 2026 (RESMI)
# =========================================================

class KPMRPeriode(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("final", "Final"),
    ]

    TRIWULAN_CHOICES = [
        (1, "TW1"),
        (2, "TW2"),
        (3, "TW3"),
        (4, "TW4"),
    ]

    RATING_CHOICES = [
        ("STRONG", "Strong"),
        ("SATISFACTORY", "Satisfactory"),
        ("FAIR", "Fair"),
        ("MARGINAL", "Marginal"),
        ("UNSATISFACTORY", "Unsatisfactory"),
    ]

    tahun = models.PositiveIntegerField(verbose_name="Tahun")
    triwulan = models.PositiveSmallIntegerField(
        choices=TRIWULAN_CHOICES,
        verbose_name="Triwulan",
    )
    unit_bisnis = models.ForeignKey(
        Group,
        on_delete=models.PROTECT,
        related_name="kpmr_periode",
        verbose_name="Bidang / Unit Bisnis",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft",
        verbose_name="Status",
    )

    skor_total = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name="Skor Total KPMR",
    )
    rating = models.CharField(
        max_length=20,
        choices=RATING_CHOICES,
        blank=True,
        null=True,
        verbose_name="Rating KPMR",
    )

    catatan = models.TextField(blank=True, null=True, verbose_name="Catatan")
    dibuat_pada = models.DateTimeField(auto_now_add=True, verbose_name="Dibuat Pada")
    diubah_pada = models.DateTimeField(auto_now=True, verbose_name="Diubah Pada")

    class Meta:
        verbose_name = "KPMR PLN — Periode"
        verbose_name_plural = "KPMR PLN — Periode"
        ordering = ["-tahun", "triwulan", "unit_bisnis__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tahun", "triwulan", "unit_bisnis"],
                name="unik_kpmr_periode_per_triwulan_unit",
            )
        ]

    def __str__(self):
        return f"KPMR {self.tahun} TW{self.triwulan} - {self.unit_bisnis.name}"


class KPMRIndikatorResmi(models.Model):
    KODE_CHOICES = [
        ("I1", "I1 - Pencapaian Nilai Eksposur Risiko vs Target Residual"),
        ("I2", "I2 - Pencapaian Output Perlakuan Risiko vs Target Output"),
        ("I3", "I3 - Realisasi Biaya Perlakuan Risiko vs Anggaran"),
        ("I4", "I4 - Ketepatan Penilaian Risiko"),
    ]

    periode = models.ForeignKey(
        KPMRPeriode,
        on_delete=models.CASCADE,
        related_name="indikator_resmi",
        verbose_name="Periode KPMR",
    )
    kode = models.CharField(max_length=5, choices=KODE_CHOICES, verbose_name="Kode")
    nama = models.CharField(max_length=255, verbose_name="Nama Indikator")
    bobot = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Bobot (%)")
    hasil = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Hasil",
    )
    skor = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
        verbose_name="Skor",
    )
    dokumen_referensi = models.TextField(blank=True, null=True, verbose_name="Dokumen Referensi")
    keterangan = models.TextField(blank=True, null=True, verbose_name="Keterangan")

    class Meta:
        verbose_name = "KPMR PLN — Indikator"
        verbose_name_plural = "KPMR PLN — Indikator"
        ordering = ["periode", "kode"]
        constraints = [
            models.UniqueConstraint(
                fields=["periode", "kode"],
                name="unik_indikator_kpmr_resmi_per_periode",
            )
        ]

    def __str__(self):
        return f"{self.periode} - {self.kode}"


class KPMRSubIndikatorResmi(models.Model):
    KODE_CHOICES = [
        ("IDENTIFIKASI", "Identifikasi Risiko"),
        ("KUANTIFIKASI", "Kuantifikasi Risiko"),
        ("RENCANA", "Rencana Perlakuan Risiko"),
        ("PRIORITISASI", "Prioritisasi Risiko"),
    ]

    indikator = models.ForeignKey(
        KPMRIndikatorResmi,
        on_delete=models.CASCADE,
        related_name="subindikator",
        verbose_name="Indikator KPMR",
    )
    kode = models.CharField(max_length=30, choices=KODE_CHOICES, verbose_name="Kode")
    nama = models.CharField(max_length=255, verbose_name="Nama Sub Indikator")
    bobot = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=25,
        verbose_name="Bobot (%)",
    )
    jawaban = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="Jawaban / Opsi",
    )
    hasil = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Hasil",
    )
    skor = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
        verbose_name="Skor",
    )
    keterangan = models.TextField(blank=True, null=True, verbose_name="Keterangan")

    class Meta:
        verbose_name = "KPMR PLN — Sub Indikator"
        verbose_name_plural = "KPMR PLN — Sub Indikator"
        ordering = ["indikator", "kode"]
        constraints = [
            models.UniqueConstraint(
                fields=["indikator", "kode"],
                name="unik_subindikator_kpmr_resmi_per_indikator",
            )
        ]

    def __str__(self):
        return f"{self.indikator} - {self.kode}"


class KinerjaPeriode(models.Model):
    RATING_CHOICES = [
        ("SANGAT_BAIK", "Sangat Baik"),
        ("BAIK", "Baik"),
        ("CUKUP", "Cukup"),
        ("KURANG", "Kurang"),
        ("BURUK", "Buruk"),
    ]

    TRIWULAN_CHOICES = [
        (1, "TW1"),
        (2, "TW2"),
        (3, "TW3"),
        (4, "TW4"),
    ]

    tahun = models.PositiveIntegerField(verbose_name="Tahun")
    triwulan = models.PositiveSmallIntegerField(
        choices=TRIWULAN_CHOICES,
        verbose_name="Triwulan",
    )
    unit_bisnis = models.ForeignKey(
        Group,
        on_delete=models.PROTECT,
        related_name="kinerja_periode",
        verbose_name="Bidang / Unit Bisnis",
    )
    skor_total = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name="Skor Total Kinerja",
    )
    rating = models.CharField(
        max_length=20,
        choices=RATING_CHOICES,
        blank=True,
        null=True,
        verbose_name="Rating Kinerja",
    )
    catatan = models.TextField(blank=True, null=True, verbose_name="Catatan")

    class Meta:
        verbose_name = "Kinerja Triwulanan"
        verbose_name_plural = "Kinerja Triwulanan"
        ordering = ["-tahun", "triwulan", "unit_bisnis__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tahun", "triwulan", "unit_bisnis"],
                name="unik_kinerja_periode_per_triwulan_unit",
            )
        ]

    def __str__(self):
        return f"Kinerja {self.tahun} TW{self.triwulan} - {self.unit_bisnis.name}"


class KinerjaIndikator(models.Model):
    NAMA_CHOICES = [
        ("KPI_KOLEGIAL", "Capaian KPI Kolegial"),
        ("KEUANGAN", "Capaian Kinerja Keuangan"),
        ("OPERASI", "Capaian Kinerja Operasi/Produksi Utama"),
    ]

    periode = models.ForeignKey(
        KinerjaPeriode,
        on_delete=models.CASCADE,
        related_name="indikator",
        verbose_name="Periode Kinerja",
    )
    nama = models.CharField(max_length=30, choices=NAMA_CHOICES, verbose_name="Indikator")
    bobot = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Bobot (%)")
    hasil = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Hasil",
    )
    skor = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
        verbose_name="Skor",
    )
    keterangan = models.TextField(blank=True, null=True, verbose_name="Keterangan")

    class Meta:
        verbose_name = "Kinerja — Indikator"
        verbose_name_plural = "Kinerja — Indikator"
        ordering = ["periode", "nama"]
        constraints = [
            models.UniqueConstraint(
                fields=["periode", "nama"],
                name="unik_indikator_kinerja_per_periode",
            )
        ]

    def __str__(self):
        return f"{self.periode} - {self.get_nama_display()}"


class KompositRisikoTriwulan(models.Model):
    periode_kpmr = models.OneToOneField(
        KPMRPeriode,
        on_delete=models.CASCADE,
        related_name="komposit_risiko",
        verbose_name="Periode KPMR",
    )
    periode_kinerja = models.OneToOneField(
        KinerjaPeriode,
        on_delete=models.CASCADE,
        related_name="komposit_risiko",
        verbose_name="Periode Kinerja",
    )
    skor_kpmr = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    skor_kinerja = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    peringkat_komposit = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="Peringkat Komposit",
    )
    catatan_review_spi = models.TextField(
        blank=True,
        null=True,
        verbose_name="Catatan Review SPI",
    )

    class Meta:
        verbose_name = "Komposit Risiko Triwulan"
        verbose_name_plural = "Komposit Risiko Triwulan"
        ordering = ["-periode_kpmr__tahun", "periode_kpmr__triwulan"]

    def __str__(self):
        return f"Komposit {self.periode_kpmr}"


class RoadmapProgram(models.Model):
    tahun = models.PositiveIntegerField(verbose_name="Tahun")
    nomor_urut = models.PositiveSmallIntegerField(verbose_name="No")
    nama_program = models.CharField(max_length=255, verbose_name="Program")
    aktif = models.BooleanField(default=True, verbose_name="Aktif")

    class Meta:
        verbose_name = "Roadmap MR — Program"
        verbose_name_plural = "Roadmap MR — Program"
        ordering = ["tahun", "nomor_urut"]
        constraints = [
            models.UniqueConstraint(
                fields=["tahun", "nomor_urut"],
                name="unik_nomor_roadmap_per_tahun",
            )
        ]

    def __str__(self):
        return f"{self.nomor_urut}. {self.nama_program}"


class RoadmapPenilaianSemester(models.Model):
    SEMESTER_CHOICES = [
        (1, "Semester 1"),
        (2, "Semester 2"),
    ]

    tahun = models.PositiveIntegerField(verbose_name="Tahun")
    semester = models.PositiveSmallIntegerField(
        choices=SEMESTER_CHOICES,
        verbose_name="Semester",
    )
    unit_bisnis = models.ForeignKey(
        Group,
        on_delete=models.PROTECT,
        related_name="roadmap_penilaian_semester",
        verbose_name="Bidang / Unit Bisnis",
    )
    program = models.ForeignKey(
        RoadmapProgram,
        on_delete=models.CASCADE,
        related_name="penilaian_semester",
        verbose_name="Program Roadmap",
    )

    nilai_kuantitas = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    nilai_kualitas = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    nilai_waktu = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    nilai_program = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    catatan = models.TextField(blank=True, null=True, verbose_name="Catatan")

    class Meta:
        verbose_name = "Roadmap MR — Penilaian Semester"
        verbose_name_plural = "Roadmap MR — Penilaian Semester"
        ordering = ["-tahun", "semester", "unit_bisnis__name", "program__nomor_urut"]
        constraints = [
            models.UniqueConstraint(
                fields=["tahun", "semester", "unit_bisnis", "program"],
                name="unik_penilaian_roadmap_per_semester_unit_program",
            )
        ]

    def __str__(self):
        return f"{self.tahun} S{self.semester} - {self.unit_bisnis.name} - {self.program}"

    def save(self, *args, **kwargs):
        self.nilai_program = (
            (self.nilai_kuantitas or Decimal("0")) +
            (self.nilai_kualitas or Decimal("0")) +
            (self.nilai_waktu or Decimal("0"))
        ) / Decimal("3")
        self.nilai_program = self.nilai_program.quantize(Decimal("0.01"))
        super().save(*args, **kwargs)