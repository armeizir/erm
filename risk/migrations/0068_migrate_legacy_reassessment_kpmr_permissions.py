from django.db import migrations


def copy_action_permissions(
    apps,
    *,
    source_app,
    target_models,
):
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    User = apps.get_model("auth", "User")

    for action in ("view", "add", "change", "delete"):
        # Semua permission legacy dengan action yang sama.
        source_permissions = Permission.objects.filter(
            content_type__app_label=source_app,
            codename__startswith=f"{action}_",
        )

        if not source_permissions.exists():
            continue

        # Pertahankan siapa saja yang sudah memiliki capability tersebut.
        groups = list(
            Group.objects.filter(
                permissions__in=source_permissions
            ).distinct()
        )

        users = list(
            User.objects.filter(
                user_permissions__in=source_permissions
            ).distinct()
        )

        # Berikan capability yang sama ke model canonical.
        for target_model in target_models:
            target_permission = Permission.objects.filter(
                content_type__app_label="risk",
                content_type__model=target_model,
                codename=f"{action}_{target_model}",
            ).first()

            if target_permission is None:
                raise RuntimeError(
                    "Canonical permission tidak ditemukan: "
                    f"risk.{action}_{target_model}"
                )

            for group in groups:
                group.permissions.add(target_permission)

            for user in users:
                user.user_permissions.add(target_permission)


def migrate_legacy_permissions(apps, schema_editor):
    # Legacy reassessment capability -> canonical reassessment.
    copy_action_permissions(
        apps,
        source_app="reassessment",
        target_models=(
            "reassessmentsummary",
            "reassessmentitem",
        ),
    )

    # Legacy KPMR capability -> canonical operational KPMR only.
    # KPMRIndikatorResmi dan KPMRPeriode sengaja tidak dimasukkan
    # karena merupakan konfigurasi/master dan bukan padanan 1:1 legacy.
    copy_action_permissions(
        apps,
        source_app="kpmr",
        target_models=(
            "kpmrsummary",
            "kpmritem",
        ),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("risk", "0067_copy_legacy_km_permissions"),
    ]

    operations = [
        migrations.RunPython(
            migrate_legacy_permissions,
            migrations.RunPython.noop,
        ),
    ]
