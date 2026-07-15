from decimal import Decimal, ROUND_HALF_UP
import string

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.text import Truncator, slugify


# =========================================================
# MASTER DATA
# =========================================================

class AppSetting(models.Model):
    AI_PROVIDER_OPENAI = "openai"
    AI_PROVIDER_GEMINI = "gemini"
    AI_PROVIDER_CHOICES = (
        (AI_PROVIDER_OPENAI, "OpenAI / ChatGPT"),
        (AI_PROVIDER_GEMINI, "Google Gemini API"),
        ("other", "Provider lain"),
    )

    nama_aplikasi = models.CharField(
        max_length=120,
        default="Manajemen Risiko PLN Batam",
        verbose_name="Nama Aplikasi",
    )
    subtitle_aplikasi = models.CharField(
        max_length=180,
        blank=True,
        default="Enterprise Risk Management",
        verbose_name="Subtitle Aplikasi",
    )
    logo = models.ImageField(
        upload_to="system/logo/",
        blank=True,
        null=True,
        verbose_name="Logo PLN Batam",
    )
    tampilkan_logo = models.BooleanField(
        default=True,
        verbose_name="Tampilkan Logo di Header",
    )
    warna_header = models.CharField(
        max_length=20,
        blank=True,
        default="#3f7c91",
        verbose_name="Warna Header",
        help_text="Contoh: #3f7c91",
    )
    warna_teks_header = models.CharField(
        max_length=20,
        blank=True,
        default="#ffe45c",
        verbose_name="Warna Teks Header",
        help_text="Contoh: #ffe45c",
    )
    ldap_aktif = models.BooleanField(
        default=True,
        verbose_name="LDAP Aktif",
    )
    ldap_server = models.CharField(
        max_length=255,
        blank=True,
        default="ldap://10.28.0.154",
        verbose_name="LDAP Server",
    )
    ldap_base_dn = models.CharField(
        max_length=255,
        blank=True,
        default="dc=plnbatam,dc=com",
        verbose_name="LDAP Base DN",
    )
    ldap_domain = models.CharField(
        max_length=100,
        blank=True,
        default="PLNBATAM",
        verbose_name="LDAP Domain",
    )
    ldap_user_filter = models.CharField(
        max_length=255,
        blank=True,
        default="(sAMAccountName={username})",
        verbose_name="LDAP User Search Filter",
    )
    ldap_email_domain = models.CharField(
        max_length=120,
        blank=True,
        default="plnbatam.com",
        verbose_name="Default Email Domain LDAP",
    )
    ldap_debug = models.BooleanField(
        default=False,
        verbose_name="Aktifkan Debug LDAP",
    )
    ai_aktif = models.BooleanField(
        default=False,
        verbose_name="AI Aktif",
    )
    ai_provider = models.CharField(
        max_length=30,
        choices=AI_PROVIDER_CHOICES,
        default=AI_PROVIDER_OPENAI,
        verbose_name="Provider AI",
    )
    ai_api_key = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="API Key AI",
        help_text="Simpan API key di sini hanya jika server sudah diamankan.",
    )
    ai_model = models.CharField(
        max_length=80,
        blank=True,
        default="gpt-4.1-mini",
        verbose_name="Model AI",
    )
    ai_base_url = models.URLField(
        max_length=255,
        blank=True,
        default="https://api.openai.com/v1",
        verbose_name="Base URL AI",
    )
    ai_temperature = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("0.20"),
        verbose_name="Temperature AI",
    )
    email_smtp_aktif = models.BooleanField(
        default=False,
        verbose_name="SMTP Email Aktif",
    )
    email_host = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="SMTP Host",
    )
    email_port = models.PositiveIntegerField(
        default=587,
        verbose_name="SMTP Port",
    )
    email_host_user = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="SMTP Username",
    )
    email_host_password = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="SMTP Password",
    )
    email_use_tls = models.BooleanField(
        default=True,
        verbose_name="SMTP Gunakan TLS",
    )
    email_use_ssl = models.BooleanField(
        default=False,
        verbose_name="SMTP Gunakan SSL",
    )
    default_from_email = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Default From Email",
        help_text="Contoh: PLNBATAM CSIRT <noreply@plnbatam.com>",
    )
    support_email = models.EmailField(
        blank=True,
        default="",
        verbose_name="Email Support",
    )
    footer_laporan = models.CharField(
        max_length=255,
        blank=True,
        default="PT PLN Batam - Manajemen Risiko",
        verbose_name="Footer Laporan",
    )
    diperbarui_pada = models.DateTimeField(
        auto_now=True,
        verbose_name="Diperbarui pada",
    )

    class Meta:
        verbose_name = "Pengaturan Aplikasi"
        verbose_name_plural = "PENGATURAN — Aplikasi"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return self.nama_aplikasi

    @property
    def masked_ai_api_key(self):
        if not self.ai_api_key:
            return "-"
        if len(self.ai_api_key) <= 8:
            return "********"
        return f"{self.ai_api_key[:4]}...{self.ai_api_key[-4:]}"

    @property
    def masked_email_host_password(self):
        if not self.email_host_password:
            return "-"
        if len(self.email_host_password) <= 8:
            return "********"
        return f"{self.email_host_password[:2]}...{self.email_host_password[-2:]}"


