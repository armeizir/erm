from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import MonthlyRiskReport, MonthlyRiskReportItem, MonthlyRiskReportSubmissionLog
from reassessment.models import RiskAssessment


@transaction.atomic
def generate_monthly_report_from_reassessment(report: MonthlyRiskReport):
    """
    Membuat atau memperbarui item report dari seluruh risk event di reassessment.
    Snapshot diambil dari assessment dan progress treatment pada periode yang sama.
    """
    risk_events = report.reassessment.risk_events.select_related("km_item").all()

    for risk_event in risk_events:
        assessments = {
            a.risk_type: a
            for a in risk_event.assessments.select_related(
                "skala_dampak", "skala_probabilitas"
            ).filter(periode=report.periode)
        }
        inherent = assessments.get("inherent")
        residual = assessments.get("residual")
        target = assessments.get("target_residual")

        progress = None
        treatment_plan = risk_event.treatment_plans.order_by("id").first()
        if treatment_plan:
            progress = treatment_plan.progress_list.filter(periode=report.periode).first()

        item, _ = MonthlyRiskReportItem.objects.update_or_create(
            report=report,
            risk_event=risk_event,
            defaults={
                "km_item": risk_event.km_item,
                "inherent_skala_dampak": getattr(inherent, "skala_dampak", None),
                "inherent_skala_probabilitas": getattr(inherent, "skala_probabilitas", None),
                "inherent_level": getattr(inherent, "level_risiko", None),
                "residual_skala_dampak": getattr(residual, "skala_dampak", None),
                "residual_skala_probabilitas": getattr(residual, "skala_probabilitas", None),
                "residual_level": getattr(residual, "level_risiko", None),
                "target_residual_level": getattr(target, "level_risiko", None),
                "mitigation_progress_percent": getattr(progress, "persentase_progress", None),
                "mitigation_status": getattr(progress, "status_realisasi", None),
            },
        )
        item.full_clean()
        item.save()

    refresh_monthly_report_summary(report)
    return report


@transaction.atomic
def refresh_monthly_report_summary(report: MonthlyRiskReport):
    items = report.items.all()

    report.total_risiko = items.count()
    report.total_high = items.filter(residual_level__gte=15).count()
    report.total_selesai = items.filter(mitigation_status="done").count()
    report.total_mitigasi_terlambat = items.filter(mitigation_status="delayed").count()

    top_items = items.filter(residual_level__gte=12).select_related("risk_event")[:5]
    if top_items:
        report.summary_risiko = "; ".join(
            [
                f"{item.risk_event.no_risiko} - {item.risk_event.peristiwa_risiko[:80]}"
                for item in top_items
            ]
        )

    report.save(update_fields=[
        "total_risiko",
        "total_high",
        "total_selesai",
        "total_mitigasi_terlambat",
        "summary_risiko",
        "updated_at",
    ])
    return report


@transaction.atomic
def submit_monthly_report(report: MonthlyRiskReport, user, note: str = ""):
    issues = validate_report_alignment(report)
    if issues:
        raise ValidationError({"report": issues})

    report.status = "submitted"
    report.submitted_at = timezone.now()
    report.save(update_fields=["status", "submitted_at", "updated_at"])
    MonthlyRiskReportSubmissionLog.objects.create(
        report=report,
        action="submit",
        action_by=user,
        note=note,
    )
    return report


@transaction.atomic
def approve_monthly_report(report: MonthlyRiskReport, user, note: str = ""):
    report.status = "approved"
    report.approved_by = user
    report.approved_at = timezone.now()
    report.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    MonthlyRiskReportSubmissionLog.objects.create(
        report=report,
        action="approve",
        action_by=user,
        note=note,
    )
    return report


def validate_report_alignment(report: MonthlyRiskReport):
    issues = []

    if report.unit_id != report.reassessment.unit_id:
        issues.append("Unit laporan tidak sama dengan unit reassessment.")
    if report.periode_id != report.reassessment.periode_id:
        issues.append("Periode laporan tidak sama dengan periode reassessment.")
    if report.kontrak_manajemen_id != report.reassessment.kontrak_manajemen_id:
        issues.append("Kontrak manajemen laporan tidak sama dengan reassessment.")

    for item in report.items.select_related("risk_event", "km_item"):
        if item.risk_event.reassessment_id != report.reassessment_id:
            issues.append(
                f"Risk {item.risk_event.no_risiko} tidak berasal dari reassessment report ini."
            )
        if not item.km_item_id:
            issues.append(f"Risk {item.risk_event.no_risiko} belum terhubung ke KM.")
        if item.target_residual_level and item.residual_level:
            if item.residual_level > item.target_residual_level and not item.escalation_note:
                issues.append(
                    f"Risk {item.risk_event.no_risiko} residual masih di atas target dan belum ada escalation note."
                )

    return issues
