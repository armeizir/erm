# BOD_EXECUTIVE_DASHBOARD_PHASE2
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET


RED_KRI_TOKENS = ("merah", "red", "bahaya", "danger")
YELLOW_KRI_TOKENS = ("kuning", "yellow", "hati-hati", "hati hati", "warning", "waspada")
GREEN_KRI_TOKENS = ("hijau", "green", "aman", "safe")
OVERDUE_TOKENS = ("overdue", "terlambat", "lewat", "delay", "late")
COMPLETE_TOKENS = ("selesai", "completed", "complete", "closed", "done", "100%")


def _txt(value):
    return str(value or "").strip()


def _norm(value):
    return " ".join(_txt(value).lower().split())


def _decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def classify_kri(value):
    text = _norm(value)
    if not text:
        return "unknown"
    if any(token in text for token in RED_KRI_TOKENS):
        return "red"
    if any(token in text for token in YELLOW_KRI_TOKENS):
        return "yellow"
    if any(token in text for token in GREEN_KRI_TOKENS):
        return "green"
    return "unknown"


def classify_level(level, score=None):
    text = _norm(level)
    score_num = _decimal(score)
    if any(token in text for token in ("sangat tinggi", "very high", "critical", "kritis")):
        return "very_high"
    if text == "high" or ("tinggi" in text and "moderate" not in text and "moderat" not in text):
        return "high"
    if any(token in text for token in ("moderate to high", "moderat ke tinggi", "moderate-high")):
        return "moderate_high"
    if any(token in text for token in ("moderate", "moderat", "sedang")):
        return "moderate"
    if any(token in text for token in ("low", "rendah")):
        return "low"
    if score_num is not None:
        if score_num >= 20:
            return "high"
        if score_num >= 16:
            return "moderate_high"
        if score_num >= 10:
            return "moderate"
        if score_num >= 1:
            return "low"
    return "unknown"


def is_overdue(status):
    text = _norm(status)
    return bool(text) and any(token in text for token in OVERDUE_TOKENS)


def is_complete(status, progress):
    p = _decimal(progress)
    if p is not None and p >= 100:
        return True
    text = _norm(status)
    return bool(text) and any(token in text for token in COMPLETE_TOKENS)


def _first_attr(obj, names, default=None):
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value not in (None, ""):
                return value
    return default


def _field_names(model):
    return {field.name for field in model._meta.get_fields()}


def _report_year_month(report):
    period = getattr(report, "periode", None)
    start = getattr(period, "tanggal_mulai", None)
    if start:
        return start.year, start.month
    return None, None


def _latest_reports_for_month(reports, month):
    candidates = [r for r in reports if _report_year_month(r)[1] == month]
    if not candidates:
        return []

    grouped = {}
    for report in candidates:
        key = (
            getattr(report, "reassessment_id", None)
            or getattr(report, "profil_risiko_id", None)
            or getattr(report, "unit_bisnis_id", None)
            or report.pk
        )
        version = getattr(report, "versi", 0) or 0
        rank = (version, report.pk)
        current = grouped.get(key)
        if current is None or rank > current[0]:
            grouped[key] = (rank, report)
    return [value[1] for value in grouped.values()]


def _risk_name(item):
    event = getattr(item, "risk_event", None)
    return _txt(_first_attr(
        event,
        (
            "peristiwa_risiko",
            "deskripsi_peristiwa_risiko",
            "nama_risiko",
            "judul",
        ),
        f"Risk Event #{getattr(item, 'risk_event_id', '-')}",
    ))


def _owner_name(item):
    value = _first_attr(item, ("realisasi_pic", "pic"), None)
    if value:
        return _txt(value)
    event = getattr(item, "risk_event", None)
    value = _first_attr(event, ("pemilik_risiko", "risk_owner", "pic"), None)
    return _txt(value) if value else "-"


def _item_snapshot(item):
    level = _first_attr(
        item,
        (
            "realisasi_level_risiko_bumn",
            "realisasi_level_risiko_kbumn",
            "realisasi_level_risiko",
        ),
    )
    score = _first_attr(item, ("realisasi_skor_risiko", "realisasi_skala_nilai_risiko_kbumn"))
    kri_status = _first_attr(item, ("realisasi_threshold_kri",))
    kri_value = _first_attr(item, ("realisasi_nilai_kri",))
    kri_threshold = _first_attr(item, ("realisasi_threshold_kri_skor",))
    treatment_status = _first_attr(item, ("status_rencana_perlakuan",))
    progress = _first_attr(item, ("progress_pelaksanaan_percent",))

    return {
        "risk": _risk_name(item),
        "owner": _owner_name(item),
        "level": _txt(level),
        "score": None if score is None else _txt(score),
        "level_class": classify_level(level, score),
        "kri_status": _txt(kri_status),
        "kri_class": classify_kri(kri_status),
        "kri_value": None if kri_value is None else _txt(kri_value),
        "kri_threshold": _txt(kri_threshold),
        "treatment_status": _txt(treatment_status),
        "progress": None if progress is None else _txt(progress),
        "overdue": is_overdue(treatment_status),
        "complete": is_complete(treatment_status, progress),
    }


