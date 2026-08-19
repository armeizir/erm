from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class RCMType(models.TextChoices):
    TLC = "TLC", "Transaction Level Control (TLC)"
    ELC = "ELC", "Entity Level Control (ELC)"
    ITGC = "ITGC", "IT General Control (ITGC)"


class ICoFRPeriod(TimeStampedModel):
    year = models.PositiveIntegerField(verbose_name="Tahun")
    name = models.CharField(max_length=120, verbose_name="Nama Periode")
    rcm_type = models.CharField(max_length=10, choices=RCMType.choices, verbose_name="Jenis RCM")
    start_date = models.DateField(null=True, blank=True, verbose_name="Periode Awal")
    end_date = models.DateField(null=True, blank=True, verbose_name="Periode Akhir")
    is_active = models.BooleanField(default=True, verbose_name="Aktif")

    class Meta:
        db_table = "icofr_period"
        verbose_name = "Periode ICoFR"
        verbose_name_plural = "ICoFR — Periode"
        ordering = ("-year", "rcm_type", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("year", "name", "rcm_type"),
                name="uniq_icofr_period_year_name_type",
            )
        ]

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "Periode akhir tidak boleh sebelum periode awal."})

    def __str__(self):
        return f"{self.name} / {self.year} — {self.rcm_type}"


class RCMSet(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        FINAL = "FINAL", "Final / Locked"
        ARCHIVED = "ARCHIVED", "Archived"

    rcm_type = models.CharField(max_length=10, choices=RCMType.choices, verbose_name="Jenis RCM")
    version = models.CharField(max_length=80, verbose_name="Versi")
    entity_name = models.CharField(max_length=255, blank=True, verbose_name="Entitas")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    source_filename = models.CharField(max_length=255, blank=True)
    source_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    source_row_count = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="icofr_rcm_imports",
    )
    imported_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="icofr_rcm_finalizations",
    )
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "icofr_rcm_set"
        verbose_name = "RCM"
        verbose_name_plural = "ICoFR — RCM"
        ordering = ("rcm_type", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("rcm_type", "version"),
                name="uniq_icofr_rcm_type_version",
            )
        ]

    @property
    def is_locked(self):
        return self.status != self.Status.DRAFT

    def finalize(self, user=None):
        if self.status == self.Status.FINAL:
            return
        if not self.entries.exists():
            raise ValidationError("RCM belum mempunyai entry dan tidak dapat difinalisasi.")
        self.status = self.Status.FINAL
        self.finalized_at = timezone.now()
        self.finalized_by = user
        self.save(update_fields=("status", "finalized_at", "finalized_by", "updated_at"))

    def __str__(self):
        return f"{self.rcm_type} — {self.version}"


class RCMRisk(TimeStampedModel):
    rcm_set = models.ForeignKey(RCMSet, on_delete=models.CASCADE, related_name="risks")
    reference = models.CharField(max_length=80, verbose_name="Referensi Risiko")
    description = models.TextField(blank=True, verbose_name="Deskripsi Risiko")
    coso_objective = models.CharField(max_length=160, blank=True, verbose_name="Tujuan COSO")
    coso_component = models.CharField(max_length=160, blank=True, verbose_name="Komponen COSO")
    fraud_risk = models.CharField(max_length=40, blank=True, verbose_name="Risiko Kecurangan")
    impact = models.CharField(max_length=100, blank=True, verbose_name="Dampak")
    likelihood = models.CharField(max_length=100, blank=True, verbose_name="Kemungkinan Terjadi")
    risk_level = models.CharField(max_length=100, blank=True, verbose_name="Tingkat Risiko")
    coso_element = models.TextField(blank=True, verbose_name="Elemen COSO (ELC)")
    control_area = models.CharField(max_length=255, blank=True, verbose_name="Area Kontrol (ITGC)")
    control_sub_area = models.CharField(max_length=255, blank=True, verbose_name="Sub Area Kontrol (ITGC)")

    class Meta:
        db_table = "icofr_rcm_risk"
        verbose_name = "Risiko RCM"
        verbose_name_plural = "ICoFR — Risiko RCM"
        ordering = ("rcm_set", "reference")
        constraints = [
            models.UniqueConstraint(
                fields=("rcm_set", "reference"),
                name="uniq_icofr_risk_reference_per_set",
            )
        ]
        indexes = [models.Index(fields=("rcm_set", "reference"))]

    def clean(self):
        super().clean()
        if self.rcm_set_id and self.rcm_set.is_locked:
            raise ValidationError("RCM sudah final/locked; definisi risiko tidak dapat diubah.")

    def __str__(self):
        return f"{self.reference} — {self.description[:80]}"


class RCMControl(TimeStampedModel):
    rcm_set = models.ForeignKey(RCMSet, on_delete=models.CASCADE, related_name="controls")
    reference = models.CharField(max_length=80, verbose_name="Referensi Kontrol")
    objective = models.TextField(blank=True, verbose_name="Tujuan Kontrol")
    description = models.TextField(blank=True, verbose_name="Deskripsi Kontrol")
    control_type = models.CharField(max_length=120, blank=True, verbose_name="Jenis Kontrol")
    is_key_control = models.BooleanField(null=True, blank=True, verbose_name="Kontrol Utama")
    anti_fraud = models.BooleanField(null=True, blank=True, verbose_name="Anti Kecurangan")
    supporting_application = models.CharField(max_length=255, blank=True, verbose_name="Aplikasi Pendukung")

    class Meta:
        db_table = "icofr_rcm_control"
        verbose_name = "Kontrol RCM"
        verbose_name_plural = "ICoFR — Kontrol RCM"
        ordering = ("rcm_set", "reference")
        constraints = [
            models.UniqueConstraint(
                fields=("rcm_set", "reference"),
                name="uniq_icofr_control_reference_per_set",
            )
        ]
        indexes = [models.Index(fields=("rcm_set", "reference"))]

    def clean(self):
        super().clean()
        if self.rcm_set_id and self.rcm_set.is_locked:
            raise ValidationError("RCM sudah final/locked; definisi kontrol tidak dapat diubah.")

    def __str__(self):
        return f"{self.reference} — {self.objective[:80]}"