class KnowledgeBaseCategory(models.Model):
    nama = models.CharField(max_length=120, unique=True, verbose_name="Nama Kategori")
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    deskripsi = models.TextField(blank=True, default="", verbose_name="Deskripsi")
    urutan = models.PositiveIntegerField(default=1, verbose_name="Urutan")
    aktif = models.BooleanField(default=True, verbose_name="Aktif")

    class Meta:
        verbose_name = "Knowledge Base - Kategori"
        verbose_name_plural = "KNOWLEDGE BASE — Kategori"
        ordering = ["urutan", "nama"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nama)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nama


class KnowledgeBaseArticle(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_ARCHIVED = "archived"

    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
        (STATUS_ARCHIVED, "Archived"),
    )

    AUDIENCE_CHOICES = (
        ("all", "Semua Pengguna"),
        ("strategic", "Strategic Level"),
        ("management", "Management Level"),
        ("operational", "Operational Level"),
        ("evaluation", "Evaluation Level"),
        ("admin", "Administrator"),
    )

    kategori = models.ForeignKey(
        KnowledgeBaseCategory,
        on_delete=models.PROTECT,
        related_name="artikel",
        verbose_name="Kategori",
    )
    judul = models.CharField(max_length=220, verbose_name="Judul")
    slug = models.SlugField(max_length=240, unique=True, blank=True)
    ringkasan = models.TextField(blank=True, default="", verbose_name="Ringkasan")
    konten = models.TextField(verbose_name="Konten Knowledge Base")
    tags = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Tag",
        help_text="Pisahkan tag dengan koma. Contoh: ERM, Profil Risiko, Monte Carlo",
    )
    audience = models.CharField(
        max_length=20,
        choices=AUDIENCE_CHOICES,
        default="all",
        verbose_name="Target Pengguna",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        verbose_name="Status",
    )
    lampiran = models.FileField(
        upload_to="knowledge_base/",
        blank=True,
        null=True,
        verbose_name="Lampiran",
    )
    dibuat_oleh = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="knowledge_base_dibuat",
        verbose_name="Dibuat Oleh",
    )
    diperbarui_oleh = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="knowledge_base_diperbarui",
        verbose_name="Diperbarui Oleh",
    )
    dipublikasikan_pada = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Dipublikasikan Pada",
    )
    dibuat_pada = models.DateTimeField(auto_now_add=True, verbose_name="Dibuat Pada")
    diperbarui_pada = models.DateTimeField(auto_now=True, verbose_name="Diperbarui Pada")

    class Meta:
        verbose_name = "Knowledge Base - Artikel"
        verbose_name_plural = "KNOWLEDGE BASE — Artikel"
        ordering = ["kategori__urutan", "judul"]

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.judul) or "knowledge-base"
            slug = base_slug
            counter = 2
            while KnowledgeBaseArticle.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.judul


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


