from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [("smt", "0001_initial")]
    operations = [migrations.AddField(
        model_name="document", name="revisi_sebelumnya",
        field=models.ForeignKey(
            to="smt.document", on_delete=django.db.models.deletion.PROTECT,
            null=True, blank=True, editable=False,
            related_name="revisi_lanjutan", verbose_name="Revisi sebelumnya",
        ),
    ), migrations.AddConstraint(
        model_name="document",
        constraint=models.UniqueConstraint(
            fields=("revisi_sebelumnya",),
            condition=models.Q(revisi_sebelumnya__isnull=False),
            name="smt_one_successor_per_revision",
        ),
    )]