class RCMEntry(TimeStampedModel):
    rcm_set = models.ForeignKey(RCMSet, on_delete=models.CASCADE, related_name="entries")
    risk = models.ForeignKey(RCMRisk, on_delete=models.PROTECT, related_name="entries")
    control = models.ForeignKey(RCMControl, on_delete=models.PROTECT, related_name="entries")

    entity_name = models.CharField(max_length=255, blank=True, verbose_name="Entitas")
    subprocess_number = models.CharField(max_length=80, blank=True, verbose_name="No. Sub Proses")
    subprocess_description = models.TextField(blank=True, verbose_name="Deskripsi Sub Proses")
    account_description = models.TextField(blank=True, verbose_name="Deskripsi Akun")
    assertions_raw = models.TextField(blank=True, verbose_name="Asersi")

    location = models.CharField(max_length=120, blank=True, verbose_name="Lokasi")
    location_description = models.TextField(blank=True, verbose_name="Deskripsi Lokasi")
    frequency = models.CharField(max_length=120, blank=True, verbose_name="Frekuensi")
    preparer_position = models.CharField(max_length=255, blank=True, verbose_name="Control Preparer")
    reviewer_position = models.CharField(max_length=255, blank=True, verbose_name="Control Reviewer")
    compensating_control = models.TextField(blank=True, verbose_name="Kontrol Kompensasi")
    segment = models.CharField(max_length=160, blank=True, verbose_name="Segmen")

    source_row_number = models.PositiveIntegerField(verbose_name="Baris Sumber")
    source_fingerprint = models.CharField(max_length=64, blank=True, db_index=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "icofr_rcm_entry"
        verbose_name = "Entry RCM"
        verbose_name_plural = "ICoFR — Entry RCM"
        ordering = ("rcm_set", "source_row_number")
        constraints = [
            models.UniqueConstraint(
                fields=("rcm_set", "source_row_number"),
                name="uniq_icofr_entry_source_row_per_set",
            )
        ]
        indexes = [
            models.Index(fields=("rcm_set", "segment")),
            models.Index(fields=("rcm_set", "preparer_position")),
            models.Index(fields=("rcm_set", "reviewer_position")),
        ]

    def clean(self):
        super().clean()
        if self.rcm_set_id and self.rcm_set.is_locked:
            raise ValidationError("RCM sudah final/locked; entry tidak dapat ditambah atau diubah.")
        if self.risk_id and self.risk.rcm_set_id != self.rcm_set_id:
            raise ValidationError({"risk": "Risiko harus berasal dari RCM yang sama."})
        if self.control_id and self.control.rcm_set_id != self.rcm_set_id:
            raise ValidationError({"control": "Kontrol harus berasal dari RCM yang sama."})

    def __str__(self):
        return f"{self.rcm_set.rcm_type} {self.risk.reference} / {self.control.reference}"


class OrderedEntryText(TimeStampedModel):
    entry = models.ForeignKey(RCMEntry, on_delete=models.CASCADE)
    sequence = models.PositiveIntegerField(default=1)
    text = models.TextField()

    class Meta:
        abstract = True
        ordering = ("entry", "sequence", "id")


class RCMEntryAssertion(OrderedEntryText):
    entry = models.ForeignKey(RCMEntry, on_delete=models.CASCADE, related_name="assertions")

    class Meta(OrderedEntryText.Meta):
        db_table = "icofr_rcm_entry_assertion"
        verbose_name = "Asersi Entry"
        verbose_name_plural = "Asersi Entry"


class RCMControlAttribute(OrderedEntryText):
    entry = models.ForeignKey(RCMEntry, on_delete=models.CASCADE, related_name="control_attributes")

    class Meta(OrderedEntryText.Meta):
        db_table = "icofr_rcm_control_attribute"
        verbose_name = "Atribut Kontrol"
        verbose_name_plural = "Atribut Kontrol"


class RCMSupportingDocument(OrderedEntryText):
    entry = models.ForeignKey(RCMEntry, on_delete=models.CASCADE, related_name="supporting_documents")

    class Meta(OrderedEntryText.Meta):
        db_table = "icofr_rcm_supporting_document"
        verbose_name = "Dokumen Pendukung"
        verbose_name_plural = "Dokumen Pendukung"


class RCMMapping(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Belum Dipetakan"
        PARTIAL = "PARTIAL", "Sebagian"
        MAPPED = "MAPPED", "Terpetakan"
        FAILED = "FAILED", "Gagal Mapping"
        MANUAL = "MANUAL", "Mapping Manual"

    entry = models.OneToOneField(RCMEntry, on_delete=models.CASCADE, related_name="mapping")
    preparer_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="icofr_preparer_mappings",
    )
    reviewer_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="icofr_reviewer_mappings",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    mapping_note = models.TextField(blank=True)
    mapped_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="icofr_mapping_actions",
    )
    mapped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "icofr_rcm_mapping"
        verbose_name = "Mapping RCM"
        verbose_name_plural = "ICoFR — Mapping RCM"
        ordering = ("entry__rcm_set", "entry__source_row_number")

    def refresh_status(self, *, manual=False):
        if self.preparer_user_id and self.reviewer_user_id:
            self.status = self.Status.MANUAL if manual else self.Status.MAPPED
        elif self.preparer_user_id or self.reviewer_user_id:
            self.status = self.Status.PARTIAL
        else:
            self.status = self.Status.FAILED
        self.mapped_at = timezone.now()

    def __str__(self):
        return f"{self.entry} — {self.get_status_display()}"