class RiwayatJabatanUser(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="riwayat_jabatan",
        verbose_name="User",
    )
    jabatan = models.CharField(max_length=255, verbose_name="Jabatan")
    tanggal_mulai = models.DateField(verbose_name="Tanggal Mulai")
    tanggal_selesai = models.DateField(null=True, blank=True, verbose_name="Tanggal Selesai")

    class Meta:
        verbose_name = "Riwayat Jabatan User"
        verbose_name_plural = "MASTER — Riwayat Jabatan User"
        ordering = ["user", "-tanggal_mulai"]

    def __str__(self):
        akhir = self.tanggal_selesai or "NOW"
        return f"{self.user} - {self.jabatan} ({self.tanggal_mulai} s.d. {akhir})"

# =========================================================
# TEMPLATE KONTRAK MANAJEMEN
# =========================================================

class TemplateKontrakManajemen(models.Model):
    tahun = models.IntegerField(unique=True)
    nama = models.CharField(max_length=200)

    class Meta:
        verbose_name = "Template Kontrak Manajemen"
        verbose_name_plural = "Template Kontrak Manajemen"
        ordering = ["-tahun"]

    def __str__(self):
        return f"{self.nama} ({self.tahun})"


class TemplateBagianKM(models.Model):
    template = models.ForeignKey(
        TemplateKontrakManajemen,
        on_delete=models.CASCADE,
        related_name="bagian_list"
    )

    kode_bagian = models.CharField(max_length=10)
    nama_bagian = models.CharField(max_length=255)

    class Meta:
        verbose_name = "Bagian Template KM"
        verbose_name_plural = "Bagian Template KM"
        ordering = ["kode_bagian"]

    def __str__(self):
        return f"{self.kode_bagian}. {self.nama_bagian}"


class TemplateItemKM(models.Model):
    bagian = models.ForeignKey(
        TemplateBagianKM,
        on_delete=models.CASCADE,
        related_name="item_list"
    )

    no_urut = models.PositiveIntegerField()

    indikator_kinerja_kunci = models.TextField()
    formula = models.TextField(blank=True, null=True)
    satuan = models.CharField(max_length=100, blank=True, null=True)
    target = models.CharField(max_length=255, blank=True, null=True)
    bobot = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Item Template KM"
        verbose_name_plural = "Item Template KM"
        ordering = ["no_urut"]

    def __str__(self):
        return f"{self.no_urut}. {self.indikator_kinerja_kunci}"

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
    
    template = models.ForeignKey(
        "MasterTemplateKM",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="kontrak_list",
    )

    pihak_pertama = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="km_pihak_pertama"
    )

    pihak_kedua = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="km_pihak_kedua"
    )

    tanggal_kontrak = models.DateField(null=True, blank=True, verbose_name="Tanggal Kontrak")

    pihak_pertama = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="km_pihak_pertama",
        verbose_name="Pihak Pertama",
    )

    pihak_kedua = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="km_pihak_kedua",
        verbose_name="Pihak Kedua",
    )

class MasterTemplateKM(models.Model):
    tahun = models.IntegerField(unique=True)
    nama = models.CharField(max_length=200)

    class Meta:
        verbose_name = "MASTER — Template KM"
        verbose_name_plural = "MASTER — Template KM"
        ordering = ["-tahun"]

    def __str__(self):
        return f"{self.nama} ({self.tahun})"


class MasterBagianKM(models.Model):
    template = models.ForeignKey(
        MasterTemplateKM,
        on_delete=models.CASCADE,
        related_name="bagian_list",
    )
    kode_bagian = models.CharField(max_length=10)
    nama_bagian = models.CharField(max_length=255)
    urutan = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "MASTER — Bagian KM"
        verbose_name_plural = "MASTER — Bagian KM"
        ordering = ["template__tahun", "urutan", "kode_bagian"]

    def __str__(self):
        return f"{self.kode_bagian}. {self.nama_bagian}"


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

    POLARITAS_CHOICES = (
        ('positif', 'Positif'),
        ('negatif', 'Negatif'),
    )

    kontrak = models.ForeignKey(
        KontrakManajemen,
        on_delete=models.CASCADE
    )

    bagian = models.ForeignKey(
        BagianKontrakManajemen,
        on_delete=models.CASCADE,
        related_name="items",
        null=True,
        blank=True,
    )

    master_bagian = models.ForeignKey(
        MasterBagianKM,
        on_delete=models.CASCADE
    )

    no_urut = models.IntegerField(default=0)

    indikator_kinerja_kunci = models.TextField()

    formula = models.TextField(blank=True, null=True)

    satuan = models.CharField(max_length=100, blank=True, null=True)

    bobot = models.FloatField(default=0)

    target = models.CharField(max_length=100, blank=True, null=True)

    polaritas = models.CharField(
        max_length=10,
        choices=POLARITAS_CHOICES,
        default='positif'
    )

    class Meta:
        verbose_name = "Item Kontrak"
        verbose_name_plural = "TRANSAKSI UNIT — Item Kontrak"
        ordering = ["kontrak", "master_bagian__urutan", "no_urut"]

        constraints = [
            models.UniqueConstraint(
                fields=["kontrak", "master_bagian", "no_urut"],
                name="unique_km_item_per_bagian"
            )
        ]

    def __str__(self):
        bagian = self.master_bagian.kode_bagian if self.master_bagian_id else "-"
        indikator = self.indikator_kinerja_kunci or "-"
        return f"{self.kontrak} | {bagian}.{self.no_urut} - {indikator}"

