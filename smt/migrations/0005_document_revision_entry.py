from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("smt", "0004_approval_users")]
    operations = [migrations.CreateModel(
        name="DocumentRevisionEntry",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("revisi", models.CharField(max_length=30, verbose_name="Revisi")),
            ("tanggal_berlaku", models.DateField(blank=True, null=True, verbose_name="Tanggal berlaku", help_text="Tanggal revisi berjalan mengikuti tanggal berlaku dokumen.")),
            ("uraian", models.TextField(verbose_name="Uraian perubahan")),
            ("urutan", models.PositiveIntegerField(default=0, verbose_name="Urutan")),
            ("document", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="daftar_perubahan", to="smt.document")),
        ],
        options={"ordering": ["urutan", "pk"], "verbose_name": "Perubahan dokumen",
                 "verbose_name_plural": "Daftar Perubahan Dokumen",
                 "constraints": [models.UniqueConstraint(fields=("document", "revisi"), name="smt_unique_history_revision")]},
    )]