class RCMImportBatch(TimeStampedModel):
    class Status(models.TextChoices):
        UPLOADED = "UPLOADED", "Uploaded"
        VALIDATED = "VALIDATED", "Validated"
        IMPORTED = "IMPORTED", "Imported"
        FAILED = "FAILED", "Failed"

    upload = models.FileField(upload_to="icofr/import_staging/%Y/%m/", verbose_name="File RCM")
    original_filename = models.CharField(max_length=255)
    source_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    detected_type = models.CharField(max_length=10, choices=RCMType.choices, blank=True)
    detected_version = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED)
    row_count = models.PositiveIntegerField(default=0)
    summary = models.JSONField(default=dict, blank=True)
    validation_errors = models.JSONField(default=list, blank=True)
    validation_warnings = models.JSONField(default=list, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="icofr_import_batches",
    )
    imported_rcm = models.ForeignKey(
        RCMSet,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="import_batches",
    )

    class Meta:
        db_table = "icofr_rcm_import_batch"
        verbose_name = "Import RCM"
        verbose_name_plural = "ICoFR — Riwayat Import RCM"
        ordering = ("-created_at",)

    @property
    def can_import(self):
        return self.status == self.Status.VALIDATED and not self.validation_errors and not self.imported_rcm_id

    def __str__(self):
        label = self.detected_type or "RCM"
        version = self.detected_version or "?"
        return f"{label} {version} — {self.original_filename}"


# =============================================================================
# Phase 2 — Penjadwalan, Distribusi, Kuesioner, dan fondasi CSA Line 1
# =============================================================================


class ICoFRStage(models.TextChoices):
    QUESTIONNAIRE = "QUESTIONNAIRE", "Kuesioner"
    LINE1 = "LINE1", "Line 1 — CSA"
    LINE2 = "LINE2", "Line 2 — TOD"
    LINE3 = "LINE3", "Line 3 — TOE"


class ICoFRSchedule(TimeStampedModel):
    """Jendela pelaksanaan ICoFR per RCM/periode.

    Manual ICoFR memperbolehkan setiap tahap diaktifkan secara bertahap. Karena itu
    satu schedule menyimpan empat jendela yang dapat diaktifkan independen.
    """

    period = models.ForeignKey(
        ICoFRPeriod,
        on_delete=models.PROTECT,
        related_name="schedules",
        verbose_name="Periode",
    )
    rcm_set = models.ForeignKey(
        RCMSet,
        on_delete=models.PROTECT,
        related_name="schedules",
        verbose_name="RCM",
    )

    questionnaire_active = models.BooleanField(default=False, verbose_name="Aktif Kuesioner")
    questionnaire_start = models.DateField(null=True, blank=True, verbose_name="Mulai Kuesioner")
    questionnaire_end = models.DateField(null=True, blank=True, verbose_name="Akhir Kuesioner")

    line1_active = models.BooleanField(default=False, verbose_name="Aktif Line 1")
    line1_start = models.DateField(null=True, blank=True, verbose_name="Mulai Line 1")
    line1_end = models.DateField(null=True, blank=True, verbose_name="Akhir Line 1")

    line2_active = models.BooleanField(default=False, verbose_name="Aktif Line 2")
    line2_start = models.DateField(null=True, blank=True, verbose_name="Mulai Line 2")
    line2_end = models.DateField(null=True, blank=True, verbose_name="Akhir Line 2")

    line3_active = models.BooleanField(default=False, verbose_name="Aktif Line 3")
    line3_start = models.DateField(null=True, blank=True, verbose_name="Mulai Line 3")
    line3_end = models.DateField(null=True, blank=True, verbose_name="Akhir Line 3")

    notes = models.TextField(blank=True, verbose_name="Catatan")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="icofr_schedules_created",
    )

    class Meta:
        db_table = "icofr_schedule"
        verbose_name = "Penjadwalan ICoFR"
        verbose_name_plural = "ICoFR — Penjadwalan"
        ordering = ("-period__year", "rcm_set__rcm_type", "period__name")
        constraints = [
            models.UniqueConstraint(
                fields=("period", "rcm_set"),
                name="uniq_icofr_schedule_period_rcm",
            )
        ]

    _STAGE_FIELDS = {
        ICoFRStage.QUESTIONNAIRE: ("questionnaire_active", "questionnaire_start", "questionnaire_end"),
        ICoFRStage.LINE1: ("line1_active", "line1_start", "line1_end"),
        ICoFRStage.LINE2: ("line2_active", "line2_start", "line2_end"),
        ICoFRStage.LINE3: ("line3_active", "line3_start", "line3_end"),
    }

    def clean(self):
        super().clean()
        errors = {}
        if self.period_id and self.rcm_set_id:
            if self.period.rcm_type != self.rcm_set.rcm_type:
                errors["rcm_set"] = "Jenis RCM harus sama dengan jenis RCM pada periode."
        for stage, (active_field, start_field, end_field) in self._STAGE_FIELDS.items():
            active = getattr(self, active_field)
            start = getattr(self, start_field)
            end = getattr(self, end_field)
            if active and (not start or not end):
                errors[start_field] = f"Tanggal mulai dan akhir {ICoFRStage(stage).label} wajib diisi ketika diaktifkan."
            if start and end and end < start:
                errors[end_field] = f"Tanggal akhir {ICoFRStage(stage).label} tidak boleh sebelum tanggal mulai."
        if errors:
            raise ValidationError(errors)

    def stage_config(self, stage):
        stage = ICoFRStage(stage)
        active_field, start_field, end_field = self._STAGE_FIELDS[stage]
        return {
            "stage": stage,
            "active": getattr(self, active_field),
            "start": getattr(self, start_field),
            "end": getattr(self, end_field),
        }

    def __str__(self):
        return f"{self.rcm_set} / {self.period.name} {self.period.year}"


