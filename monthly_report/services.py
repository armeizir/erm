import calendar
import re
from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db import transaction
from django.utils import timezone

from masterdata.models import TahunBuku
from risk.models import PenugasanUnitBisnis

from .models import (
    MonthlyRiskReport,
    MonthlyRiskReportChange,
    MonthlyRiskReportItem,
    MonthlyRiskReportKMAlignment,
    MonthlyRiskReportLossEvent,
    MonthlyRiskReportSubmissionLog,
)


MONTH_NAMES_ID = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
}


def _next_month(value):
    month_index = value.year * 12 + value.month
    year, zero_based_month = divmod(month_index, 12)
    return year, zero_based_month + 1


def _current_unit_user(unit, role):
    User = get_user_model()
    return (
        User.objects.filter(
            penugasan_unit_bisnis__unit_bisnis=unit,
            penugasan_unit_bisnis__peran=role,
            penugasan_unit_bisnis__aktif=True,
            is_active=True,
        )
        .distinct()
        .order_by("first_name", "last_name", "username")
        .first()
    )


def _copy_concrete_fields(instance, excluded):
    values = {}
    for field in instance._meta.concrete_fields:
        if field.primary_key or field.name in excluded:
            continue
        values[field.attname] = getattr(instance, field.attname)
    return values


def _next_report_code(source, year, month):
    if source.kode:
        suffix = re.compile(r"-\d{4}-\d{2}$")
        if suffix.search(source.kode):
            return suffix.sub(f"-{year:04d}-{month:02d}", source.kode)
    unit_name = source.reassessment.unit_bisnis.name
    unit_code = re.sub(r"[^A-Z0-9]+", "", unit_name.upper())
    return f"MRR-{unit_code}-{year:04d}-{month:02d}"


@transaction.atomic
def duplicate_approved_report_to_next_month(source_report, user):
    """Create a draft next-month report using an approved report as baseline."""
    source = (
        MonthlyRiskReport.objects.select_for_update()
        .select_related(
            "periode",
            "tahun_buku",
            "reassessment__unit_bisnis",
            "approved_by",
        )
        .get(pk=source_report.pk)
    )
    if source.status != "approved":
        raise ValidationError("Hanya laporan berstatus Approved yang dapat disalin.")

    next_year, next_month = _next_month(source.periode.tanggal_mulai)
    if next_year != source.reassessment.tahun:
        raise ValidationError(
            "Laporan bulan berikutnya berada pada tahun buku baru. "
            "Buat Profil Risiko tahun berikutnya terlebih dahulu."
        )

    tahun_buku, _ = TahunBuku.objects.get_or_create(
        tahun=next_year,
        defaults={"aktif": True},
    )
    last_day = calendar.monthrange(next_year, next_month)[1]
    periode, _ = tahun_buku.periodelaporan_set.get_or_create(
        kode_periode=f"{next_year}-{next_month:02d}",
        defaults={
            "nama_periode": f"{MONTH_NAMES_ID[next_month]} {next_year}",
            "jenis_periode": "bulanan",
            "tanggal_mulai": date(next_year, next_month, 1),
            "tanggal_selesai": date(next_year, next_month, last_day),
        },
    )

    existing = MonthlyRiskReport.objects.filter(
        reassessment=source.reassessment,
        periode=periode,
        versi=source.versi,
    ).first()
    if existing:
        raise ValidationError(
            f"Laporan {periode.nama_periode} untuk {source.reassessment} sudah tersedia."
        )

    unit = source.reassessment.unit_bisnis
    prepared_by = _current_unit_user(unit, PenugasanUnitBisnis.ROLE_RISK_OFFICER)
    reviewed_by = _current_unit_user(unit, PenugasanUnitBisnis.ROLE_RISK_CHAMPION)
    if not prepared_by:
        raise ValidationError(f"Risk Officer aktif untuk {unit} belum tersedia.")
    if not reviewed_by:
        raise ValidationError(f"Risk Champion aktif untuk {unit} belum tersedia.")

    code = _next_report_code(source, next_year, next_month)
    if MonthlyRiskReport.objects.filter(kode=code).exists():
        raise ValidationError(f"Kode laporan {code} sudah digunakan.")

    target = MonthlyRiskReport.objects.create(
        kode=code,
        tahun_buku=tahun_buku,
        periode=periode,
        unit=source.unit,
        kontrak_manajemen=source.kontrak_manajemen,
        reassessment=source.reassessment,
        versi=source.versi,
        status="draft",
        prepared_by=prepared_by,
        reviewed_by=reviewed_by,
        approved_by=source.approved_by,
        summary_km=source.summary_km,
        summary_rkm=source.summary_rkm,
        summary_risiko=source.summary_risiko,
        catatan_manajemen=source.catatan_manajemen,
        is_aggregated_to_corporate=False,
        aggregated_at=None,
        is_locked=False,
        copied_from=source,
        copied_by=user,
        copied_at=timezone.now(),
    )

    for source_item in source.items.select_related("km_alignment"):
        values = _copy_concrete_fields(
            source_item,
            {"report", "created_at", "updated_at"},
        )
        target_item = MonthlyRiskReportItem.objects.create(report=target, **values)
        try:
            alignment = source_item.km_alignment
        except MonthlyRiskReportKMAlignment.DoesNotExist:
            alignment = None
        if alignment:
            alignment_values = _copy_concrete_fields(
                alignment,
                {"report_item", "created_at", "updated_at"},
            )
            MonthlyRiskReportKMAlignment.objects.create(
                report_item=target_item,
                **alignment_values,
            )

    for source_change in source.changes.all():
        values = _copy_concrete_fields(
            source_change,
            {"report", "created_at", "updated_at"},
        )
        MonthlyRiskReportChange.objects.create(report=target, **values)

    for source_loss in source.loss_events.all():
        values = _copy_concrete_fields(
            source_loss,
            {"report", "created_at", "updated_at"},
        )
        MonthlyRiskReportLossEvent.objects.create(report=target, **values)

    refresh_monthly_report_summary(target)
    MonthlyRiskReportSubmissionLog.objects.create(
        report=target,
        action="duplicate",
        action_by=user,
        note=f"Dibuat dari laporan Approved {source.periode.nama_periode} (ID {source.pk}).",
    )
    return target


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
