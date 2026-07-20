from django.db import migrations
from django.db.models import Q


def recalculate_monthly_risk_items(apps, schema_editor):
    MonthlyRiskReport = apps.get_model("monthly_report", "MonthlyRiskReport")
    MonthlyRiskReportItem = apps.get_model("monthly_report", "MonthlyRiskReportItem")
    RiskMatrix = apps.get_model("risk", "RiskMatrix")
    RiskMatrixCell = apps.get_model("risk", "RiskMatrixCell")

    default_matrix = RiskMatrix.objects.filter(aktif=True, is_default=True).first()
    cells = {
        (cell.matrix_id, cell.skala_dampak_id, cell.skala_probabilitas_id): cell
        for cell in RiskMatrixCell.objects.filter(aktif=True).select_related("level_risiko")
    }

    items = MonthlyRiskReportItem.objects.select_related("risk_event__summary").all()
    for item in items.iterator():
        if not item.realisasi_skala_dampak_id or not item.realisasi_skala_probabilitas_id:
            continue
        matrix_id = item.risk_event.summary.risk_matrix_id if item.risk_event_id else None
        matrix_id = matrix_id or (default_matrix.pk if default_matrix else None)
        cell = cells.get(
            (matrix_id, item.realisasi_skala_dampak_id, item.realisasi_skala_probabilitas_id)
        )
        if not cell:
            continue
        MonthlyRiskReportItem.objects.filter(pk=item.pk).update(
            realisasi_skor_risiko=cell.skor,
            realisasi_level_risiko=cell.level_risiko.nama,
        )

    for report in MonthlyRiskReport.objects.all().iterator():
        report_items = MonthlyRiskReportItem.objects.filter(report_id=report.pk)
        total_high = report_items.filter(
            Q(realisasi_skor_risiko__gte=20)
            | (
                Q(realisasi_skor_risiko__isnull=True)
                & (
                    Q(realisasi_level_risiko__iexact="High")
                    | Q(realisasi_level_risiko__iexact="Tinggi")
                    | Q(realisasi_level_risiko__iexact="Sangat Tinggi")
                    | Q(residual_level__gte=20)
                )
            )
        ).distinct().count()
        MonthlyRiskReport.objects.filter(pk=report.pk).update(
            total_risiko=report_items.count(),
            total_high=total_high,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("monthly_report", "0011_monthlyriskreportlossevent"),
        ("risk", "0063_correct_score_five_risk_level"),
    ]
    operations = [
        migrations.RunPython(recalculate_monthly_risk_items, migrations.RunPython.noop),
    ]
