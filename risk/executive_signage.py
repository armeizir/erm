from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render

from corporate_risk.models import (
    MonteCarloMetricHistory,
    MultiMetricMonteCarloResult,
    RiskMetric,
)
from risk.services.permissions import get_accessible_corporate_risk_items
from monthly_report.models import MonthlyRiskReportItem


MONTH_NAMES = {
    1: "Januari", 2: "Februari", 3: "Maret", 4: "April", 5: "Mei", 6: "Juni",
    7: "Juli", 8: "Agustus", 9: "September", 10: "Oktober", 11: "November", 12: "Desember",
}


def _decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _num(value):
    value = _decimal(value)
    if value is None:
        return None
    return float(value)


def _plain_number(value):
    value = _decimal(value)
    if value is None:
        return "–"
    if value == value.to_integral():
        return f"{int(value):,}".replace(",", ".")
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _compact_number(value):
    value = _decimal(value)
    if value is None:
        return "–"
    absolute = abs(value)
    suffix = ""
    divisor = Decimal("1")
    if absolute >= Decimal("1000000000000"):
        suffix, divisor = " T", Decimal("1000000000000")
    elif absolute >= Decimal("1000000000"):
        suffix, divisor = " Miliar", Decimal("1000000000")
    elif absolute >= Decimal("1000000"):
        suffix, divisor = " Juta", Decimal("1000000")
    scaled = value / divisor
    text = f"{scaled:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    text = text.rstrip("0").rstrip(",")
    return f"{text}{suffix}"


def _format_value(value, unit=""):
    if value in (None, ""):
        return "–"
    unit_text = (unit or "").strip()
    normalized = unit_text.lower().replace(" ", "")
    compact = _compact_number(value)
    if normalized.startswith("rp") or "rupiah" in normalized:
        return f"Rp {compact}"
    if normalized.startswith("usd"):
        remainder = unit_text[3:].strip(" /-")
        suffix = f" / {remainder}" if remainder else ""
        return f"USD {_plain_number(value)}{suffix}"
    if unit_text == "%" or "persen" in normalized:
        return f"{_plain_number(value)}%"
    return f"{_plain_number(value)}{(' ' + unit_text) if unit_text else ''}"


def _risk_status(risk, metric=None, actual=None, target=None):
    actual = _decimal(actual)
    target = _decimal(target)
    if metric is not None and actual is not None and target not in (None, Decimal("0")):
        ratio = actual / target
        if metric.direction == RiskMetric.DIRECTION_DECREASE:
            if ratio < Decimal("1"):
                return "BAHAYA", "danger"
            if ratio <= Decimal("1.05"):
                return "HATI-HATI", "warning"
            return "TERKENDALI", "safe"
        if ratio > Decimal("1"):
            return "BAHAYA", "danger"
        if ratio >= Decimal("0.95"):
            return "HATI-HATI", "warning"
        return "TERKENDALI", "safe"

    level = (risk.get_level_name("residual") or "").lower()
    if "very high" in level or "sangat tinggi" in level or level.strip() == "high" or "tinggi" in level:
        return "BAHAYA", "danger"
    if "moderate" in level or "moderat" in level or "sedang" in level:
        return "HATI-HATI", "warning"
    if level:
        return "TERKENDALI", "safe"
    if risk.status:
        text = str(risk.status).strip().upper()
        return text, "neutral"
    return "BELUM DINILAI", "neutral"


def _trend(current, previous, direction="increase"):
    current = _decimal(current)
    previous = _decimal(previous)
    if current is None or previous is None:
        return "flat"
    if current == previous:
        return "flat"
    rising = current > previous
    adverse = rising if direction == RiskMetric.DIRECTION_INCREASE else not rising
    return "up" if adverse else "down"


def _metric_rows(risk, year):
    metrics = list(
        RiskMetric.objects.filter(corporate_risk_item=risk, is_active=True)
        .select_related("rkap_item")
        .order_by("-is_target_metric", "name")
    )
    rows = []
    primary = None
    primary_latest = None
    primary_previous = None

    for metric in metrics:
        histories = list(
            MonteCarloMetricHistory.objects.filter(metric=metric, tanggal_data__year=year)
            .select_related("periode")
            .order_by("-tanggal_data", "-id")[:2]
        )
        latest = histories[0] if histories else None
        previous = histories[1] if len(histories) > 1 else None
        target = metric.effective_target_value
        if latest and latest.target_value is not None:
            target = latest.target_value
        status, status_class = _risk_status(
            risk,
            metric=metric,
            actual=latest.metric_value if latest else None,
            target=target,
        )
        row = {
            "name": metric.name,
            "unit": metric.unit or "",
            "target": _format_value(target, metric.unit),
            "target_raw": _num(target),
            "actual": _format_value(latest.metric_value if latest else None, metric.unit),
            "actual_raw": _num(latest.metric_value) if latest else None,
            "previous_raw": _num(previous.metric_value) if previous else None,
            "trend": _trend(
                latest.metric_value if latest else None,
                previous.metric_value if previous else None,
                metric.direction,
            ),
            "status": status,
            "status_class": status_class,
            "date": latest.tanggal_data.isoformat() if latest else "",
            "month": MONTH_NAMES.get(latest.tanggal_data.month, "") if latest else "",
            "is_target": metric.is_target_metric,
        }
        rows.append(row)
        if primary is None or metric.is_target_metric:
            primary = metric
            primary_latest = latest
            primary_previous = previous
            if metric.is_target_metric:
                # The first target metric is the executive headline metric.
                pass

    return metrics, rows, primary, primary_latest, primary_previous



