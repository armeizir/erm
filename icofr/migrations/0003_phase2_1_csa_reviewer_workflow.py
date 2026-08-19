import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("icofr", "0002_phase2_schedule_questionnaire_csa"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="csaassessment",
            name="review_round",
            field=models.PositiveIntegerField(default=0, verbose_name="Putaran Review"),
        ),
        migrations.CreateModel(
            name="CSAAssessmentReviewLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("round_number", models.PositiveIntegerField(default=1, verbose_name="Putaran")),
                ("action", models.CharField(choices=[("SUBMIT", "Kirim"), ("RESUBMIT", "Kirim Ulang"), ("APPROVE", "Setujui"), ("REJECT", "Tolak")], max_length=20, verbose_name="Aksi")),
                ("note", models.TextField(blank=True, verbose_name="Catatan")),
                ("snapshot", models.JSONField(blank=True, default=dict, verbose_name="Snapshot")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="icofr_csa_review_logs", to=settings.AUTH_USER_MODEL, verbose_name="Pelaksana")),
                ("assessment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="review_logs", to="icofr.csaassessment", verbose_name="CSA")),
            ],
            options={
                "verbose_name": "Riwayat Workflow CSA",
                "verbose_name_plural": "ICoFR — Riwayat Review CSA",
                "db_table": "icofr_csa_review_log",
                "ordering": ("-created_at", "-id"),
            },
        ),
        migrations.AddIndex(
            model_name="csaassessmentreviewlog",
            index=models.Index(fields=["assessment", "round_number", "action"], name="icofr_csa_review_idx"),
        ),
    ]
