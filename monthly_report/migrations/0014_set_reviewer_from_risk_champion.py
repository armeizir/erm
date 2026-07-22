from django.db import migrations


def set_reviewer_from_risk_champion(apps, schema_editor):
    MonthlyRiskReport = apps.get_model("monthly_report", "MonthlyRiskReport")
    PenugasanUnitBisnis = apps.get_model("risk", "PenugasanUnitBisnis")

    reports = MonthlyRiskReport.objects.select_related(
        "reassessment__unit_bisnis"
    ).all()
    for report in reports.iterator():
        unit_id = report.reassessment.unit_bisnis_id
        champion_user_id = (
            PenugasanUnitBisnis.objects.filter(
                unit_bisnis_id=unit_id,
                peran="RISK_CHAMPION",
                aktif=True,
                user__is_active=True,
            )
            .order_by("user__first_name", "user__last_name", "user__username", "user_id")
            .values_list("user_id", flat=True)
            .first()
        )
        if champion_user_id and report.reviewed_by_id != champion_user_id:
            report.reviewed_by_id = champion_user_id
            report.save(update_fields=["reviewed_by"])


class Migration(migrations.Migration):
    dependencies = [
        ("monthly_report", "0013_alter_monthlyriskreportitem_persentase_serapan_biaya"),
        ("risk", "0064_normalize_setper_display_names"),
    ]

    operations = [
        migrations.RunPython(set_reviewer_from_risk_champion, migrations.RunPython.noop),
    ]
