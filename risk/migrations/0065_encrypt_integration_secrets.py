from cryptography.fernet import Fernet
from django.conf import settings
from django.db import migrations, models

PREFIX = "fernet:v1:"


def encrypt_existing_secrets(apps, schema_editor):
    AppSetting = apps.get_model("risk", "AppSetting")
    rows = list(AppSetting.objects.all())
    plaintext_exists = any(
        (row.ai_api_key and not row.ai_api_key.startswith(PREFIX))
        or (row.email_host_password and not row.email_host_password.startswith(PREFIX))
        for row in rows
    )
    if not plaintext_exists:
        return

    key = (getattr(settings, "APP_ENCRYPTION_KEY", "") or "").strip()
    if not key:
        raise RuntimeError(
            "Migration 0065 membutuhkan APP_ENCRYPTION_KEY karena database masih "
            "memiliki AI API Key/SMTP Password plaintext. Set master key terlebih dahulu."
        )

    try:
        fernet = Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError(
            "APP_ENCRYPTION_KEY tidak valid. Gunakan Fernet key urlsafe-base64 32-byte."
        ) from exc

    for row in rows:
        changed = []
        if row.ai_api_key and not row.ai_api_key.startswith(PREFIX):
            token = fernet.encrypt(row.ai_api_key.encode("utf-8")).decode("ascii")
            row.ai_api_key = f"{PREFIX}{token}"
            changed.append("ai_api_key")
        if row.email_host_password and not row.email_host_password.startswith(PREFIX):
            token = fernet.encrypt(row.email_host_password.encode("utf-8")).decode("ascii")
            row.email_host_password = f"{PREFIX}{token}"
            changed.append("email_host_password")
        if changed:
            row.save(update_fields=changed)


class Migration(migrations.Migration):
    dependencies = [
        ("risk", "0064_normalize_setper_display_names"),
    ]

    operations = [
        migrations.AlterField(
            model_name="appsetting",
            name="ai_api_key",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Disimpan terenkripsi. Gunakan form admin untuk mengganti secret.",
                verbose_name="API Key AI (terenkripsi)",
            ),
        ),
        migrations.AlterField(
            model_name="appsetting",
            name="email_host_password",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Disimpan terenkripsi. Gunakan form admin untuk mengganti secret.",
                verbose_name="SMTP Password (terenkripsi)",
            ),
        ),
        migrations.RunPython(encrypt_existing_secrets, migrations.RunPython.noop),
    ]