# =========================================================
# RKAP (SIMPLIFIED FOR RISK APP)
# =========================================================

class RKAPItem(models.Model):
    PERIODE_CHOICES = [
        ("Tahunan", "Tahunan"),
        ("Bulanan", "Bulanan"),
        ("Triwulan", "Triwulan"),
        ("Lampiran", "Lampiran"),
    ]

    tahun = models.PositiveIntegerField(verbose_name="Tahun")

    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="Induk RKAP",
        help_text="Gunakan untuk detail bulanan atau rincian dari item RKAP utama.",
    )

    kode = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="Kode RKAP",
    )

    sasaran = models.CharField(
        max_length=255,
        verbose_name="Sasaran RKAP",
    )

    indikator = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Indikator",
    )

    kategori = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="Kategori",
    )

    subkategori = models.CharField(
        max_length=160,
        blank=True,
        default="",
        verbose_name="Subkategori",
    )

    periode = models.CharField(
        max_length=20,
        choices=PERIODE_CHOICES,
        default="Tahunan",
        verbose_name="Periode",
    )

    bulan = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="Bulan",
        help_text="Isi 1-12 jika item ini adalah target bulanan.",
    )

    target = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Target",
    )

    satuan = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="Satuan",
    )

    nilai_audited_2024 = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Audited 2024",
    )

    nilai_unaudited_2025 = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Unaudited 2025",
    )

    asumsi = models.TextField(
        blank=True,
        null=True,
        verbose_name="Asumsi / Driver RKAP",
    )

    unit_penanggung_jawab = models.ForeignKey(
        Group,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rkap_items",
        verbose_name="Unit Penanggung Jawab",
    )

    sumber_dokumen = models.CharField(
        max_length=180,
        blank=True,
        default="",
        verbose_name="Sumber Dokumen",
    )

    halaman_sumber = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Halaman Sumber",
    )

    urutan = models.PositiveIntegerField(
        default=0,
        verbose_name="Urutan",
    )

    aktif = models.BooleanField(default=True, verbose_name="Aktif")

    class Meta:
        verbose_name = "RKAP — Item"
        verbose_name_plural = "RKAP — Item"
        ordering = ["-tahun", "kategori", "subkategori", "urutan", "kode", "sasaran"]
        constraints = [
            models.UniqueConstraint(
                fields=["tahun", "kode", "sasaran"],
                name="unik_rkap_item_per_tahun_kode_sasaran",
            )
        ]

    def __str__(self):
        label = self.kode or "RKAP"
        return f"{label} - {self.sasaran} ({self.tahun})"

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
        verbose_name="Deadline Pengajuan Profil Risiko",
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

    penandatangan_laporan_km = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rkm_laporan_km_ditandatangani",
        verbose_name="Penandatangan Laporan KM",
    )

    penandatangan_laporan_rkm = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rkm_laporan_rkm_ditandatangani",
        verbose_name="Penandatangan Laporan RKM",
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
    def is_approved(self):
        return self.status == "Final" or self.status_pengajuan == "Disetujui"

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

        if self.status == "Final":
            self.status_pengajuan = "Disetujui"
        elif self.status_pengajuan == "Disetujui":
            self.status = "Final"
        elif self.deadline_pengajuan:
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
        used_numbers = set(
            RKMItem.objects
            .filter(summary=self)
            .values_list("no_item", flat=True)
        )
        no = max(used_numbers, default=0) + 1

        for km_item in km_items:
            existing_item = RKMItem.objects.filter(summary=self, km_item=km_item).first()
            if existing_item:
                continue

            while no in used_numbers:
                no += 1

            _, created = RKMItem.objects.get_or_create(
                summary=self,
                km_item=km_item,
                defaults={
                    "no_item": no,
                    "sasaran": km_item.indikator_kinerja_kunci,
                    "kpi_indikator": km_item.indikator_kinerja_kunci,
                    "kpi_satuan": km_item.satuan,
                    "kpi_target": km_item.target,
                }
            )
            if created:
                created_count += 1
                used_numbers.add(no)
                no += 1

        return created_count
    
