from django.db import migrations, models
import django.db.models.deletion


def assert_legacy_links_are_empty(apps, schema_editor):
    Report = apps.get_model("monthly_report", "MonthlyRiskReport")
    ReportItem = apps.get_model("monthly_report", "MonthlyRiskReportItem")
    Alignment = apps.get_model("monthly_report", "MonthlyRiskReportKMAlignment")

    counts = {
        "MonthlyRiskReport.kontrak_manajemen": Report.objects.exclude(kontrak_manajemen_id=None).count(),
        "MonthlyRiskReportItem.km_item": ReportItem.objects.exclude(km_item_id=None).count(),
        "MonthlyRiskReportKMAlignment.km_item": Alignment.objects.exclude(km_item_id=None).count(),
    }
    non_empty = {name: count for name, count in counts.items() if count}
    if non_empty:
        details = ", ".join(f"{name}={count}" for name, count in non_empty.items())
        raise RuntimeError(
            "Migration 0021 dihentikan karena masih ada relasi KM legacy non-null: " + details
        )


def backfill_canonical_links(apps, schema_editor):
    Report = apps.get_model("monthly_report", "MonthlyRiskReport")
    ReportItem = apps.get_model("monthly_report", "MonthlyRiskReportItem")
    Alignment = apps.get_model("monthly_report", "MonthlyRiskReportKMAlignment")
    ReAssessmentSummary = apps.get_model("risk", "ReAssessmentSummary")
    ReAssessmentItem = apps.get_model("risk", "ReAssessmentItem")

    db = schema_editor.connection.alias

    profile_to_km = dict(
        ReAssessmentSummary.objects.using(db)
        .exclude(kontrak_manajemen_id=None)
        .values_list("id", "kontrak_manajemen_id")
    )
    for report in Report.objects.using(db).exclude(reassessment_id=None).iterator():
        km_id = profile_to_km.get(report.reassessment_id)
        if km_id:
            Report.objects.using(db).filter(pk=report.pk).update(kontrak_manajemen_id=km_id)

    risk_to_km_item = dict(
        ReAssessmentItem.objects.using(db)
        .exclude(km_item_id=None)
        .values_list("id", "km_item_id")
    )
    for item in ReportItem.objects.using(db).exclude(risk_event_id=None).iterator():
        km_item_id = risk_to_km_item.get(item.risk_event_id)
        if km_item_id:
            ReportItem.objects.using(db).filter(pk=item.pk).update(km_item_id=km_item_id)

    report_item_to_km = dict(
        ReportItem.objects.using(db)
        .exclude(km_item_id=None)
        .values_list("id", "km_item_id")
    )
    for alignment in Alignment.objects.using(db).exclude(report_item_id=None).iterator():
        km_item_id = report_item_to_km.get(alignment.report_item_id)
        if km_item_id:
            Alignment.objects.using(db).filter(pk=alignment.pk).update(km_item_id=km_item_id)


class Migration(migrations.Migration):

    dependencies = [
        ("risk", "0066_alter_profilrisikokorporatsummary_status"),
        ("monthly_report", "0020_alter_monthlyriskreport_evidence_url_and_more"),
    ]

    operations = [
        migrations.RunPython(assert_legacy_links_are_empty, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="monthlyriskreport",
            name="kontrak_manajemen",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="risk.kontrakmanajemen",
            ),
        ),
        migrations.AlterField(
            model_name="monthlyriskreportitem",
            name="km_item",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="risk.itemkontrakmanajemen",
            ),
        ),
        migrations.AlterField(
            model_name="monthlyriskreportkmalignment",
            name="km_item",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="risk.itemkontrakmanajemen",
            ),
        ),
        migrations.RunPython(backfill_canonical_links, migrations.RunPython.noop),
    ]