def _aggregate_items(items):
    kri = defaultdict(int)
    high = 0
    overdue = 0
    completed = 0
    incomplete = 0
    signals = []

    for item in items:
        snap = _item_snapshot(item)
        kri[snap["kri_class"]] += 1

        high_flag = snap["level_class"] in {"high", "very_high"}
        if high_flag:
            high += 1

        if snap["overdue"]:
            overdue += 1

        if snap["complete"]:
            completed += 1
        elif snap["progress"] not in (None, "") or snap["treatment_status"]:
            incomplete += 1

        reasons = []
        priority = 0
        if snap["kri_class"] == "red":
            reasons.append("KRI Merah/Bahaya")
            priority += 100
        if high_flag:
            reasons.append("Residual High")
            priority += 80
        if snap["overdue"]:
            reasons.append("Mitigasi Overdue")
            priority += 60

        progress_num = _decimal(snap["progress"])
        if progress_num is not None and progress_num < 50 and not snap["complete"]:
            reasons.append(f"Progress mitigasi {progress_num}%")
            priority += 20

        if reasons:
            signals.append({
                **snap,
                "reason": " · ".join(reasons),
                "priority": priority,
                "management_action": (
                    "Review efektivitas mitigasi, konfirmasi owner dan target penyelesaian, "
                    "serta tetapkan kebutuhan eskalasi pada forum manajemen."
                ),
            })

    signals.sort(key=lambda x: (-x["priority"], x["risk"]))
    return {
        "high_risk": high,
        "kri": {
            "red": kri["red"],
            "yellow": kri["yellow"],
            "green": kri["green"],
            "unknown": kri["unknown"],
        },
        "mitigation": {
            "completed": completed,
            "incomplete": incomplete,
            "overdue": overdue,
        },
        "signals": signals[:8],
    }


