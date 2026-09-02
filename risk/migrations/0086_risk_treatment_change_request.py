from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(
            settings.AUTH_USER_MODEL
        ),
        (
            "risk",
            "0085_corporate_kpi_relation",
        ),
    ]

    operations = [
        migrations.CreateModel(
            name="RiskTreatmentChangeRequest",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "version",
                    models.PositiveIntegerField(
                        default=1,
                        verbose_name="Versi Perubahan",
                    ),
                ),
                (
                    "before_snapshot",
                    models.JSONField(
                        default=dict,
                        verbose_name="Data Sebelum Perubahan",
                    ),
                ),
                (
                    "proposed_changes",
                    models.JSONField(
                        default=dict,
                        verbose_name="Usulan Perubahan",
                    ),
                ),
                (
                    "alasan_perubahan",
                    models.TextField(
                        verbose_name="Alasan Perubahan",
                    ),
                ),
                (
                    "dampak_perubahan",
                    models.TextField(
                        blank=True,
                        null=True,
                        verbose_name="Dampak Perubahan",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("submitted", "Diajukan"),
                            (
                                "under_review",
                                "Dalam Review",
                            ),
                            (
                                "revision",
                                "Perlu Revisi",
                            ),
                            ("rejected", "Ditolak"),
                            ("approved", "Disetujui"),
                        ],
                        db_index=True,
                        default="draft",
                        max_length=20,
                        verbose_name="Status",
                    ),
                ),
                (
                    "requested_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Tanggal Pengajuan",
                    ),
                ),
                (
                    "reviewed_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Tanggal Review",
                    ),
                ),
                (
                    "reviewer_note",
                    models.TextField(
                        blank=True,
                        null=True,
                        verbose_name="Catatan Reviewer",
                    ),
                ),
                (
                    "approved_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Tanggal Persetujuan",
                    ),
                ),
                (
                    "applied_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Tanggal Diterapkan",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                    ),
                ),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="risk_treatment_changes_approved",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Disetujui Oleh",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="risk_treatment_changes_created",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Dibuat Oleh",
                    ),
                ),
                (
                    "reassessment_item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="treatment_change_requests",
                        to="risk.reassessmentitem",
                        verbose_name="Item Risiko",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="risk_treatment_changes_requested",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Diajukan Oleh",
                    ),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="risk_treatment_changes_reviewed",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Direview Oleh",
                    ),
                ),
            ],
            options={
                "verbose_name":
                    "Usulan Perubahan Rencana Perlakuan Risiko",
                "verbose_name_plural":
                    "Usulan Perubahan Rencana Perlakuan Risiko",
                "ordering": [
                    "-created_at",
                    "-pk",
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="risktreatmentchangerequest",
            constraint=models.UniqueConstraint(
                fields=(
                    "reassessment_item",
                    "version",
                ),
                name="uniq_treat_change_item_ver",
            ),
        ),
        migrations.AddConstraint(
            model_name="risktreatmentchangerequest",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    status__in=[
                        "draft",
                        "submitted",
                        "under_review",
                        "revision",
                    ]
                ),
                fields=(
                    "reassessment_item",
                ),
                name="uniq_open_treat_change_item",
            ),
        ),
    ]
