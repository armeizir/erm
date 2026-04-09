from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('risk', '0030_alter_profilrisikokorporatpenyebab_key_risk_indicators'),
    ]

    operations = [
        migrations.AddField(
            model_name='profilrisikokorporatitem',
            name='matrix_cell_inheren',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='profil_risiko_korporat_inheren', to='risk.riskmatrixcell', verbose_name='Sel Matriks Inheren'),
        ),
        migrations.AddField(
            model_name='profilrisikokorporatitem',
            name='matrix_cell_residual',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='profil_risiko_korporat_residual', to='risk.riskmatrixcell', verbose_name='Sel Matriks Residual'),
        ),
        migrations.AddField(
            model_name='profilrisikokorporatitem',
            name='residual_dampak',
            field=models.IntegerField(blank=True, null=True, verbose_name='Dampak Residual'),
        ),
        migrations.AddField(
            model_name='profilrisikokorporatitem',
            name='residual_kemungkinan',
            field=models.IntegerField(blank=True, null=True, verbose_name='Kemungkinan Residual'),
        ),
        migrations.AddField(
            model_name='profilrisikokorporatitem',
            name='residual_level_risiko',
            field=models.IntegerField(blank=True, null=True, verbose_name='Level Risiko Residual'),
        ),
        migrations.AlterField(
            model_name='profilrisikokorporatitem',
            name='dampak',
            field=models.IntegerField(blank=True, null=True, verbose_name='Dampak Inheren'),
        ),
        migrations.AlterField(
            model_name='profilrisikokorporatitem',
            name='kemungkinan',
            field=models.IntegerField(blank=True, null=True, verbose_name='Kemungkinan Inheren'),
        ),
        migrations.AlterField(
            model_name='profilrisikokorporatitem',
            name='level_risiko',
            field=models.IntegerField(blank=True, null=True, verbose_name='Level Risiko Inheren'),
        ),
    ]
