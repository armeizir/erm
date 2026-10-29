from django.db import migrations, models
import django.db.models.deletion
import monthly_report.evidence_storage
import monthly_report.models

class Migration(migrations.Migration):
    dependencies = [("monthly_report", "0033_expand_pairing_review_decision_states")]
    operations = [
        migrations.AddField("monthlyriskreportevidence", "document", models.FileField(blank=True, default="", storage=monthly_report.evidence_storage.private_evidence_storage, upload_to=monthly_report.evidence_storage.evidence_upload_path, validators=[monthly_report.evidence_storage.validate_evidence_file], verbose_name="Upload dokumen (maks. 20 MB)")),
        migrations.AddField("monthlyriskreportevidence", "original_filename", models.CharField(max_length=255, blank=True, default="", editable=False)),
        migrations.AddField("monthlyriskreportevidence", "sha256", models.CharField(max_length=64, blank=True, default="", editable=False)),
        migrations.AddField("monthlyriskreportevidence", "file_size", models.PositiveBigIntegerField(default=0, editable=False)),
        migrations.AddField("monthlyriskreportevidence", "version", models.PositiveIntegerField(default=1, editable=False)),
        migrations.AddField("monthlyriskreportevidence", "supersedes", models.ForeignKey(to="monthly_report.monthlyriskreportevidence", null=True, blank=True, on_delete=django.db.models.deletion.PROTECT, related_name="new_versions", verbose_name="Versi sebelumnya (opsional)")),
        migrations.AddField("monthlyriskreportevidence", "report_item", models.ForeignKey(to="monthly_report.monthlyriskreportitem", null=True, blank=True, on_delete=django.db.models.deletion.PROTECT, related_name="evidence_documents", verbose_name="Risiko/perlakuan terkait (opsional)")),
        migrations.AlterField("monthlyriskreportevidence", "external_url", models.URLField(max_length=500, blank=True, default="", validators=[monthly_report.models.validate_https_evidence_url], verbose_name="Link Eviden", help_text="Referensi tambahan; tidak menggantikan dokumen eviden tersimpan.")),
        migrations.AlterField("monthlyriskreportevidence", "report", models.ForeignKey(to="monthly_report.monthlyriskreport", on_delete=django.db.models.deletion.PROTECT, related_name="evidences", verbose_name="Laporan Risiko Bulanan")),
        migrations.AlterField("monthlyriskreport", "evidence_url", models.URLField(max_length=500, blank=True, default="", validators=[monthly_report.models.validate_https_evidence_url], verbose_name="Link Referensi Eviden Lama (opsional)", help_text="Unggah Dokumen Eviden pada tabel di bawah. Link ini hanya referensi tambahan.")),
    ]
