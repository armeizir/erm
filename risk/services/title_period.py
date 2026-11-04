"""Select a period-specific version without changing monthly realization."""
from django.core.exceptions import ValidationError


def risk_for_report(risk, report):
    if not report.periode_id:
        return risk
    if risk.summary_id != report.reassessment_id:
        raise ValidationError("Profil risiko sumber berbeda dari laporan tujuan.")
    candidates = report.profile_items_queryset().filter(
        no_item=risk.no_item, no_risiko=risk.no_risiko,
    )
    matches = list(candidates[:2])
    if len(matches) != 1:
        raise ValidationError(
            f"Versi risiko No. {risk.no_item} untuk periode tujuan tidak tunggal. "
            "Penyalinan dibatalkan; periksa tanggal berlaku profil."
        )
    return matches[0]
