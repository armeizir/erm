from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required, permission_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from corporate_risk.models import (
    MonteCarloMetricHistory,
    MultiMetricMonteCarloResult,
    RiskMetric,
)
from risk.models import AppSetting, RKAPItem
from risk.services.ai_management_decision import (
    AIManagementDecisionError,
    generate_management_decision,
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


def _accounting_number(value):
    value = _decimal(value)
    if value is None:
        return "–"
    text = _plain_number(abs(value))
    return f"({text})" if value < 0 else text


def _financial_posture(year):
    items = list(
        RKAPItem.objects.filter(
            tahun=year,
            jenis_rkap="LABA_RUGI",
            aktif=True,
        ).order_by("urutan", "kode", "id")
    )
    depth_by_id = {}
    rows = []
    for item in items:
        depth = depth_by_id.get(item.parent_id, -1) + 1
        depth_by_id[item.pk] = depth
        rows.append({
            "kode": item.kode or "",
            "name": item.sasaran,
            "depth": depth,
            "row_type": (item.tipe_baris or "DATA").lower(),
            "audited": _accounting_number(item.nilai_audited_2024),
            "unaudited": _accounting_number(item.nilai_unaudited_2025),
            "target": _accounting_number(item.target),
            "unit": item.satuan or "",
        })
    return {
        "year": year,
        "rows": rows,
        "source": next((item.sumber_dokumen for item in items if item.sumber_dokumen), ""),
    }


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


def _metric_month_values(metric, year):
    """Return the latest stored value per month for one metric/year."""
    values = {}
    histories = (
        MonteCarloMetricHistory.objects.filter(metric=metric, tanggal_data__year=year)
        .order_by("tanggal_data", "id")
    )
    for history in histories:
        value = _decimal(history.metric_value)
        if value is None:
            continue
        values[history.tanggal_data.month] = {
            "date": history.tanggal_data,
            "value": value,
        }
    return values


def _linked_ratio_actuals(metric, year):
    """Derive monthly and YTD actuals for a linked RATIO metric.

    The metric's own legacy history may stop earlier than the linked numerator and
    denominator.  Executive Risk therefore derives the ratio from the latest common
    month instead of displaying a stale/summed rate.
    """
    if not metric or metric.aggregation_type != RiskMetric.AGGREGATION_RATIO:
        return None
    if not metric.ratio_numerator_metric_id or not metric.ratio_denominator_metric_id:
        return None

    numerator_values = _metric_month_values(metric.ratio_numerator_metric, year)
    denominator_values = _metric_month_values(metric.ratio_denominator_metric, year)
    common_months = sorted(set(numerator_values) & set(denominator_values))
    if not common_months:
        return None

    monthly = []
    cumulative_num = Decimal("0")
    cumulative_den = Decimal("0")
    for month in common_months:
        num = numerator_values[month]["value"]
        den = denominator_values[month]["value"]
        if den == 0:
            continue
        cumulative_num += num
        cumulative_den += den
        monthly.append({
            "month": month,
            "date": max(numerator_values[month]["date"], denominator_values[month]["date"]),
            "current": num / den,
            "ytd": cumulative_num / cumulative_den if cumulative_den else None,
        })

    if not monthly:
        return None
    latest = monthly[-1]
    previous = monthly[-2] if len(monthly) > 1 else None
    return {
        "current": latest["current"],
        "previous": previous["current"] if previous else None,
        "ytd": latest["ytd"],
        "month": latest["month"],
        "date": latest["date"],
    }


def _rate_actuals(metric, year):
    """Return current/previous and YTD arithmetic mean for a RATE metric.

    RATE values are period rates, so YTD must not be summed.  For the currently
    validated gas-price model, the annual/YTD semantic is the arithmetic mean of
    monthly rates, matching the workbook's AVERAGE(monthly rate) definition.
    """
    if not metric or metric.aggregation_type != RiskMetric.AGGREGATION_RATE:
        return None
    values = _metric_month_values(metric, year)
    months = sorted(values)
    if not months:
        return None
    monthly = [values[month]["value"] for month in months]
    latest_month = months[-1]
    previous_month = months[-2] if len(months) > 1 else None
    return {
        "current": values[latest_month]["value"],
        "previous": values[previous_month]["value"] if previous_month else None,
        "ytd": sum(monthly, Decimal("0")) / Decimal(len(monthly)),
        "month": latest_month,
        "date": values[latest_month]["date"],
    }



def _sum_actuals(metric, year):
    # Return current/previous and YTD sum for a SUM metric.
    if not metric or metric.aggregation_type != RiskMetric.AGGREGATION_SUM:
        return None
    values = _metric_month_values(metric, year)
    months = sorted(values)
    if not months:
        return None
    latest_month = months[-1]
    previous_month = months[-2] if len(months) > 1 else None
    return {
        "current": values[latest_month]["value"],
        "previous": values[previous_month]["value"] if previous_month else None,
        "ytd": sum((values[month]["value"] for month in months), Decimal("0")),
        "month": latest_month,
        "date": values[latest_month]["date"],
    }

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

        ratio_actuals = _linked_ratio_actuals(metric, year)
        actual_value = ratio_actuals["current"] if ratio_actuals else (latest.metric_value if latest else None)
        previous_actual = ratio_actuals["previous"] if ratio_actuals else (previous.metric_value if previous else None)
        actual_date = ratio_actuals["date"] if ratio_actuals else (latest.tanggal_data if latest else None)
        actual_month = ratio_actuals["month"] if ratio_actuals else (latest.tanggal_data.month if latest else None)

        status, status_class = _risk_status(
            risk,
            metric=metric,
            actual=actual_value,
            target=target,
        )
        row = {
            "name": metric.name,
            "unit": metric.unit or "",
            "target": _format_value(target, metric.unit),
            "target_raw": _num(target),
            "actual": _format_value(actual_value, metric.unit),
            "actual_raw": _num(actual_value),
            "previous_raw": _num(previous_actual),
            "trend": _trend(actual_value, previous_actual, metric.direction),
            "status": status,
            "status_class": status_class,
            "date": actual_date.isoformat() if actual_date else "",
            "month": MONTH_NAMES.get(actual_month, "") if actual_month else "",
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



def _metric_snapshot_row(result, metric_id):
    if not result or not metric_id:
        return None
    for row in (result.metric_snapshot or {}).get("metrics", []) or []:
        if row.get("metric_id") == metric_id:
            return row
    return None


def _validated_imported_outlook(result, primary):
    if not result or not primary:
        return None
    snapshot = result.simulation_snapshot or {}
    if snapshot.get("simulation_mode") != "imported_assumptions":
        return None
    validation = snapshot.get("external_validation") or {}
    if validation.get("status") != "PASS":
        return None
    row = _metric_snapshot_row(result, primary.id)
    if not row:
        return None
    executive = snapshot.get("executive_risk") or {}
    direction = row.get("direction") or primary.direction
    if direction == RiskMetric.DIRECTION_INCREASE:
        worst_case = row.get("p95_total")
        best_case = row.get("p5_total")
    else:
        worst_case = row.get("p5_total")
        best_case = row.get("p95_total")
    return {
        "forecast": row.get("p50_total"),
        "worst_case": worst_case,
        "best_case": best_case,
        "worst_case_percentile": "P95" if direction == RiskMetric.DIRECTION_INCREASE else "P5",
        "forecast_period": str(result.forecast_periode),
        "probability_not_achieve": executive.get("probability_not_achieve_target"),
        "potential_impact": executive.get("impact_worst_case"),
        "impact_metric_name": executive.get("impact_metric_name") or "",
        "validation_status": validation.get("status"),
        "validation_source": validation.get("source") or "Crystal Ball",
        "source_sha256": (validation.get("source_sha256") or [""])[0],
        "result_id": result.id,
    }


def _linked_ratio_outlook(metric, year):
    if not metric or metric.aggregation_type != RiskMetric.AGGREGATION_RATIO:
        return None
    if not metric.ratio_numerator_metric_id or not metric.ratio_denominator_metric_id:
        return None
    numerator = metric.ratio_numerator_metric
    denominator = metric.ratio_denominator_metric
    if numerator.corporate_risk_item_id != denominator.corporate_risk_item_id:
        return None

    source_result = _latest_montecarlo(numerator.corporate_risk_item, year)
    if not source_result:
        return None
    snapshot = source_result.simulation_snapshot or {}
    validation = snapshot.get("external_validation") or {}
    if snapshot.get("simulation_mode") != "imported_assumptions" or validation.get("status") != "PASS":
        return None

    numerator_row = _metric_snapshot_row(source_result, numerator.id)
    denominator_row = _metric_snapshot_row(source_result, denominator.id)
    if not numerator_row or not denominator_row:
        return None

    def ratio(key):
        den = _num(denominator_row.get(key))
        num = _num(numerator_row.get(key))
        if den in (None, 0) or num is None:
            return None
        return num / den

    return {
        "forecast": ratio("p50_total"),
        "worst_case": ratio("p5_total"),
        "best_case": ratio("p95_total"),
        "forecast_period": str(source_result.forecast_periode),
        "probability_not_achieve": None,
        "potential_impact": None,
        "impact_metric_name": "",
        "validation_status": validation.get("status"),
        "validation_source": f"{validation.get('source') or 'Crystal Ball'} · derived RATIO",
        "source_sha256": (validation.get("source_sha256") or [""])[0],
        "result_id": source_result.id,
    }


def _forecast_status(metric, forecast_value, target_value, probability_not_achieve=None):
    # V4.9.2 — target achievement is a direction-aware hard gate.
    forecast = _decimal(forecast_value)
    target = _decimal(target_value)

    if (
        metric is not None
        and forecast is not None
        and target not in (None, Decimal("0"))
    ):
        if metric.direction == RiskMetric.DIRECTION_INCREASE:
            target_failed = forecast > target
        else:
            target_failed = forecast < target

        if target_failed:
            return "BAHAYA", "danger"

    probability = _decimal(probability_not_achieve)
    if probability is not None:
        appetite = _decimal(getattr(metric, "risk_appetite_threshold", None)) or Decimal("20")
        if probability >= Decimal("80"):
            return "BAHAYA", "danger"
        if probability >= appetite:
            return "HATI-HATI", "warning"
        return "TERKENDALI", "safe"

    return _risk_status(metric.corporate_risk_item, metric, forecast_value, target_value)


def _management_decisions(risk):
    decisions = []
    for item in risk.rencana_perlakuan_items.all().order_by("urutan")[:4]:
        text = (item.rencana_perlakuan_risiko or "").strip()
        if text:
            decisions.append(text)
    return decisions


def _ai_decision_context(risk, year, card):
    """Build the minimum decision-support context sent to the configured AI provider."""
    causes = []
    for cause in risk.daftar_penyebab.all().order_by("urutan")[:6]:
        causes.append({
            "cause": (cause.penyebab_risiko or "").strip(),
            "kri": (cause.key_risk_indicators or "").strip(),
            "danger_threshold": (cause.threshold_bahaya or "").strip(),
            "existing_control": (cause.existing_control or "").strip(),
            "control_effectiveness": str(cause.penilaian_efektivitas_kontrol or ""),
            "impact": (cause.deskripsi_dampak or "").strip(),
        })

    treatments = []
    for item in risk.rencana_perlakuan_items.all().order_by("urutan")[:6]:
        text = (item.rencana_perlakuan_risiko or "").strip()
        if text:
            treatments.append({
                "plan": text,
                "output": (item.output_perlakuan_risiko or "").strip(),
            })

    indicators = []
    for row in (card.get("rows") or [])[:6]:
        indicators.append({
            "name": row.get("name"),
            "target": row.get("target"),
            "actual": row.get("actual"),
            "trend": row.get("trend"),
        })

    return {
        "risk": {
            "number": card.get("number"),
            "event": card.get("title"),
            "description": card.get("description"),
            "year": year,
            "residual_level": card.get("level"),
            "status": card.get("status"),
        },
        "executive_position": {
            "period": card.get("period_label"),
            "ytd": card.get("ytd"),
            "current": card.get("current"),
            "target": card.get("target"),
            "forecast": card.get("forecast"),
            "worst_case": card.get("worst_case"),
            "probability_not_achieve": card.get("probability_not_achieve"),
            "potential_impact": card.get("potential_loss"),
            "model_validation": card.get("model_validation"),
            "model_source": card.get("model_source"),
        },
        "indicators": indicators,
        "causes_controls": causes,
        "existing_treatments": treatments,
    }


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
    ratio_actuals = _linked_ratio_actuals(primary, year) if primary else None
    rate_actuals = _rate_actuals(primary, year) if primary else None
    sum_actuals = _sum_actuals(primary, year) if primary else None
    if ratio_actuals:
        current_value = ratio_actuals["current"]
        previous_value = ratio_actuals["previous"]
    elif rate_actuals:
        current_value = rate_actuals["current"]
        previous_value = rate_actuals["previous"]
    elif sum_actuals:
        current_value = sum_actuals["current"]
        previous_value = sum_actuals["previous"]

    # For SUM metrics, prefer a validated imported-assumption result. For RATIO metrics,
    # derive the forecast from linked numerator/denominator metrics so legacy summed-rate
    # results (e.g. ~19k Rp/kWh) never leak into Executive Risk.
    outlook = None
    if primary and primary.aggregation_type == RiskMetric.AGGREGATION_RATIO:
        outlook = _linked_ratio_outlook(primary, year)
    else:
        outlook = _validated_imported_outlook(mc, primary)

    target_analysis = (mc.simulation_snapshot or {}).get("target_analysis", {}) if mc else {}
    if primary and primary.aggregation_type == RiskMetric.AGGREGATION_RATIO and ratio_actuals:
        ytd_value = ratio_actuals["ytd"]
    elif primary and primary.aggregation_type == RiskMetric.AGGREGATION_RATE and rate_actuals:
        ytd_value = rate_actuals["ytd"]
    else:
        ytd_value = target_analysis.get("actual_total") if mc else None
        if ytd_value in (None, ""):
            ytd_value = sum_actuals["ytd"] if sum_actuals else current_value

    period_month = (
        ratio_actuals["month"] if ratio_actuals
        else rate_actuals["month"] if rate_actuals
        else latest.tanggal_data.month if latest
        else None
    )
    period_label = f"{MONTH_NAMES.get(period_month, 'Periode')} {year}" if period_month else str(year)
    if outlook:
        status_label, status_class = _forecast_status(
            primary,
            outlook.get("forecast"),
            primary_target,
            outlook.get("probability_not_achieve"),
        )
    else:
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

    mc_snapshot = (mc.simulation_snapshot or {}) if mc else {}
    imported_unvalidated = (
        mc is not None
        and mc_snapshot.get("simulation_mode") == "imported_assumptions"
        and outlook is None
    )
    fallback_mc = None if imported_unvalidated else mc

    forecast_value = outlook.get("forecast") if outlook else (fallback_mc.forecast_total if fallback_mc else None)
    forecast_unit = primary.unit if primary else ""
    worst_case = outlook.get("worst_case") if outlook else (fallback_mc.worst_case_value if fallback_mc else None)
    potential_loss = outlook.get("potential_impact") if outlook else (fallback_mc.potential_loss if fallback_mc else None)
    forecast_period = outlook.get("forecast_period") if outlook else (str(fallback_mc.forecast_periode) if fallback_mc else "Belum tersedia")

    if outlook and outlook.get("probability_not_achieve") is not None:
        probability = _decimal(outlook.get("probability_not_achieve"))
        probability_text = f"{probability:.2f}%".replace(".", ",") if probability is not None else "–"
        status_note = (
            f"Monte Carlo tervalidasi: probabilitas target tidak tercapai {probability_text}; "
            f"status memakai outlook tahunan, bukan membandingkan realisasi bulanan dengan target tahunan."
        )
    elif outlook:
        status_note = (
            f"Outlook {primary.name if primary else 'metric'} diturunkan sebagai RATE/RATIO dari model "
            f"Monte Carlo tervalidasi; target ERM tetap digunakan untuk penilaian status."
        )
        probability_text = "–"
    else:
        status_note = _explanation(status_label, current_value, primary_target, MONTH_NAMES.get(period_month, "periode"))
        probability_text = "–"

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
        "status_note": status_note,
        "level": risk.get_level_name("residual") or "Belum dipetakan",
        "score": risk.residual_level_risiko,
        "rows": rows[:6],
        "rows_source": "Risk Metric" if metrics else "KRI Profil Risiko",
        "forecast": _format_value(forecast_value, forecast_unit),
        "forecast_period": forecast_period,
        "trigger": " atau ".join(trigger_parts) if trigger_parts else "Belum ditetapkan pada data sumber",
        "worst_case": _format_value(worst_case, forecast_unit),
        "worst_case_percentile": (
            (outlook.get("worst_case_percentile") if outlook else None)
            or (
                ("P95" if primary.direction == RiskMetric.DIRECTION_INCREASE else "P5")
                if (fallback_mc is not None and primary is not None)
                else ""
            )
        ),
        "potential_loss": _format_value(potential_loss, "Rp") if potential_loss not in (None, 0, Decimal("0")) else "–",
        "probability_not_achieve": probability_text,
        "model_validation": outlook.get("validation_status") if outlook else "",
        "model_source": outlook.get("validation_source") if outlook else "",
        "monte_carlo_result_id": outlook.get("result_id") if outlook else (fallback_mc.id if fallback_mc else None),
        "decisions": _management_decisions(risk),
    }


@login_required
@permission_required("risk.change_profilrisikokorporatitem", raise_exception=True)
@require_POST
def executive_risk_ai_decision(request, risk_id):
    risk = get_object_or_404(
        get_accessible_corporate_risk_items(request.user)
        .select_related("summary", "kategori_risiko", "matrix_cell_residual", "matrix_cell_residual__level_risiko")
        .prefetch_related("daftar_penyebab", "rencana_perlakuan_items"),
        pk=risk_id,
    )

    session_key = f"ai_management_decision_last_{risk_id}"
    now = timezone.now().timestamp()
    last = request.session.get(session_key)
    if last is not None and now - float(last) < 20:
        return JsonResponse(
            {"ok": False, "error": "Tunggu sekitar 20 detik sebelum generate ulang rekomendasi AI."},
            status=429,
        )
    request.session[session_key] = now

    year = risk.summary.tahun
    card = _build_risk_card(risk, year)
    context = _ai_decision_context(risk, year, card)

    try:
        generated = generate_management_decision(context)
    except AIManagementDecisionError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)

    return JsonResponse({
        "ok": True,
        "draft": generated.payload,
        "provider": generated.provider,
        "model": generated.model,
        "notice": "AI Draft — wajib direview dan tidak otomatis menjadi Management Decision final.",
    })


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
    risk_years = list(base.values_list("summary__tahun", flat=True).distinct().order_by("-summary__tahun"))
    financial_years = list(
        RKAPItem.objects.filter(jenis_rkap="LABA_RUGI", aktif=True)
        .order_by()
        .values_list("tahun", flat=True)
        .distinct()
    )
    years = sorted(set(risk_years) | set(financial_years), reverse=True)
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
    financial_mode = request.GET.get("finance") in {"1", "true", "yes"}
    app_setting = AppSetting.get_solo()
    ai_management_enabled = bool(app_setting.ai_aktif and app_setting.ai_api_key)

    context = {
        "page_title": "Executive Risk Dashboard",
        "years": years,
        "selected_year": selected_year,
        "risks": risks,
        "risk_card": risk_card,
        "rotation": rotation,
        "tv_mode": request.GET.get("tv") in {"1", "true", "yes"},
        "financial_mode": financial_mode,
        "financial_posture": _financial_posture(selected_year) if financial_mode else None,
        "ai_management_enabled": ai_management_enabled,
        "ai_management_provider": app_setting.get_ai_provider_display() if ai_management_enabled else "",
        "ai_management_model": app_setting.ai_model if ai_management_enabled else "",
    }
    return render(request, "executive_risk_dashboard.html", context)
