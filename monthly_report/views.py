from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404

from risk.models import PenugasanUnitBisnis

from .models import MonthlyRiskReportEvidence


def _can_view_evidence(user, evidence):
    report = evidence.report
    if user.is_superuser:
        return True
    if user.pk in {report.prepared_by_id, report.reviewed_by_id, report.approved_by_id}:
        return True
    unit_id = report.reassessment.unit_bisnis_id
    if unit_id and user.groups.filter(pk=unit_id).exists():
        return True
    if unit_id and PenugasanUnitBisnis.objects.filter(
        unit_bisnis_id=unit_id, user=user, aktif=True
    ).exists():
        return True
    return user.is_staff and user.has_perm("monthly_report.view_monthlyriskreport")


@login_required
def download_evidence(request, file_name):
    evidence = get_object_or_404(
        MonthlyRiskReportEvidence.objects.select_related(
            "report__reassessment__unit_bisnis"
        ),
        file=file_name,
    )
    if not _can_view_evidence(request.user, evidence):
        raise PermissionDenied("Anda tidak memiliki akses ke eviden laporan ini.")
    try:
        evidence.file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("File eviden tidak ditemukan pada NAS.")
    return FileResponse(
        evidence.file,
        as_attachment=True,
        filename=Path(evidence.file.name).name.split("_", 1)[-1],
    )
