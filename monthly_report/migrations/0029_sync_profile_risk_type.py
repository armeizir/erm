from django.db import migrations


def sync_profile_risk_type(apps, schema_editor):
    MonthlyRiskReportItem = apps.get_model("monthly_report", "MonthlyRiskReportItem")
    ReAssessmentItem = apps.get_model("risk", "ReAssessmentItem")

    # Profil Risiko adalah canonical source. Existing monthly rows mengikuti
    # jenis risiko master yang direferensikan oleh risk_event.
    canonical = dict(
        ReAssessmentItem.objects.filter(
            jenis_risiko__in=("kuantitatif", "kualitatif")
        ).values_list("pk", "jenis_risiko")
    )

    for risk_event_id, risk_type in canonical.items():
        MonthlyRiskReportItem.objects.filter(
            risk_event_id=risk_event_id
        ).update(jenis_risiko=risk_type)


def reverse_sync(apps, schema_editor):
    # Tidak mengubah data saat rollback karena jenis risiko historis sebelum
    # migrasi tidak dapat direkonstruksi secara aman.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("monthly_report", "0028_add_monthly_planned_treatment_cost"),
        ("risk", "0082_reassessmentitem_jenis_risiko"),
    ]

    operations = [
        migrations.RunPython(sync_profile_risk_type, reverse_sync),
    ]