class ICoFRScheduleUnit(TimeStampedModel):
    schedule = models.ForeignKey(
        ICoFRSchedule,
        on_delete=models.CASCADE,
        related_name="unit_activations",
        verbose_name="Penjadwalan",
    )
    organization_unit = models.ForeignKey(
        "masterdata.OrganizationUnit",
        on_delete=models.PROTECT,
        related_name="icofr_schedule_activations",
        verbose_name="Organization Unit",
    )
    questionnaire_active = models.BooleanField(default=False, verbose_name="Kuesioner")
    line1_active = models.BooleanField(default=False, verbose_name="Line 1")
    line2_active = models.BooleanField(default=False, verbose_name="Line 2")
    line3_active = models.BooleanField(default=False, verbose_name="Line 3")

    class Meta:
        db_table = "icofr_schedule_unit"
        verbose_name = "Aktivasi Unit ICoFR"
        verbose_name_plural = "Aktivasi Unit ICoFR"
        ordering = ("schedule", "organization_unit__code")
        constraints = [
            models.UniqueConstraint(
                fields=("schedule", "organization_unit"),
                name="uniq_icofr_schedule_org_unit",
            )
        ]

    def is_active_for(self, stage):
        stage = ICoFRStage(stage)
        field = {
            ICoFRStage.QUESTIONNAIRE: "questionnaire_active",
            ICoFRStage.LINE1: "line1_active",
            ICoFRStage.LINE2: "line2_active",
            ICoFRStage.LINE3: "line3_active",
        }[stage]
        return bool(getattr(self, field))

    def __str__(self):
        return f"{self.schedule} — {self.organization_unit}"


class ICoFRDistributionBatch(TimeStampedModel):
    class Status(models.TextChoices):
        COMPLETED = "COMPLETED", "Selesai"
        PARTIAL = "PARTIAL", "Sebagian"
        FAILED = "FAILED", "Gagal"

    schedule = models.ForeignKey(
        ICoFRSchedule,
        on_delete=models.CASCADE,
        related_name="distribution_batches",
        verbose_name="Penjadwalan",
    )
    stage = models.CharField(max_length=20, choices=ICoFRStage.choices, verbose_name="Tahap")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.COMPLETED)
    total_entries = models.PositiveIntegerField(default=0)
    distributed_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    summary = models.JSONField(default=dict, blank=True)
    distributed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="icofr_distributions",
    )
    distributed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "icofr_distribution_batch"
        verbose_name = "Distribusi Kontrol"
        verbose_name_plural = "ICoFR — Riwayat Distribusi"
        ordering = ("-distributed_at",)

    def __str__(self):
        return f"{self.schedule} — {self.get_stage_display()} — {self.distributed_at:%d-%m-%Y %H:%M}"


class ICoFRWorkItem(TimeStampedModel):
    class Status(models.TextChoices):
        READY = "READY", "Ready"
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Terkirim"
        APPROVED = "APPROVED", "Disetujui"
        REJECTED = "REJECTED", "Ditolak"
        FINISHED = "FINISHED", "Finish"

    schedule = models.ForeignKey(
        ICoFRSchedule,
        on_delete=models.CASCADE,
        related_name="work_items",
        verbose_name="Penjadwalan",
    )
    stage = models.CharField(max_length=20, choices=ICoFRStage.choices, verbose_name="Tahap")
    entry = models.ForeignKey(
        RCMEntry,
        on_delete=models.PROTECT,
        related_name="icofr_work_items",
        verbose_name="Entry RCM",
    )
    organization_unit = models.ForeignKey(
        "masterdata.OrganizationUnit",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="icofr_work_items",
        verbose_name="Organization Unit",
    )
    preparer_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="icofr_work_items_as_preparer",
        verbose_name="Preparer",
    )
    reviewer_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="icofr_work_items_as_reviewer",
        verbose_name="Reviewer",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.READY)
    distribution_batch = models.ForeignKey(
        ICoFRDistributionBatch,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="work_items",
    )

    class Meta:
        db_table = "icofr_work_item"
        verbose_name = "Pelaksana Risk Control"
        verbose_name_plural = "ICoFR — Pelaksana Risk Control"
        ordering = ("schedule", "stage", "entry__source_row_number")
        constraints = [
            models.UniqueConstraint(
                fields=("schedule", "stage", "entry"),
                name="uniq_icofr_work_item_schedule_stage_entry",
            )
        ]
        indexes = [
            models.Index(fields=("schedule", "stage", "status")),
            models.Index(fields=("preparer_user", "stage", "status")),
            models.Index(fields=("reviewer_user", "stage", "status")),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.schedule_id and self.entry_id:
            if self.entry.rcm_set_id != self.schedule.rcm_set_id:
                errors["entry"] = "Entry RCM harus berasal dari RCM pada penjadwalan."
        if (
            self.stage == ICoFRStage.LINE1
            and self.preparer_user_id
            and self.reviewer_user_id
            and self.preparer_user_id == self.reviewer_user_id
        ):
            errors["reviewer_user"] = "Control Preparer dan Control Reviewer Line 1 harus berbeda (Segregation of Duties)."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.get_stage_display()} — {self.entry}"


