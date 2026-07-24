import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masterdata", "0007_normalize_setper_and_bid_renkin"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OrganizationUnitUserAssignment",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "is_unit_head",
                    models.BooleanField(
                        default=False,
                        help_text=(
                            "Tandai untuk pejabat yang menjadi kepala "
                            "Organization Unit ini."
                        ),
                        verbose_name="Kepala Unit",
                    ),
                ),
                (
                    "utama",
                    models.BooleanField(default=True, verbose_name="Penugasan Utama"),
                ),
                ("aktif", models.BooleanField(default=True, verbose_name="Aktif")),
                (
                    "tanggal_mulai",
                    models.DateField(
                        default=django.utils.timezone.localdate,
                        verbose_name="Tanggal Mulai",
                    ),
                ),
                (
                    "tanggal_selesai",
                    models.DateField(
                        blank=True,
                        null=True,
                        verbose_name="Tanggal Selesai",
                    ),
                ),
                (
                    "organization_unit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="user_assignments",
                        to="masterdata.organizationunit",
                        verbose_name="Organization Unit",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="organization_unit_assignments",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="User / Pejabat",
                    ),
                ),
            ],
            options={
                "verbose_name": "Penugasan User Organisasi",
                "verbose_name_plural": "Organization — Penugasan User",
                "db_table": "md_organization_unit_user_assignment",
                "ordering": (
                    "organization_unit__code",
                    "-is_unit_head",
                    "user__first_name",
                    "user__last_name",
                    "user__username",
                ),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "organization_unit", "tanggal_mulai"),
                        name="uniq_user_organization_unit_start",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("aktif", True), ("is_unit_head", True)),
                        fields=("organization_unit",),
                        name="uniq_active_head_per_organization_unit",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("aktif", True), ("utama", True)),
                        fields=("user",),
                        name="uniq_active_primary_organization_per_user",
                    ),
                ],
            },
        ),
    ]
