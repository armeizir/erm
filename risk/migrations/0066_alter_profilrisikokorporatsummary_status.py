from django.db import migrations, models


def normalize_status_forward(apps, schema_editor):
    Summary = apps.get_model("risk", "ProfilRisikoKorporatSummary")
    db = schema_editor.connection.alias

    Summary.objects.using(db).filter(
        status__iexact="draft"
    ).update(status="draft")

    Summary.objects.using(db).filter(
        status__iexact="final"
    ).update(status="final")


def normalize_status_reverse(apps, schema_editor):
    Summary = apps.get_model("risk", "ProfilRisikoKorporatSummary")
    db = schema_editor.connection.alias

    Summary.objects.using(db).filter(
        status="draft"
    ).update(status="Draft")

    Summary.objects.using(db).filter(
        status="final"
    ).update(status="Final")


class Migration(migrations.Migration):

    dependencies = [
        ("risk", "0065_encrypt_integration_secrets"),
    ]

    operations = [
        migrations.RunPython(
            normalize_status_forward,
            normalize_status_reverse,
        ),
        migrations.AlterField(
            model_name="profilrisikokorporatsummary",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("final", "Final"),
                ],
                default="draft",
                max_length=20,
                verbose_name="Status",
            ),
        ),
    ]