class ICoFRQuestion(TimeStampedModel):
    rcm_type = models.CharField(max_length=10, choices=RCMType.choices, verbose_name="Jenis RCM")
    sequence = models.PositiveIntegerField(default=1, verbose_name="Urutan")
    question = models.TextField(verbose_name="Pertanyaan")
    is_active = models.BooleanField(default=True, verbose_name="Aktif")

    class Meta:
        db_table = "icofr_question"
        verbose_name = "Pertanyaan Kuesioner"
        verbose_name_plural = "ICoFR — Master Kuesioner"
        ordering = ("rcm_type", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("rcm_type", "sequence"),
                name="uniq_icofr_question_type_sequence",
            )
        ]

    def __str__(self):
        return f"{self.rcm_type} #{self.sequence} — {self.question[:80]}"


class QuestionnaireSubmission(TimeStampedModel):
    class Status(models.TextChoices):
        READY = "READY", "Ready"
        DRAFT = "DRAFT", "Draft"
        REQUESTED = "REQUESTED", "Requested"
        APPROVED = "APPROVED", "Approved"
        FINISH = "FINISH", "Finish"
        REJECTED = "REJECTED", "Rejected"

    work_item = models.OneToOneField(
        ICoFRWorkItem,
        on_delete=models.CASCADE,
        related_name="questionnaire_submission",
        limit_choices_to={"stage": ICoFRStage.QUESTIONNAIRE},
        verbose_name="Work Item",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.READY)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="icofr_questionnaires_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    admin_note = models.TextField(blank=True, verbose_name="Catatan Admin")

    class Meta:
        db_table = "icofr_questionnaire_submission"
        verbose_name = "Kuesioner"
        verbose_name_plural = "ICoFR — Kuesioner"
        ordering = ("work_item__schedule", "work_item__entry__source_row_number")

    @property
    def has_change(self):
        return self.answers.filter(answer=True).exists()

    def validate_ready_to_submit(self):
        active_questions = ICoFRQuestion.objects.filter(
            rcm_type=self.work_item.entry.rcm_set.rcm_type,
            is_active=True,
        )
        answers = {answer.question_id: answer for answer in self.answers.all()}
        missing = [question for question in active_questions if question.id not in answers or answers[question.id].answer is None]
        if missing:
            raise ValidationError(f"Masih ada {len(missing)} pertanyaan yang belum dijawab.")
        for answer in answers.values():
            if answer.answer and not answer.change_description.strip():
                raise ValidationError("Setiap jawaban 'Ya' wajib mempunyai deskripsi perubahan.")

    def submit(self):
        self.validate_ready_to_submit()
        self.status = self.Status.REQUESTED if self.has_change else self.Status.FINISH
        self.submitted_at = timezone.now()
        self.save(update_fields=("status", "submitted_at", "updated_at"))
        self.work_item.status = (
            ICoFRWorkItem.Status.SUBMITTED if self.status == self.Status.REQUESTED else ICoFRWorkItem.Status.FINISHED
        )
        self.work_item.save(update_fields=("status", "updated_at"))

    def approve(self, user, note=""):
        if self.status != self.Status.REQUESTED:
            raise ValidationError("Hanya kuesioner Requested yang dapat disetujui.")
        self.status = self.Status.APPROVED
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        self.admin_note = note or self.admin_note
        self.save(update_fields=("status", "reviewed_by", "reviewed_at", "admin_note", "updated_at"))
        self.work_item.status = ICoFRWorkItem.Status.APPROVED
        self.work_item.save(update_fields=("status", "updated_at"))

    def __str__(self):
        return f"{self.work_item.entry} — {self.get_status_display()}"


class QuestionnaireAnswer(TimeStampedModel):
    submission = models.ForeignKey(
        QuestionnaireSubmission,
        on_delete=models.CASCADE,
        related_name="answers",
    )
    question = models.ForeignKey(
        ICoFRQuestion,
        on_delete=models.PROTECT,
        related_name="answers",
    )
    answer = models.BooleanField(null=True, blank=True, verbose_name="Jawaban Ya/Tidak")
    change_description = models.TextField(blank=True, verbose_name="Deskripsi Perubahan")

    class Meta:
        db_table = "icofr_questionnaire_answer"
        verbose_name = "Jawaban Kuesioner"
        verbose_name_plural = "Jawaban Kuesioner"
        ordering = ("question__sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("submission", "question"),
                name="uniq_icofr_questionnaire_answer",
            )
        ]

    def clean(self):
        super().clean()
        if self.submission_id and self.question_id:
            if self.question.rcm_type != self.submission.work_item.entry.rcm_set.rcm_type:
                raise ValidationError({"question": "Jenis RCM pertanyaan tidak sesuai dengan RCM work item."})
        if self.answer is True and not self.change_description.strip():
            raise ValidationError({"change_description": "Deskripsi perubahan wajib diisi untuk jawaban Ya."})

    def __str__(self):
        return f"{self.submission} / {self.question.sequence}"


