from __future__ import annotations

from collections import Counter

from .kpmr_aggregation import _aggregate_exposure_for_i1, normalize_no_item
from .kpmr_scoring import actual_residual_score, target_residual_score


COMPARISON_LABELS = {
    "below": "Di bawah target",
    "same": "Sama dengan target",
    "above": "Di atas target",
    "incomplete": "Data tidak lengkap",
}


def _scale_detail(value):
    if value is None:
        return None
    return {
        "id": value.pk,
        "rank": value.urutan,
        "label": str(value),
    }


def build_kpmr_diagnostics(report, report_items=None, quarter=None):
    if quarter is None:
        quarter = ((report.periode.tanggal_mulai.month - 1) // 3) + 1
    if report_items is None:
        report_items = list(
            report.items.select_related(
                "risk_event",
                "risk_event__summary",
                "risk_event__summary__risk_matrix",
                f"risk_event__skala_dampak_q{quarter}",
                f"risk_event__skala_probabilitas_q{quarter}",
                "realisasi_skala_dampak",
                "realisasi_skala_probabilitas",
            ).order_by("risk_event__no_item", "risk_event__no_risiko", "pk")
        )

    rows = []
    group_members = {}
    counts = Counter()
    seen_item_ids = set()
    for item in report_items:
        if item.pk in seen_item_ids:
            continue
        seen_item_ids.add(item.pk)
        risk = item.risk_event
        group_key = normalize_no_item(risk.no_item) or f"risk:{risk.pk}"
        group_members.setdefault(group_key, []).append(risk.no_risiko)
        target_impact = getattr(risk, f"skala_dampak_q{quarter}", None)
        target_likelihood = getattr(risk, f"skala_probabilitas_q{quarter}", None)
        actual_impact = item.realisasi_skala_dampak
        actual_likelihood = item.realisasi_skala_probabilitas
        target_score = target_residual_score(item, quarter)
        actual_score = actual_residual_score(item)
        missing = []
        for label, value in (
            ("target likelihood", target_likelihood),
            ("target impact", target_impact),
            ("target score/matrix cell", target_score),
            ("aktual likelihood", actual_likelihood),
            ("aktual impact", actual_impact),
            ("aktual score/matrix cell", actual_score),
        ):
            if value is None:
                missing.append(label)

        if missing:
            comparison = "incomplete"
        elif actual_score < target_score:
            comparison = "below"
        elif actual_score == target_score:
            comparison = "same"
        else:
            comparison = "above"
        counts[comparison] += 1
        matrix = risk.summary.risk_matrix
        rows.append({
            "item_id": item.pk,
            "risk_event_id": risk.pk,
            "no_item": risk.no_item,
            "normalized_no_item": group_key,
            "no_risiko": risk.no_risiko,
            "event": risk.peristiwa_risiko,
            "target_likelihood": _scale_detail(target_likelihood),
            "target_impact": _scale_detail(target_impact),
            "target_score": target_score,
            "actual_likelihood": _scale_detail(actual_likelihood),
            "actual_impact": _scale_detail(actual_impact),
            "actual_score": actual_score,
            "comparison": comparison,
            "comparison_label": COMPARISON_LABELS[comparison],
            "is_complete": not missing,
            "missing": missing,
            "matrix_id": matrix.pk if matrix else None,
            "matrix": str(matrix) if matrix else "-",
            "legacy_target_residual_level": item.target_residual_level,
            "legacy_actual_score": item.realisasi_skor_risiko,
            "source": (
                f"Target: ReAssessmentItem.skala_dampak_q{quarter} + "
                f"skala_probabilitas_q{quarter}; Aktual: "
                "MonthlyRiskReportItem.realisasi_skala_dampak + "
                "realisasi_skala_probabilitas; Score: RiskMatrix.get_cell().skor"
            ),
        })

    exposure = _aggregate_exposure_for_i1(report_items, quarter)
    exposure_ready = bool(
        exposure
        and exposure["comparable_group_count"] > 0
        and exposure["incomplete_group_count"] == 0
        and not exposure["conflicts"]
    )
    fallback_used = False
    if exposure is None:
        fallback_reason = "Tidak ada kelompok eksposur yang dapat dibentuk."
    elif not exposure_ready:
        fallback_reason = (
            f"Eksposur lengkap {exposure['comparable_group_count']} dari "
            f"{exposure['group_count']} kelompok; "
            f"{exposure['incomplete_group_count']} kelompok tidak lengkap dan "
            f"{len(exposure['conflicts'])} konflik."
        )
    else:
        fallback_reason = "Eksposur kelompok lengkap; fallback tidak diperlukan."

    exposure_groups = []
    raw_exposure_groups = (exposure or {}).get("groups", {})
    conflicts = (exposure or {}).get("conflicts", [])
    for group_key, members in group_members.items():
        values = raw_exposure_groups.get(group_key, {})
        missing = sorted(values.get("missing", []))
        group_conflicts = [row for row in conflicts if row["group"] == group_key]
        is_complete = not missing and not group_conflicts
        reasons = []
        if "target" in missing:
            reasons.append(
                f"ReAssessmentItem.eksposur_risiko_q{quarter} tidak ditemukan"
            )
        if "residual" in missing:
            reasons.append(
                "MonthlyRiskReportItem.realisasi_eksposur tidak ditemukan"
            )
        if group_conflicts:
            reasons.append(
                f"terdapat {len(group_conflicts)} nilai berbeda dalam kelompok"
            )
        exposure_groups.append({
            "no_item": group_key,
            "risk_count": len(members),
            "target": values.get("target"),
            "actual": values.get("residual"),
            "target_source": f"ReAssessmentItem.eksposur_risiko_q{quarter}",
            "actual_source": "MonthlyRiskReportItem.realisasi_eksposur",
            "is_complete": is_complete,
            "missing": missing,
            "reason": "; ".join(reasons) if reasons else "Data eksposur lengkap",
            "assessable": is_complete,
            "conflict_count": len(group_conflicts),
        })

    return {
        "rows": rows,
        "counts": {
            "below": counts["below"],
            "same": counts["same"],
            "above": counts["above"],
            "incomplete": counts["incomplete"],
        },
        "complete_risk_count": len(rows) - counts["incomplete"],
        "group_members": group_members,
        "exposure_groups": exposure_groups,
        "group_count": len(group_members),
        "complete_group_count": exposure["comparable_group_count"] if exposure else 0,
        "incomplete_group_count": exposure["incomplete_group_count"] if exposure else len(group_members),
        "conflict_count": len(exposure["conflicts"]) if exposure else 0,
        "exposure": exposure,
        "exposure_ready": exposure_ready,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "needs_verification": bool(counts["incomplete"]) or not exposure_ready,
    }