def _kri_status_class(value):
    text = str(value or "").lower()
    if any(token in text for token in ("merah", "bahaya", "red", "danger")):
        return "danger"
    if any(token in text for token in ("kuning", "hati", "warning", "waspada")):
        return "warning"
    if any(token in text for token in ("hijau", "aman", "green", "safe")):
        return "safe"
    return "neutral"


def _source_kri_rows(risk, year):
    rows = []
    for source in risk.sumber_risiko.all():
        event = source.reassessment_item
        histories = list(
            MonthlyRiskReportItem.objects.filter(
                risk_event=event,
                report__periode__tanggal_mulai__year=year,
            )
            .select_related("report", "report__periode")
            .order_by("-report__periode__tanggal_mulai", "-report__versi", "-id")[:2]
        )
        latest = histories[0] if histories else None
        previous = histories[1] if len(histories) > 1 else None
        value = latest.realisasi_nilai_kri if latest else None
        previous_value = previous.realisasi_nilai_kri if previous else None
        status = latest.realisasi_threshold_kri if latest else ""
        direction = getattr(event, "kri_threshold_direction", "increase") or "increase"
        risk_direction = (
            RiskMetric.DIRECTION_DECREASE
            if "decrease" in str(direction).lower() or "menurun" in str(direction).lower()
            else RiskMetric.DIRECTION_INCREASE
        )
        unit = getattr(event, "unit_satuan_kri", "") or ""
        rows.append({
            "name": event.key_risk_indicators or source.penyebab_risiko or event.penyebab_risiko or event.peristiwa_risiko,
            "target": event.threshold_hati_hati or event.threshold_bahaya or event.threshold_aman or "–",
            "actual": _format_value(value, unit),
            "trend": _trend(value, previous_value, risk_direction),
            "status": status or "KRI",
            "status_class": _kri_status_class(status),
            "threshold_warning": event.threshold_hati_hati or "–",
            "threshold_danger": event.threshold_bahaya or "–",
            "unit": unit,
        })
    return rows

def _cause_rows(risk):
    rows = []
    for cause in risk.daftar_penyebab.all().order_by("urutan")[:6]:
        rows.append({
            "name": cause.key_risk_indicators or cause.penyebab_risiko or f"Penyebab {cause.no_penyebab_risiko or cause.urutan}",
            "target": cause.threshold_aman or "–",
            "actual": "–",
            "trend": "flat",
            "status": "KRI",
            "status_class": "neutral",
            "threshold_warning": cause.threshold_hati_hati or "–",
            "threshold_danger": cause.threshold_bahaya or "–",
            "unit": cause.unit_satuan_kri or "",
        })
    return rows


def _latest_montecarlo(risk, year):
    return (
        MultiMetricMonteCarloResult.objects.filter(
            corporate_risk_item=risk,
            forecast_periode__tahun_buku__tahun=year,
        )
        .select_related("forecast_periode")
        .order_by("-forecast_periode__tanggal_mulai", "-created_at")
        .first()
    )


def _management_decisions(risk):
    decisions = []
    for item in risk.rencana_perlakuan_items.all().order_by("urutan")[:4]:
        text = (item.rencana_perlakuan_risiko or "").strip()
        if text:
            decisions.append(text)
    return decisions


def _explanation(status_label, actual, target, month_label):
    actual = _decimal(actual)
    target = _decimal(target)
    if actual is None or target in (None, Decimal("0")):
        return "Status mengikuti posisi risiko residual karena metric target belum lengkap."
    gap_pct = abs((actual - target) / target * Decimal("100"))
    gap = f"{gap_pct:.1f}".replace(".", ",")
    if status_label == "BAHAYA":
        return f"Posisi {month_label} telah melewati trigger/target utama sekitar {gap}%."
    if status_label == "HATI-HATI":
        return f"Posisi {month_label} mendekati trigger/target utama; deviasi sekitar {gap}%."
    return f"Posisi {month_label} masih memiliki headroom sekitar {gap}% terhadap trigger/target utama."