class QuestionnaireEvidence(TimeStampedModel):
    submission = models.ForeignKey(
        QuestionnaireSubmission,
        on_delete=models.CASCADE,
        related_name="evidences",
    )
    file = models.FileField(upload_to="icofr/questionnaire/%Y/%m/", verbose_name="Dokumen Pendukung")
    description = models.CharField(max_length=255, blank=True, verbose_name="Keterangan")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="icofr_questionnaire_evidence_uploads",
    )

    class Meta:
        db_table = "icofr_questionnaire_evidence"
        verbose_name = "Dokumen Kuesioner"
        verbose_name_plural = "Dokumen Kuesioner"

    def __str__(self):
        return self.description or self.file.name


class CSAIneffectivenessCategory(TimeStampedModel):
    rcm_type = models.CharField(max_length=10, choices=RCMType.choices, verbose_name="Jenis RCM")
    name = models.CharField(max_length=180, verbose_name="Kategori Ketidakefektifan")
    description = models.TextField(blank=True, verbose_name="Keterangan")
    is_active = models.BooleanField(default=True, verbose_name="Aktif")

    class Meta:
        db_table = "icofr_csa_ineffectiveness_category"
        verbose_name = "Kategori Ketidakefektifan"
        verbose_name_plural = "ICoFR — Master Ketidakefektifan"
        ordering = ("rcm_type", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("rcm_type", "name"),
                name="uniq_icofr_ineffectiveness_type_name",
            )
        ]

    def __str__(self):
        return f"{self.rcm_type} — {self.name}"


