from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db import transaction
from django.utils import timezone

from .models import MonthlyRiskReport, MonthlyRiskReportItem, MonthlyRiskReportSubmissionLog


@transaction.atomic
def generate_monthly_report_from_reassessment(report: MonthlyRiskReport):
    """
    Membuat atau memperbarui item report dari seluruh risk event di reassessment.
    Snapshot diambil dari assessment dan progress treatment pada periode yang sama.
    """
    risk_events = report.reassessment.item.select_related("summary").all()

    for risk_event in risk_events:
        item, _ = MonthlyRiskReportItem.objects.update_or_create(
            report=report,
            risk_event=risk_event,
            defaults={
                "issue_summary": risk_event.peristiwa_risiko,
                "next_action": risk_event.rencana_perlakuan_risiko,
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
    report.total_high = (
        items.filter(
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
        )
        .distinct()
        .count()
    )
    report.total_selesai = items.filter(mitigation_status="done").count()
    report.total_mitigasi_terlambat = items.filter(mitigation_status="delayed").count()

    top_items = (
        items.filter(
            Q(realisasi_level_risiko__icontains="tinggi")
            | Q(realisasi_skor_risiko__gte=12)
            | Q(residual_level__gte=12)
        )
        .select_related("risk_event")
        .distinct()[:5]
    )
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

    if report.tahun_buku_id and report.reassessment.tahun != report.tahun_buku.tahun:
        issues.append("Tahun buku laporan tidak sama dengan profil risiko.")

    for item in report.items.select_related("risk_event", "km_item"):
        if item.risk_event.summary_id != report.reassessment_id:
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
