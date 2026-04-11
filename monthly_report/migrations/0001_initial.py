from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0001_initial"),
        ("km", "0001_initial"),
        ("masterdata", "0002_masterbumn"),
        ("reassessment", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="MonthlyRiskReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("kode", models.CharField(max_length=50, unique=True)),
                ("judul", models.CharField(max_length=255)),
                ("versi", models.PositiveIntegerField(default=1)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("submitted", "Submitted"), ("under_review", "Under Review"), ("revision", "Revision"), ("approved", "Approved"), ("locked", "Locked")], default="draft", max_length=30)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("summary_km", models.TextField(blank=True, null=True)),
                ("summary_rkm", models.TextField(blank=True, null=True)),
                ("summary_risiko", models.TextField(blank=True, null=True)),
                ("catatan_manajemen", models.TextField(blank=True, null=True)),
                ("total_risiko", models.PositiveIntegerField(default=0)),
                ("total_high", models.PositiveIntegerField(default=0)),
                ("total_mitigasi_terlambat", models.PositiveIntegerField(default=0)),
                ("total_selesai", models.PositiveIntegerField(default=0)),
                ("is_aggregated_to_corporate", models.BooleanField(default=False)),
                ("aggregated_at", models.DateTimeField(blank=True, null=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="monthly_report_approved", to=settings.AUTH_USER_MODEL)),
                ("kontrak_manajemen", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="km.kontrakmanajemen")),
                ("periode", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="masterdata.periodelaporan")),
                ("prepared_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="monthly_report_prepared", to=settings.AUTH_USER_MODEL)),
                ("reassessment", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="monthly_reports", to="reassessment.reassessment")),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="monthly_report_reviewed", to=settings.AUTH_USER_MODEL)),
                ("tahun_buku", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="masterdata.tahunbuku")),
                ("unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="masterdata.unitorganisasi")),
            ],
            options={
                "db_table": "mr_monthly_risk_report",
                "ordering": ["-tahun_buku__tahun", "periode__tanggal_mulai", "unit__kode", "-versi"],
                "unique_together": {("tahun_buku", "periode", "unit", "versi")},
            },
        ),
        migrations.CreateModel(
            name="MonthlyRiskReportItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("inherent_level", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("residual_level", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("target_residual_level", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("mitigation_progress_percent", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ("mitigation_status", models.CharField(blank=True, choices=[("not_started", "Not Started"), ("on_progress", "On Progress"), ("done", "Done"), ("delayed", "Delayed")], max_length=30, null=True)),
                ("trend", models.CharField(blank=True, choices=[("up", "Meningkat"), ("down", "Menurun"), ("flat", "Tetap")], max_length=10, null=True)),
                ("issue_summary", models.TextField(blank=True, null=True)),
                ("next_action", models.TextField(blank=True, null=True)),
                ("escalation_note", models.TextField(blank=True, null=True)),
                ("contributes_to_corporate", models.BooleanField(default=False)),
                ("corporate_note", models.TextField(blank=True, null=True)),
                ("inherent_skala_dampak", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="masterdata.skaladampak")),
                ("inherent_skala_probabilitas", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="masterdata.skalaprobabilitas")),
                ("km_item", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="km.kontrakmanajemenitem")),
                ("report", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="monthly_report.monthlyriskreport")),
                ("residual_skala_dampak", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="masterdata.skaladampak")),
                ("residual_skala_probabilitas", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="masterdata.skalaprobabilitas")),
                ("risk_event", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="monthly_report_items", to="reassessment.riskevent")),
            ],
            options={
                "db_table": "mr_monthly_risk_report_item",
                "ordering": ["risk_event__no_item", "risk_event__no_risiko"],
                "unique_together": {("report", "risk_event")},
            },
        ),
        migrations.CreateModel(
            name="MonthlyRiskReportKMAlignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("alignment_status", models.CharField(choices=[("aligned", "Aligned"), ("partial", "Partial"), ("not_aligned", "Not Aligned")], default="partial", max_length=20)),
                ("alignment_score", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ("reason", models.TextField(blank=True, null=True)),
                ("km_item", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="km.kontrakmanajemenitem")),
                ("report_item", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="km_alignment", to="monthly_report.monthlyriskreportitem")),
            ],
            options={"db_table": "mr_km_alignment"},
        ),
        migrations.CreateModel(
            name="MonthlyRiskReportSubmissionLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(choices=[("submit", "Submit"), ("review", "Review"), ("revise", "Revise"), ("approve", "Approve"), ("lock", "Lock")], max_length=30)),
                ("action_at", models.DateTimeField(auto_now_add=True)),
                ("note", models.TextField(blank=True, null=True)),
                ("action_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("report", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="submission_logs", to="monthly_report.monthlyriskreport")),
            ],
            options={"db_table": "mr_submission_log", "ordering": ["-action_at"]},
        ),
    ]