class CSAAssessment(TimeStampedModel):
    class Status(models.TextChoices):
        READY = "READY", "Ready"
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Terkirim"
        APPROVED = "APPROVED", "Disetujui"
        REJECTED = "REJECTED", "Ditolak"

    class Result(models.TextChoices):
        EFFECTIVE = "EFFECTIVE", "Efektif"
        INEFFECTIVE = "INEFFECTIVE", "Tidak Efektif"
        TAT = "TAT", "TAT / Tidak Ada Transaksi"

    work_item = models.OneToOneField(
        ICoFRWorkItem,
        on_delete=models.CASCADE,
        related_name="csa_assessment",
        limit_choices_to={"stage": ICoFRStage.LINE1},
        verbose_name="Work Item",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.READY)
    result = models.CharField(max_length=20, choices=Result.choices, blank=True, verbose_name="Hasil CSA")
    ineffectiveness_category = models.ForeignKey(
        CSAIneffectivenessCategory,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assessments",
        verbose_name="Kategori Ketidakefektifan",
    )
    ineffectiveness_explanation = models.TextField(blank=True, verbose_name="Penjelasan Ketidakefektifan / Perbaikan")
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="icofr_csa_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_note = models.TextField(blank=True, verbose_name="Catatan Reviewer")
    review_round = models.PositiveIntegerField(default=0, verbose_name="Putaran Review")

    class Meta:
        db_table = "icofr_csa_assessment"
        verbose_name = "CSA Line 1"
        verbose_name_plural = "ICoFR — CSA Line 1"
        ordering = ("work_item__schedule", "work_item__entry__source_row_number")

    def validate_ready_to_submit(self):
        if not self.result:
            raise ValidationError("Hasil CSA wajib dipilih sebelum dikirim.")
        if self.result == self.Result.TAT:
            if self.samples.exists():
                raise ValidationError("CSA berstatus TAT tidak boleh mempunyai sampel transaksi.")
            if not self.evidences.filter(evidence_type=CSAEvidence.EvidenceType.TAT).exists():
                raise ValidationError("Status TAT wajib mempunyai dokumen/evidence TAT.")
        else:
            samples = list(self.samples.all())
            if not samples:
                raise ValidationError("CSA Efektif/Tidak Efektif wajib mempunyai minimal satu sampel transaksi.")
            any_ineffective = False
            for sample in samples:
                expected_attributes = list(self.work_item.entry.control_attributes.values_list("id", flat=True))
                actual_attributes = set(sample.attribute_results.values_list("attribute_id", flat=True))
                missing_attributes = [pk for pk in expected_attributes if pk not in actual_attributes]
                if missing_attributes:
                    raise ValidationError(
                        f"Sampel '{sample.description}' belum menilai seluruh atribut kontrol "
                        f"({len(missing_attributes)} atribut belum dinilai)."
                    )
                if sample.result == CSASample.Result.EFFECTIVE and sample.attribute_results.filter(is_met=False).exists():
                    raise ValidationError(
                        f"Sampel '{sample.description}' tidak dapat Efektif karena masih ada atribut kontrol yang tidak terpenuhi."
                    )
                required_docs = set(self.work_item.entry.supporting_documents.values_list("id", flat=True))
                if required_docs:
                    uploaded_docs = set(
                        sample.evidences.filter(evidence_type=CSAEvidence.EvidenceType.SUPPORTING)
                        .exclude(supporting_document__isnull=True)
                        .values_list("supporting_document_id", flat=True)
                    )
                    missing_docs = required_docs - uploaded_docs
                    if missing_docs:
                        raise ValidationError(
                            f"Sampel '{sample.description}' belum memenuhi {len(missing_docs)} dokumen evidence yang diwajibkan RCM."
                        )
                any_ineffective = any_ineffective or sample.result == CSASample.Result.INEFFECTIVE
            if any_ineffective and self.result != self.Result.INEFFECTIVE:
                raise ValidationError("Jika ada sampel Tidak Efektif, hasil CSA harus Tidak Efektif.")
            if not any_ineffective and self.result != self.Result.EFFECTIVE:
                raise ValidationError("Jika seluruh sampel Efektif, hasil CSA harus Efektif.")
        if self.result == self.Result.INEFFECTIVE:
            if not self.ineffectiveness_category_id:
                raise ValidationError("CSA Tidak Efektif wajib mempunyai kategori ketidakefektifan.")
            if not self.ineffectiveness_explanation.strip():
                raise ValidationError("CSA Tidak Efektif wajib mempunyai penjelasan ketidakefektifan/perbaikan.")
        for sample in self.samples.all():
            sample.full_clean()

    def _workflow_snapshot(self):
        entry = self.work_item.entry
        return {
            "status": self.status,
            "result": self.result,
            "result_label": self.get_result_display() if self.result else "",
            "rcm_type": entry.rcm_set.rcm_type,
            "period": str(self.work_item.schedule.period),
            "risk_reference": entry.risk.reference,
            "control_reference": entry.control.reference,
            "segment": entry.segment,
            "sample_count": self.samples.count(),
            "evidence_count": self.evidences.count(),
            "ineffectiveness_category": (
                self.ineffectiveness_category.name if self.ineffectiveness_category_id else ""
            ),
            "ineffectiveness_explanation": self.ineffectiveness_explanation,
        }

    def _record_workflow(self, action, user=None, note=""):
        CSAAssessmentReviewLog.objects.create(
            assessment=self,
            round_number=self.review_round,
            action=action,
            actor=user,
            note=str(note or ""),
            snapshot=self._workflow_snapshot(),
        )

    @transaction.atomic
    def submit(self, user=None):
        if self.status not in {self.Status.READY, self.Status.DRAFT, self.Status.REJECTED}:
            raise ValidationError("CSA hanya dapat dikirim dari status Ready, Draft, atau Ditolak.")
        if (
            user
            and not getattr(user, "is_superuser", False)
            and self.work_item.preparer_user_id
            and self.work_item.preparer_user_id != getattr(user, "pk", None)
        ):
            raise ValidationError("CSA hanya dapat dikirim oleh Control Preparer yang terdistribusi.")
        self.validate_ready_to_submit()
        was_rejected = self.status == self.Status.REJECTED
        self.review_round += 1
        self.status = self.Status.SUBMITTED
        self.submitted_at = timezone.now()
        # Catatan penolakan lama tetap tersimpan pada workflow log, sedangkan review
        # aktif dibersihkan agar putaran berikutnya tidak rancu.
        self.reviewed_by = None
        self.reviewed_at = None
        self.reviewer_note = ""
        self.save(update_fields=(
            "status", "submitted_at", "review_round", "reviewed_by",
            "reviewed_at", "reviewer_note", "updated_at"
        ))
        self.work_item.status = ICoFRWorkItem.Status.SUBMITTED
        self.work_item.save(update_fields=("status", "updated_at"))
        self._record_workflow(
            CSAAssessmentReviewLog.Action.RESUBMIT if was_rejected else CSAAssessmentReviewLog.Action.SUBMIT,
            user=user or self.work_item.preparer_user,
        )

    def _validate_reviewer(self, user):
        if not user or not getattr(user, "is_authenticated", False):
            raise ValidationError("Reviewer tidak valid.")
        if getattr(user, "is_superuser", False):
            return
        if self.work_item.reviewer_user_id != user.pk:
            raise ValidationError("CSA hanya dapat direview oleh Control Reviewer yang terdistribusi.")
        if self.work_item.preparer_user_id == user.pk:
            raise ValidationError("Control Preparer tidak boleh mereview CSA miliknya sendiri.")

    @transaction.atomic
    def approve(self, user, note=""):
        if self.status != self.Status.SUBMITTED:
            raise ValidationError("Hanya CSA yang sudah dikirim yang dapat disetujui.")
        self._validate_reviewer(user)
        self.status = self.Status.APPROVED
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        self.reviewer_note = note or ""
        self.save(update_fields=("status", "reviewed_by", "reviewed_at", "reviewer_note", "updated_at"))
        self.work_item.status = ICoFRWorkItem.Status.APPROVED
        self.work_item.save(update_fields=("status", "updated_at"))
        self._record_workflow(CSAAssessmentReviewLog.Action.APPROVE, user=user, note=note)

    @transaction.atomic
    def reject(self, user, note):
        if self.status != self.Status.SUBMITTED:
            raise ValidationError("Hanya CSA yang sudah dikirim yang dapat ditolak.")
        self._validate_reviewer(user)
        if not str(note or "").strip():
            raise ValidationError("Alasan penolakan wajib diisi.")
        self.status = self.Status.REJECTED
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        self.reviewer_note = str(note).strip()
        self.save(update_fields=("status", "reviewed_by", "reviewed_at", "reviewer_note", "updated_at"))
        self.work_item.status = ICoFRWorkItem.Status.REJECTED
        self.work_item.save(update_fields=("status", "updated_at"))
        self._record_workflow(CSAAssessmentReviewLog.Action.REJECT, user=user, note=note)

    def __str__(self):
        return f"CSA — {self.work_item.entry} — {self.get_status_display()}"