def _build_risk_card(risk, year):
    metrics, rows, primary, latest, previous = _metric_rows(risk, year)
    if not rows:
        rows = _source_kri_rows(risk, year)
    if not rows:
        rows = _cause_rows(risk)

    mc = _latest_montecarlo(risk, year)
    primary_target = primary.effective_target_value if primary else None
    if latest and latest.target_value is not None:
        primary_target = latest.target_value
    current_value = latest.metric_value if latest else None
    previous_value = previous.metric_value if previous else None

    target_analysis = (mc.simulation_snapshot or {}).get("target_analysis", {}) if mc else {}
    ytd_value = target_analysis.get("actual_total") if mc else None
    if ytd_value in (None, ""):
        ytd_value = current_value

    period_month = latest.tanggal_data.month if latest else None
    period_label = f"{MONTH_NAMES.get(period_month, 'Periode')} {year}" if period_month else str(year)
    status_label, status_class = _risk_status(risk, primary, current_value, primary_target)

    causes = list(risk.daftar_penyebab.all().order_by("urutan"))
    trigger_parts = []
    if primary_target is not None:
        comparator = ">" if not primary or primary.direction == RiskMetric.DIRECTION_INCREASE else "<"
        trigger_parts.append(f"{comparator} {_format_value(primary_target, primary.unit if primary else '')}")
    for cause in causes[:2]:
        if cause.threshold_bahaya:
            label = cause.key_risk_indicators or cause.no_penyebab_risiko or "KRI"
            trigger_parts.append(f"{label}: {cause.threshold_bahaya}")

    forecast_value = mc.forecast_total if mc else None
    forecast_unit = primary.unit if primary else ""
    worst_case = mc.worst_case_value if mc else None
    potential_loss = mc.potential_loss if mc else None

    return {
        "id": risk.pk,
        "number": risk.no_risiko or risk.no_item or risk.pk,
        "title": risk.peristiwa_risiko,
        "description": risk.deskripsi_peristiwa_risiko or "",
        "year": year,
        "period_label": period_label,
        "current_month": MONTH_NAMES.get(period_month, "Periode"),
        "unit": primary.unit if primary else "",
        "ytd": _format_value(ytd_value, primary.unit if primary else ""),
        "current": _format_value(current_value, primary.unit if primary else ""),
        "previous": _format_value(previous_value, primary.unit if primary else ""),
        "target": _format_value(primary_target, primary.unit if primary else ""),
        "status": status_label,
        "status_class": status_class,
        "status_note": _explanation(status_label, current_value, primary_target, MONTH_NAMES.get(period_month, "periode")),
        "level": risk.get_level_name("residual") or "Belum dipetakan",
        "score": risk.residual_level_risiko,
        "rows": rows[:6],
        "rows_source": "Risk Metric" if metrics else "KRI Profil Risiko",
        "forecast": _format_value(forecast_value, forecast_unit),
        "forecast_period": str(mc.forecast_periode) if mc else "Belum tersedia",
        "trigger": " atau ".join(trigger_parts) if trigger_parts else "Belum ditetapkan pada data sumber",
        "worst_case": _format_value(worst_case, forecast_unit),
        "potential_loss": _format_value(potential_loss, "Rp") if potential_loss not in (None, 0, Decimal("0")) else "–",
        "decisions": _management_decisions(risk),
    }


@login_required
@permission_required("risk.view_profilrisikokorporatitem", raise_exception=True)
def executive_risk_dashboard(request):
    base = (
        get_accessible_corporate_risk_items(request.user)
        .select_related(
            "summary", "kategori_risiko", "matrix_cell_residual", "matrix_cell_residual__level_risiko"
        )
        .prefetch_related(
            "daftar_penyebab", "daftar_penyebab__pemilik_risiko", "rencana_perlakuan_items",
            "sumber_risiko", "sumber_risiko__reassessment_item"
        )
    )
    years = list(base.values_list("summary__tahun", flat=True).distinct().order_by("-summary__tahun"))
    try:
        selected_year = int(request.GET.get("year") or (years[0] if years else 0))
    except (TypeError, ValueError):
        selected_year = years[0] if years else 0

    risks = list(base.filter(summary__tahun=selected_year).order_by("no_risiko", "no_item", "id"))
    selected_id = request.GET.get("risk")
    selected = None
    if selected_id:
        try:
            selected_pk = int(selected_id)
            selected = next((item for item in risks if item.pk == selected_pk), None)
        except (TypeError, ValueError):
            selected = None
    if selected is None and risks:
        selected = risks[0]

    risk_card = _build_risk_card(selected, selected_year) if selected else None
    rotation = [{"id": item.pk, "number": item.no_risiko or item.no_item or item.pk, "title": item.peristiwa_risiko} for item in risks]

    context = {
        "page_title": "Executive Risk Dashboard",
        "years": years,
        "selected_year": selected_year,
        "risks": risks,
        "risk_card": risk_card,
        "rotation": rotation,
        "tv_mode": request.GET.get("tv") in {"1", "true", "yes"},
    }
    return render(request, "executive_risk_dashboard.html", context)
