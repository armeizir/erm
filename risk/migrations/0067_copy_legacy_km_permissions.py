from django.db import migrations


PERMISSION_MAP = (
    ("kontrakmanajemen", "kontrakmanajemen"),
    ("kontrakmanajemenitem", "itemkontrakmanajemen"),
)
ACTIONS = ("add", "change", "delete", "view")


def copy_legacy_km_permissions(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    User = apps.get_model("auth", "User")
    db = schema_editor.connection.alias

    for source_model, target_model in PERMISSION_MAP:
        source_ct = ContentType.objects.using(db).filter(
            app_label="km", model=source_model
        ).first()
        target_ct = ContentType.objects.using(db).filter(
            app_label="risk", model=target_model
        ).first()
        if not source_ct or not target_ct:
            continue

        for action in ACTIONS:
            source_perm = Permission.objects.using(db).filter(
                content_type_id=source_ct.id,
                codename=f"{action}_{source_model}",
            ).first()
            target_perm = Permission.objects.using(db).filter(
                content_type_id=target_ct.id,
                codename=f"{action}_{target_model}",
            ).first()
            if not source_perm or not target_perm:
                continue

            group_ids = list(
                Group.objects.using(db)
                .filter(permissions=source_perm)
                .values_list("id", flat=True)
            )
            for group in Group.objects.using(db).filter(id__in=group_ids):
                group.permissions.add(target_perm)

            user_ids = list(
                User.objects.using(db)
                .filter(user_permissions=source_perm)
                .values_list("id", flat=True)
            )
            for user in User.objects.using(db).filter(id__in=user_ids):
                user.user_permissions.add(target_perm)


class Migration(migrations.Migration):

    dependencies = [
        ("risk", "0066_alter_profilrisikokorporatsummary_status"),
    ]

    operations = [
        migrations.RunPython(copy_legacy_km_permissions, migrations.RunPython.noop),
    ]