class CSAAssessmentReviewLog(models.Model):
    class Action(models.TextChoices):
        SUBMIT = "SUBMIT", "Kirim"
        RESUBMIT = "RESUBMIT", "Kirim Ulang"
        APPROVE = "APPROVE", "Setujui"
        REJECT = "REJECT", "Tolak"

    assessment = models.ForeignKey(
        CSAAssessment,
        on_delete=models.CASCADE,
        related_name="review_logs",
        verbose_name="CSA",
    )
    round_number = models.PositiveIntegerField(default=1, verbose_name="Putaran")
    action = models.CharField(max_length=20, choices=Action.choices, verbose_name="Aksi")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="icofr_csa_review_logs",
        verbose_name="Pelaksana",
    )
    note = models.TextField(blank=True, verbose_name="Catatan")
    snapshot = models.JSONField(default=dict, blank=True, verbose_name="Snapshot")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "icofr_csa_review_log"
        verbose_name = "Riwayat Workflow CSA"
        verbose_name_plural = "ICoFR — Riwayat Review CSA"
        ordering = ("-created_at", "-id")
        indexes = [models.Index(fields=("assessment", "round_number", "action"), name="icofr_csa_review_idx")]

    def __str__(self):
        return f"{self.assessment} — Putaran {self.round_number} — {self.get_action_display()}"


class CSASample(TimeStampedModel):
    class Result(models.TextChoices):
        EFFECTIVE = "EFFECTIVE", "Efektif"
        INEFFECTIVE = "INEFFECTIVE", "Tidak Efektif"

    assessment = models.ForeignKey(
        CSAAssessment,
        on_delete=models.CASCADE,
        related_name="samples",
        verbose_name="CSA",
    )
    description = models.CharField(max_length=255, verbose_name="Deskripsi Transaksi")
    transaction_date = models.DateField(default=timezone.localdate, verbose_name="Tanggal Transaksi")
    result = models.CharField(max_length=20, choices=Result.choices, verbose_name="Status Efektivitas Sampel")
    notes = models.TextField(blank=True, verbose_name="Catatan")

    class Meta:
        db_table = "icofr_csa_sample"
        verbose_name = "Sampel CSA"
        verbose_name_plural = "ICoFR — Sampel CSA"
        ordering = ("assessment", "transaction_date", "id")

    def clean(self):
        super().clean()
        if self.assessment_id and self.assessment.status in {
            CSAAssessment.Status.SUBMITTED,
            CSAAssessment.Status.APPROVED,
        }:
            raise ValidationError("Sampel tidak dapat diubah setelah CSA dikirim/disetujui.")
        if self.pk and not self.attribute_results.exists():
            # Tidak memblokir saat objek baru dibuat; atribut dapat ditambahkan setelah save.
            return

    def __str__(self):
        return f"{self.assessment} — {self.description}"


class CSASampleAttributeResult(TimeStampedModel):
    sample = models.ForeignKey(
        CSASample,
        on_delete=models.CASCADE,
        related_name="attribute_results",
    )
    attribute = models.ForeignKey(
        RCMControlAttribute,
        on_delete=models.PROTECT,
        related_name="csa_results",
        verbose_name="Atribut Kontrol",
    )
    is_met = models.BooleanField(default=False, verbose_name="Terpenuhi")
    note = models.CharField(max_length=255, blank=True, verbose_name="Catatan")

    class Meta:
        db_table = "icofr_csa_sample_attribute"
        verbose_name = "Pemenuhan Atribut Kontrol"
        verbose_name_plural = "Pemenuhan Atribut Kontrol"
        constraints = [
            models.UniqueConstraint(
                fields=("sample", "attribute"),
                name="uniq_icofr_csa_sample_attribute",
            )
        ]

    def clean(self):
        super().clean()
        if self.sample_id and self.attribute_id:
            if self.attribute.entry_id != self.sample.assessment.work_item.entry_id:
                raise ValidationError({"attribute": "Atribut kontrol harus berasal dari entry RCM yang sedang dinilai."})

    def __str__(self):
        return f"{self.sample} — {self.attribute.text[:80]}"


class CSAEvidence(TimeStampedModel):
    class EvidenceType(models.TextChoices):
        SUPPORTING = "SUPPORTING", "Dokumen Evidence"
        TAT = "TAT", "Dokumen TAT"
        OTHER = "OTHER", "Dokumen Lain"

    assessment = models.ForeignKey(
        CSAAssessment,
        on_delete=models.CASCADE,
        related_name="evidences",
        verbose_name="CSA",
    )
    sample = models.ForeignKey(
        CSASample,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="evidences",
        verbose_name="Sampel",
    )
    supporting_document = models.ForeignKey(
        RCMSupportingDocument,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="csa_evidences",
        verbose_name="Kebutuhan Dokumen RCM",
    )
    evidence_type = models.CharField(
        max_length=20,
        choices=EvidenceType.choices,
        default=EvidenceType.SUPPORTING,
        verbose_name="Jenis Evidence",
    )
    file = models.FileField(upload_to="icofr/csa/%Y/%m/", verbose_name="File")
    description = models.CharField(max_length=255, blank=True, verbose_name="Keterangan")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="icofr_csa_evidence_uploads",
    )

    class Meta:
        db_table = "icofr_csa_evidence"
        verbose_name = "Evidence CSA"
        verbose_name_plural = "Evidence CSA"
        ordering = ("assessment", "sample", "id")

    def clean(self):
        super().clean()
        if self.sample_id and self.sample.assessment_id != self.assessment_id:
            raise ValidationError({"sample": "Sampel harus berasal dari CSA yang sama."})
        entry_id = self.assessment.work_item.entry_id if self.assessment_id else None
        if self.supporting_document_id and entry_id and self.supporting_document.entry_id != entry_id:
            raise ValidationError({"supporting_document": "Dokumen pendukung harus berasal dari entry RCM yang sama."})
        if self.evidence_type == self.EvidenceType.TAT and self.sample_id:
            raise ValidationError({"sample": "Dokumen TAT tidak dikaitkan dengan sampel transaksi."})

    def __str__(self):
        return self.description or self.file.name