class RKMItem(models.Model):
    KATEGORI_RKM_CHOICES = [
        ("A", "A - Keuangan"),
        ("B", "B - Pelanggan"),
        ("C", "C - Bisnis Proses Internal"),
        ("D", "D - Pengembangan dan Lingkungan"),
        ("E", "E - Pengembangan Talenta"),
        ("F", "F - Compliance"),
    ]

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

    kategori_rkm = models.CharField(
        max_length=1,
        choices=KATEGORI_RKM_CHOICES,
        blank=True,
        null=True,
        verbose_name="Kategori RKM",
    )
    sasaran = models.TextField(blank=True, null=True, verbose_name="Sasaran / KPI")
    kpi_indikator = models.TextField(
        blank=True,
        null=True,
        verbose_name="KPI - Indikator",
    )
    kpi_satuan = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="KPI - Satuan",
    )
    kpi_target = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="KPI - Target",
    )
    inisiatif_strategis = models.TextField(
        blank=True,
        null=True,
        verbose_name="Inisiatif Strategis",
    )
    program_kerja_utama = models.TextField(
        blank=True,
        null=True,
        verbose_name="Program Kerja Utama",
    )
    risiko = models.TextField(blank=True, null=True, verbose_name="Risiko")
    mitigasi_risiko = models.TextField(
        blank=True,
        null=True,
        verbose_name="Mitigasi Risiko",
    )
    rencana_aksi = models.TextField(
        blank=True,
        null=True,
        verbose_name="Rencana Aksi",
    )
    anggaran_rp_ribu = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name="Anggaran (Rp Ribu)",
    )
    target_akumulasi = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Target Akumulasi",
    )
    target_akumulasi_satuan = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Satuan Target Akumulasi",
    )
    target_januari = models.CharField(max_length=255, blank=True, null=True, verbose_name="Target Januari")
    target_februari = models.CharField(max_length=255, blank=True, null=True, verbose_name="Target Februari")
    target_maret = models.CharField(max_length=255, blank=True, null=True, verbose_name="Target Maret")
    target_april = models.CharField(max_length=255, blank=True, null=True, verbose_name="Target April")
    target_mei = models.CharField(max_length=255, blank=True, null=True, verbose_name="Target Mei")
    target_juni = models.CharField(max_length=255, blank=True, null=True, verbose_name="Target Juni")
    target_juli = models.CharField(max_length=255, blank=True, null=True, verbose_name="Target Juli")
    target_agustus = models.CharField(max_length=255, blank=True, null=True, verbose_name="Target Agustus")
    target_september = models.CharField(max_length=255, blank=True, null=True, verbose_name="Target September")
    target_oktober = models.CharField(max_length=255, blank=True, null=True, verbose_name="Target Oktober")
    target_november = models.CharField(max_length=255, blank=True, null=True, verbose_name="Target November")
    target_desember = models.CharField(max_length=255, blank=True, null=True, verbose_name="Target Desember")
    realisasi_januari = models.CharField(max_length=255, blank=True, null=True, verbose_name="Realisasi Januari")
    realisasi_februari = models.CharField(max_length=255, blank=True, null=True, verbose_name="Realisasi Februari")
    realisasi_maret = models.CharField(max_length=255, blank=True, null=True, verbose_name="Realisasi Maret")
    realisasi_april = models.CharField(max_length=255, blank=True, null=True, verbose_name="Realisasi April")
    realisasi_mei = models.CharField(max_length=255, blank=True, null=True, verbose_name="Realisasi Mei")
    realisasi_juni = models.CharField(max_length=255, blank=True, null=True, verbose_name="Realisasi Juni")
    realisasi_juli = models.CharField(max_length=255, blank=True, null=True, verbose_name="Realisasi Juli")
    realisasi_agustus = models.CharField(max_length=255, blank=True, null=True, verbose_name="Realisasi Agustus")
    realisasi_september = models.CharField(max_length=255, blank=True, null=True, verbose_name="Realisasi September")
    realisasi_oktober = models.CharField(max_length=255, blank=True, null=True, verbose_name="Realisasi Oktober")
    realisasi_november = models.CharField(max_length=255, blank=True, null=True, verbose_name="Realisasi November")
    realisasi_desember = models.CharField(max_length=255, blank=True, null=True, verbose_name="Realisasi Desember")
    jumlah_realisasi = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Jumlah Realisasi",
    )
    persen_capaian = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name="% Capaian",
    )
    realisasi_anggaran = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name="Realisasi Anggaran",
    )
    pic_rkm = models.CharField(max_length=255, blank=True, null=True, verbose_name="PIC")
    hasil_analisa_program_kerja = models.TextField(
        blank=True,
        null=True,
        verbose_name="Hasil Analisa Program Kerja",
    )
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

    def _month_target_realisasi_fields(self):
        month_fields = {
            1: ("target_januari", "realisasi_januari"),
            2: ("target_februari", "realisasi_februari"),
            3: ("target_maret", "realisasi_maret"),
            4: ("target_april", "realisasi_april"),
            5: ("target_mei", "realisasi_mei"),
            6: ("target_juni", "realisasi_juni"),
            7: ("target_juli", "realisasi_juli"),
            8: ("target_agustus", "realisasi_agustus"),
            9: ("target_september", "realisasi_september"),
            10: ("target_oktober", "realisasi_oktober"),
            11: ("target_november", "realisasi_november"),
            12: ("target_desember", "realisasi_desember"),
        }
        return month_fields.get(getattr(self.summary, "bulan", None))

    @staticmethod
    def _parse_decimal_value(value):
        if value in (None, ""):
            return None
        cleaned = str(value).strip().replace("%", "")
        if not cleaned:
            return None
        if "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", ".")
        try:
            return Decimal(cleaned)
        except Exception:
            return None

    def sync_monthly_result(self):
        fields = self._month_target_realisasi_fields()
        if not fields:
            return
        target_field, realisasi_field = fields
        target = getattr(self, target_field, None)
        realisasi = getattr(self, realisasi_field, None)
        self.jumlah_realisasi = realisasi or None

        target_value = self._parse_decimal_value(target)
        realisasi_value = self._parse_decimal_value(realisasi)
        self.persen_capaian = None
        if target_value is None or realisasi_value is None or target_value == 0:
            return

        if self.km_item_id and self.km_item.polaritas == "negatif":
            if realisasi_value == 0:
                return
            capaian = target_value / realisasi_value * Decimal("100")
        else:
            capaian = realisasi_value / target_value * Decimal("100")
        self.persen_capaian = capaian.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def save(self, *args, **kwargs):
        if self.km_item:
            if not self.sasaran:
                self.sasaran = self.km_item.indikator_kinerja_kunci
            if not self.kpi_indikator:
                self.kpi_indikator = self.km_item.indikator_kinerja_kunci
            if not self.kpi_satuan:
                self.kpi_satuan = self.km_item.satuan
            if not self.kpi_target:
                self.kpi_target = self.km_item.target
        self.sync_monthly_result()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"jumlah_realisasi", "persen_capaian"}
        super().save(*args, **kwargs)

