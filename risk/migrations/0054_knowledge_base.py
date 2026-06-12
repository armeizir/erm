# Generated manually on 2026-06-11

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("risk", "0053_rkmsummary_penandatangan_laporan"),
    ]

    operations = [
        migrations.CreateModel(
            name="KnowledgeBaseCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nama", models.CharField(max_length=120, unique=True, verbose_name="Nama Kategori")),
                ("slug", models.SlugField(blank=True, max_length=140, unique=True)),
                ("deskripsi", models.TextField(blank=True, default="", verbose_name="Deskripsi")),
                ("urutan", models.PositiveIntegerField(default=1, verbose_name="Urutan")),
                ("aktif", models.BooleanField(default=True, verbose_name="Aktif")),
            ],
            options={
                "verbose_name": "Knowledge Base - Kategori",
                "verbose_name_plural": "KNOWLEDGE BASE — Kategori",
                "ordering": ["urutan", "nama"],
            },
        ),
        migrations.CreateModel(
            name="KnowledgeBaseArticle",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("judul", models.CharField(max_length=220, verbose_name="Judul")),
                ("slug", models.SlugField(blank=True, max_length=240, unique=True)),
                ("ringkasan", models.TextField(blank=True, default="", verbose_name="Ringkasan")),
                ("konten", models.TextField(verbose_name="Konten Knowledge Base")),
                ("tags", models.CharField(blank=True, default="", help_text="Pisahkan tag dengan koma. Contoh: ERM, Profil Risiko, Monte Carlo", max_length=255, verbose_name="Tag")),
                ("audience", models.CharField(choices=[("all", "Semua Pengguna"), ("strategic", "Strategic Level"), ("management", "Management Level"), ("operational", "Operational Level"), ("evaluation", "Evaluation Level"), ("admin", "Administrator")], default="all", max_length=20, verbose_name="Target Pengguna")),
                ("status", models.CharField(choices=[("draft", "Draft"), ("published", "Published"), ("archived", "Archived")], default="draft", max_length=20, verbose_name="Status")),
                ("lampiran", models.FileField(blank=True, null=True, upload_to="knowledge_base/", verbose_name="Lampiran")),
                ("dipublikasikan_pada", models.DateTimeField(blank=True, null=True, verbose_name="Dipublikasikan Pada")),
                ("dibuat_pada", models.DateTimeField(auto_now_add=True, verbose_name="Dibuat Pada")),
                ("diperbarui_pada", models.DateTimeField(auto_now=True, verbose_name="Diperbarui Pada")),
                ("dibuat_oleh", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="knowledge_base_dibuat", to=settings.AUTH_USER_MODEL, verbose_name="Dibuat Oleh")),
                ("diperbarui_oleh", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="knowledge_base_diperbarui", to=settings.AUTH_USER_MODEL, verbose_name="Diperbarui Oleh")),
                ("kategori", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="artikel", to="risk.knowledgebasecategory", verbose_name="Kategori")),
            ],
            options={
                "verbose_name": "Knowledge Base - Artikel",
                "verbose_name_plural": "KNOWLEDGE BASE — Artikel",
                "ordering": ["kategori__urutan", "judul"],
            },
        ),
    ]