@require_GET
@login_required
def bod_phase2_api(request):
    Report = apps.get_model("monthly_report", "MonthlyRiskReport")
    report_fields = _field_names(Report)

    try:
        year = int(request.GET.get("tahun") or 0)
    except ValueError:
        year = 0
    if year <= 0:
        from django.utils import timezone
        year = timezone.localdate().year

    try:
        requested_month = int(request.GET.get("bulan") or 0)
    except ValueError:
        requested_month = 0

    qs = Report.objects.all()
    if "periode" in report_fields:
        qs = qs.select_related("periode").filter(periode__tanggal_mulai__year=year)
    if "reassessment" in report_fields:
        qs = qs.select_related("reassessment")

    reports = list(qs.order_by("pk"))

    available_months = sorted({
        month
        for report in reports
        for _, month in [_report_year_month(report)]
        if month
    })

    selected_month = (
        requested_month
        if requested_month in available_months
        else (available_months[-1] if available_months else None)
    )

    selected_reports = _latest_reports_for_month(reports, selected_month) if selected_month else []

    selected_items = []
    for report in selected_reports:
        accessor = getattr(report, "items", None)
        if accessor is None:
            continue
        selected_items.extend(list(accessor.select_related("risk_event").all()))

    aggregate = _aggregate_items(selected_items)

    trend = []
    for month in available_months:
        month_reports = _latest_reports_for_month(reports, month)
        month_items = []
        for report in month_reports:
            accessor = getattr(report, "items", None)
            if accessor is None:
                continue
            month_items.extend(list(accessor.select_related("risk_event").all()))
        month_agg = _aggregate_items(month_items)
        trend.append({
            "month": month,
            "high_risk": month_agg["high_risk"],
            "kri_red": month_agg["kri"]["red"],
        })

    # BOD_EXECUTIVE_DASHBOARD_PHASE3_V3
    # Risk appetite is defined on corporate_risk.RiskMetric as
    # "probabilitas target tidak tercapai (%)". It is NOT a residual 5x5 score.
    RiskMetric = apps.get_model("corporate_risk", "RiskMetric")
    MultiResult = apps.get_model("corporate_risk", "MultiMetricMonteCarloResult")
    SingleResult = apps.get_model("corporate_risk", "MonteCarloKorporatResult")

    metrics = list(
        RiskMetric.objects
        .filter(is_active=True)
        .select_related("corporate_risk_item")
    )

    metrics_by_risk = defaultdict(list)
    for metric in metrics:
        metrics_by_risk[metric.corporate_risk_item_id].append(metric)

    def latest_result_map(model):
        qs = model.objects.select_related("corporate_risk_item", "forecast_periode")
        try:
            qs = qs.filter(forecast_periode__tanggal_mulai__year=year)
        except Exception:
            pass

        result_map = {}
        for result in qs.order_by("-pk"):
            risk_id = result.corporate_risk_item_id
            probability = getattr(result, "probability_not_achieve_target", None)
            if risk_id not in result_map and probability is not None:
                result_map[risk_id] = result
        return result_map

    latest_multi = latest_result_map(MultiResult)
    latest_single = latest_result_map(SingleResult)

    appetite_assessments = []
    for risk_id, risk_metrics in sorted(metrics_by_risk.items()):
        target_metric = next((m for m in risk_metrics if m.is_target_metric), None)
        source_metric = target_metric or risk_metrics[0]
        threshold = _decimal(source_metric.risk_appetite_threshold)

        result = latest_multi.get(risk_id) or latest_single.get(risk_id)
        probability = (
            _decimal(getattr(result, "probability_not_achieve_target", None))
            if result is not None
            else None
        )

        if threshold is None or probability is None:
            status = "not_assessed"
            headroom = None
        elif probability <= threshold:
            status = "within"
            headroom = threshold - probability
        else:
            status = "breach"
            headroom = threshold - probability

        label = str(source_metric.corporate_risk_item).split("|", 1)[0].strip()

        appetite_assessments.append({
            "corporate_risk_item_id": risk_id,
            "risk": label,
            "metric_name": source_metric.name,
            "is_target_metric": bool(source_metric.is_target_metric),
            "threshold": None if threshold is None else str(threshold),
            "probability_not_achieve": None if probability is None else str(probability),
            "status": status,
            "headroom": None if headroom is None else str(headroom),
            "result_source": (
                "MultiMetric"
                if result is not None and result.__class__ is MultiResult
                else ("SingleMetric" if result is not None else None)
            ),
            "result_id": getattr(result, "pk", None),
            "target_status": _txt(getattr(result, "target_status", "")) if result is not None else "",
        })

    appetite_total_metrics = len(metrics)
    appetite_covered_risks = len(metrics_by_risk)
    appetite_assessed = sum(
        1 for row in appetite_assessments if row["status"] in {"within", "breach"}
    )
    appetite_within = sum(
        1 for row in appetite_assessments if row["status"] == "within"
    )
    appetite_breach = sum(
        1 for row in appetite_assessments if row["status"] == "breach"
    )
    appetite_not_assessed = sum(
        1 for row in appetite_assessments if row["status"] == "not_assessed"
    )
    appetite_value_filled = sum(
        1 for metric in metrics if metric.risk_appetite_value is not None
    )

    effectiveness = defaultdict(int)
    kri_nonblank = 0
    kri_recognized = 0

    for item in selected_items:
        raw_effectiveness = _norm(
            getattr(item, "efektivitas_perlakuan_risiko", None)
        )
        normalized = raw_effectiveness.replace("-", "_").replace(" ", "_")

        if not normalized:
            effectiveness["not_assessed"] += 1
        elif "tidak_efektif" in normalized or "ineffective" in normalized:
            effectiveness["ineffective"] += 1
        elif "cukup_efektif" in normalized or "partially_effective" in normalized:
            effectiveness["adequate"] += 1
        elif normalized in {"efektif", "effective"}:
            effectiveness["effective"] += 1
        else:
            effectiveness["other"] += 1

        kri_status = _first_attr(item, ("realisasi_threshold_kri",))
        if kri_status not in (None, ""):
            kri_nonblank += 1
            if classify_kri(kri_status) in {"red", "yellow", "green"}:
                kri_recognized += 1

    corporate_contribution = sum(
        1
        for item in selected_items
        if bool(getattr(item, "contributes_to_corporate", False))
    )

    return JsonResponse({
        "ok": True,
        "year": year,
        "selected_month": selected_month,
        "available_months": available_months,
        "reports_used": len(selected_reports),
        "items_used": len(selected_items),
        "high_risk": aggregate["high_risk"],
        "kri": aggregate["kri"],
        "mitigation": aggregate["mitigation"],
        "decision_required": len(aggregate["signals"]),
        "signals": aggregate["signals"],
        "trend": trend,
        "risk_appetite": {
            "integrated": appetite_total_metrics > 0,
            "status": "partial" if appetite_total_metrics > 0 else "not_integrated",
            "total_metrics": appetite_total_metrics,
            "covered_corporate_risks": appetite_covered_risks,
            "value_filled": appetite_value_filled,
            "assessed": appetite_assessed,
            "within": appetite_within,
            "breach": appetite_breach,
            "not_assessed": appetite_not_assessed,
            "threshold_meaning": "Probabilitas target tidak tercapai (%)",
            "assessments": appetite_assessments,
            "note": (
                "Status appetite membandingkan probability_not_achieve_target "
                "hasil Monte Carlo dengan risk_appetite_threshold. "
                "Threshold ini bukan skor residual matriks 5x5."
            ),
        },
        "treatment_effectiveness": {
            "effective": effectiveness["effective"],
            "adequate": effectiveness["adequate"],
            "ineffective": effectiveness["ineffective"],
            "other": effectiveness["other"],
            "not_assessed": effectiveness["not_assessed"],
        },
        "kri_quality": {
            "nonblank": kri_nonblank,
            "recognized": kri_recognized,
            "unknown": max(0, kri_nonblank - kri_recognized),
        },
        "corporate_contribution": corporate_contribution,
    })