# =========================================================
# PROFIL RISIKO UNIT / BIDANG
# =========================================================

class ReAssessmentSummary(models.Model):
    judul = models.CharField(max_length=200, verbose_name="Judul Profil Risiko")
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
        verbose_name_plural = "TRANSAKSI UNIT - Profil Risiko Bidang/Unit Bisnis"
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
        verbose_name_plural = "TRANSAKSI UNIT - Item Risiko Bidang/Unit Bisnis"
        ordering = ["summary", "no_item", "no_risiko"]
        constraints = [
            models.UniqueConstraint(
                fields=["summary", "no_item", "no_risiko"],
                name="unik_reassessment_item_risiko_per_summary",
            ),
        ]

    def clean(self):
        if getattr(self, "km_item_id", None) and self.summary_id:
            if self.km_item.kontrak_id != self.summary.kontrak_manajemen_id:
                raise ValidationError(
                    "KM Item harus berasal dari Kontrak Manajemen yang sama dengan Summary."
                )

        if self.summary and self.summary.rkm:
            if self.summary.rkm.unit_bisnis_id != self.unit_bisnis_id:
                raise ValidationError(
                    "Unit bisnis Profil Risiko harus sama dengan unit bisnis RKM."
                )

            if self.summary.rkm.kontrak_manajemen_id != self.summary.kontrak_manajemen_id:
                raise ValidationError(
                    "Kontrak Manajemen Profil Risiko harus sama dengan Kontrak Manajemen pada RKM."
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
        verbose_name="Profil Risiko Bidang/Unit Bisnis",
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
            return "Dihitung otomatis dari Profil Risiko"

        return "; ".join(notes)

    def generate_items_from_reassessment(self):
        reassessment_items = self.reassessment.item.all().order_by(
            "no_item",
            "no_risiko",
            "no_penyebab_risiko",
            "id",
        )
        created_or_updated_count = 0

        self.item.all().delete()

        for sequence, reassessment_item in enumerate(reassessment_items, start=1):
            KPMRItem.objects.create(
                summary=self,
                reassessment_item=reassessment_item,
                no_item=sequence,
                perlakuan_risiko=reassessment_item.rencana_perlakuan_risiko or "",
                bukti=reassessment_item.output_perlakuan_risiko or "",
                nilai_kpmr=self._calculate_auto_score(reassessment_item),
                status_kpmr=self._calculate_auto_status(reassessment_item),
                catatan=self._build_auto_note(reassessment_item),
            )
            created_or_updated_count += 1

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
        verbose_name="Item Risiko Bidang/Unit Bisnis",
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


class RiskManagementReview(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_REVIEWED = "reviewed"
    STATUS_FINAL = "final"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_REVIEWED, "Reviewed"),
        (STATUS_FINAL, "Final"),
    ]

    title = models.CharField(max_length=255, verbose_name="Judul Review")
    tahun = models.PositiveIntegerField(verbose_name="Tahun")
    unit_bisnis = models.ForeignKey(
        Group,
        on_delete=models.PROTECT,
        related_name="risk_management_reviews",
        verbose_name="Bidang / Unit Bisnis",
    )
    kontrak_manajemen = models.ForeignKey(
        "KontrakManajemen",
        on_delete=models.PROTECT,
        related_name="risk_management_reviews",
        verbose_name="Kontrak Manajemen",
    )
    rkm = models.ForeignKey(
        "RKMSummary",
        on_delete=models.PROTECT,
        related_name="risk_management_reviews",
        verbose_name="RKM",
    )
    profil_risiko = models.ForeignKey(
        "ReAssessmentSummary",
        on_delete=models.PROTECT,
        related_name="risk_management_reviews",
        verbose_name="Profil Risiko",
    )
    kpmr = models.ForeignKey(
        "KPMRSummary",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="risk_management_reviews",
        verbose_name="KPMR",
    )
    review_date = models.DateField(default=timezone.localdate, verbose_name="Tanggal Review")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    review_summary = models.TextField(
        blank=True,
        verbose_name="Ringkasan Hasil Review Sub Bidang Manajemen Risiko",
    )
    km_notes = models.TextField(blank=True, verbose_name="Catatan Review KM")
    rkm_notes = models.TextField(blank=True, verbose_name="Catatan Review RKM")
    profil_risiko_notes = models.TextField(blank=True, verbose_name="Catatan Review Profil Risiko")
    kpmr_notes = models.TextField(blank=True, verbose_name="Catatan Review KPMR")
    recommendation = models.TextField(blank=True, verbose_name="Rekomendasi / Tindak Lanjut")
    pairing_officer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="risk_reviews_as_pairing_officer",
        verbose_name="Pairing Officer",
    )
    man_risk = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="risk_reviews_as_man_risk",
        verbose_name="MAN RISK",
    )
    vp_mrk = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="risk_reviews_as_vp_mrk",
        verbose_name="VP MRK",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Dibuat Pada")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Diubah Pada")

    class Meta:
        verbose_name = "Review Manajemen Risiko"
        verbose_name_plural = "REVIEW — Manajemen Risiko"
        ordering = ["-tahun", "-review_date", "unit_bisnis__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["profil_risiko", "rkm"],
                name="unik_review_mr_per_profil_rkm",
            )
        ]

    def __str__(self):
        return self.title

    def _active_pairing_officer(self):
        if not self.unit_bisnis_id:
            return None
        assignment = (
            PenugasanUnitBisnis.objects
            .filter(
                unit_bisnis=self.unit_bisnis,
                peran=PenugasanUnitBisnis.ROLE_PAIRING_OFFICER,
                aktif=True,
            )
            .select_related("user")
            .first()
        )
        return assignment.user if assignment else None

    def clean(self):
        errors = {}
        if self.profil_risiko_id:
            if self.unit_bisnis_id and self.profil_risiko.unit_bisnis_id != self.unit_bisnis_id:
                errors["profil_risiko"] = "Profil Risiko harus berasal dari unit bisnis yang sama."
            if self.kontrak_manajemen_id and self.profil_risiko.kontrak_manajemen_id != self.kontrak_manajemen_id:
                errors["profil_risiko"] = "Profil Risiko harus terkait Kontrak Manajemen yang sama."
        if self.rkm_id:
            if self.unit_bisnis_id and self.rkm.unit_bisnis_id != self.unit_bisnis_id:
                errors["rkm"] = "RKM harus berasal dari unit bisnis yang sama."
            if self.kontrak_manajemen_id and self.rkm.kontrak_manajemen_id != self.kontrak_manajemen_id:
                errors["rkm"] = "RKM harus terkait Kontrak Manajemen yang sama."
        if self.kpmr_id and self.profil_risiko_id and self.kpmr.reassessment_id != self.profil_risiko_id:
            errors["kpmr"] = "KPMR harus dihitung dari Profil Risiko yang sama."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.profil_risiko_id:
            self.unit_bisnis = self.profil_risiko.unit_bisnis
            self.kontrak_manajemen = self.profil_risiko.kontrak_manajemen
            if not self.tahun:
                self.tahun = self.profil_risiko.tahun
            if not self.rkm_id and self.profil_risiko.rkm_id:
                self.rkm = self.profil_risiko.rkm
            if not self.title:
                self.title = f"Review MR {self.unit_bisnis.name} {self.tahun}"
        if self.rkm_id and not self.tahun:
            self.tahun = self.rkm.tahun
        if not self.pairing_officer_id:
            self.pairing_officer = self._active_pairing_officer()
        self.full_clean()
        super().save(*args, **kwargs)


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

    rkap_item = models.ForeignKey(
        "RKAPItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="risiko_korporat_items",
        verbose_name="Sumber Target RKAP",
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

    def get_peristiwa_risiko_text(self):
        return self.peristiwa_risiko or "Peristiwa risiko belum diisi"

    @property
    def short_label(self):
        nomor = self.no_item or self.no_risiko or self.pk or "-"
        peristiwa = Truncator(self.get_peristiwa_risiko_text()).chars(110)
        return f"#{nomor} - {peristiwa}"

    @property
    def display_label(self):
        profil_obj = getattr(self, "summary", None)
        profil = str(profil_obj) if profil_obj else "Profil risiko korporat belum dipilih"
        return f"{self.short_label} | {profil}"

    def get_display_label(self):
        return self.display_label

    def __str__(self):
        return self.display_label


class ProfilRisikoKorporatPenyebab(models.Model):
    risiko_korporat = models.ForeignKey(
        "ProfilRisikoKorporatItem",
        on_delete=models.CASCADE,
        related_name="daftar_penyebab",
        verbose_name="Risiko Korporat",
    ) 

    urutan = models.PositiveIntegerField(default=1, verbose_name="Urutan")

    pemilik_risiko = models.ForeignKey(
        Group,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="pemilik_penyebab_risiko_korporat",
        verbose_name="Pemilik Risiko",
    )

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
        verbose_name="Risiko Bidang / Unit",
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
