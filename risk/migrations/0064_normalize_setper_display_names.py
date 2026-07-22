from django.db import migrations


DISPLAY_MODELS = (
    ("KontrakManajemen", "judul"),
    ("ReAssessmentSummary", "judul"),
    ("RKMSummary", "judul"),
    ("KPMRSummary", "judul"),
)


def replace_display_names(apps, old_name, new_name):
    Group = apps.get_model("auth", "Group")
    unit_ids = list(
        Group.objects.filter(name__in=("SEKPER", "SETPER")).values_list(
            "id", flat=True
        )
    )
    if not unit_ids:
        return

    for model_name, field_name in DISPLAY_MODELS:
        Model = apps.get_model("risk", model_name)
        for record in Model.objects.filter(unit_bisnis_id__in=unit_ids).only(
            "pk", field_name
        ):
            current = getattr(record, field_name) or ""
            updated = current.replace(old_name, new_name)
            if updated != current:
                setattr(record, field_name, updated)
                record.save(update_fields=[field_name])


def normalize_setper_display_names(apps, schema_editor):
    replace_display_names(apps, "SEKPER", "SETPER")


def reverse_setper_display_names(apps, schema_editor):
    replace_display_names(apps, "SETPER", "SEKPER")


class Migration(migrations.Migration):
    dependencies = [
        ("masterdata", "0007_normalize_setper_and_bid_renkin"),
        ("risk", "0063_correct_score_five_risk_level"),
    ]

    operations = [
        migrations.RunPython(
            normalize_setper_display_names,
            reverse_setper_display_names,
        ),
    ]
