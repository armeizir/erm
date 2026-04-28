from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any
import math
import random

from decimal import Decimal

from django.db import transaction

from .models import (
    MonteCarloKorporatConfig,
    MonteCarloKorporatHistory,
    MonteCarloKorporatResult,
    AIInsightKorporat,
    RiskMetric,
    MonteCarloMetricHistory,
    MultiMetricMonteCarloResult,
)

def _percentile(values, q):
    if not values:
        return 0.0

    values = sorted(float(v) for v in values)
    if len(values) == 1:
        return values[0]

    k = (len(values) - 1) * q
    f = math.floor(k)
    c = math.ceil(k)

    if f == c:
        return values[int(k)]

    return values[f] * (c - k) + values[c] * (k - f)


def _safe_float(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _growth_rates(values):
    rates = []

    for i in range(1, len(values)):
        prev_value = _safe_float(values[i - 1])
        current_value = _safe_float(values[i])

        if prev_value <= 0:
            continue

        rate = (current_value - prev_value) / prev_value

        if math.isfinite(rate):
            rates.append(rate)

    return rates


def _simulate_metric(values, months_ahead=9, n_simulations=1000):
    if len(values) < 3:
        raise ValueError("Data histori metric belum cukup. Minimal 3 periode.")

    values = [_safe_float(v) for v in values]
    rates = _growth_rates(values)

    if len(rates) < 2:
        raise ValueError("Data histori metric belum cukup untuk menghitung growth rate.")

    avg_growth = mean(rates)
    variance = mean([(r - avg_growth) ** 2 for r in rates])
    std_growth = math.sqrt(variance)

    current = values[-1]
    monthly_results = [[] for _ in range(months_ahead)]

    for _ in range(n_simulations):
        simulated = current

        for month_idx in range(months_ahead):
            sampled_growth = random.gauss(avg_growth, std_growth)

            # guardrail supaya hasil tidak terlalu liar
            sampled_growth = max(min(sampled_growth, 3.0), -0.95)

            simulated = simulated * (1 + sampled_growth)
            simulated = max(simulated, 0)

            monthly_results[month_idx].append(simulated)

    projection_rows = []
    mean_total = 0
    p80_total = 0

    for idx, month_values in enumerate(monthly_results):
        mean_value = mean(month_values)
        p20_value = _percentile(month_values, 0.20)
        p40_value = _percentile(month_values, 0.40)
        p60_value = _percentile(month_values, 0.60)
        p80_value = _percentile(month_values, 0.80)

        projection_rows.append({
            "bulan_index": idx + 1,
            "mean": mean_value,
            "p20": p20_value,
            "p40": p40_value,
            "p60": p60_value,
            "p80": p80_value,
        })

        mean_total += mean_value
        p80_total += p80_value

    return {
        "actual_total": sum(values),
        "future_mean_total": mean_total,
        "full_year_expected": sum(values) + mean_total,
        "p80_total": p80_total,
        "growth_mean": avg_growth,
        "growth_std": std_growth,
        "projection_rows": projection_rows,
    }


def _normalize_metric_score(metric, projected_value, last_actual_value):
    """
    Normalisasi score ke skala 0-100 berbasis threshold.
    - increase: makin besar nilai dibanding threshold = makin berisiko
    - decrease: makin kecil nilai dibanding threshold = makin berisiko
    """

    projected_value = _safe_float(projected_value)
    threshold = _safe_float(getattr(metric, "threshold", 0))

    if threshold <= 0:
        return 0.0

    if metric.direction == "increase":
        score = (projected_value / threshold) * 100
    else:
        score = (threshold / projected_value) * 100 if projected_value > 0 else 100

    return max(0.0, min(score, 100.0))


def _status_from_score(score):
    score = _safe_float(score)

    if score <= 20:
        return "Rendah"
    if score <= 40:
        return "Moderat"
    if score <= 60:
        return "Tinggi"
    if score <= 80:
        return "Sangat Tinggi"

    return "Ekstrem"


@transaction.atomic
def run_multi_metric_monte_carlo_for_korporat_item(
    item,
    forecast_periode,
    months_ahead=9,
    n_simulations=1000,
    scenario_percentile=80,
):
    metrics = list(
        RiskMetric.objects.filter(
            corporate_risk_item=item,
            is_active=True,
        ).order_by("name")
    )

    if not metrics:
        raise ValueError("Belum ada Risk Metric aktif untuk risiko ini.")

    metric_results = []
    total_weight = sum([_safe_float(m.weight) for m in metrics])

    if total_weight <= 0:
        total_weight = len(metrics)

    for metric in metrics:
        histories = list(
            MonteCarloMetricHistory.objects.filter(
                metric=metric,
            )
            .select_related("periode")
            .order_by("tanggal_data", "id")
        )

        if len(histories) < 3:
            raise ValueError(
                f"Data histori untuk metric '{metric.name}' belum cukup. Minimal 3 periode."
            )

        values = [_safe_float(h.metric_value) for h in histories]
        last_actual = values[-1]

        simulation = _simulate_metric(
            values=values,
            months_ahead=months_ahead,
            n_simulations=n_simulations,
        )

        mean_score = _normalize_metric_score(
            metric=metric,
            projected_value=simulation["full_year_expected"],
            last_actual_value=last_actual,
        )

        p80_score = _normalize_metric_score(
            metric=metric,
            projected_value=simulation["p80_total"],
            last_actual_value=last_actual,
        )

        weight = _safe_float(metric.weight)
        weight_ratio = weight / total_weight if total_weight else 0

        scenario_key = f"p{scenario_percentile}_total"
        scenario_total = simulation.get(scenario_key, simulation["p80_total"])

        metric_results.append({
            "metric_id": metric.id,
            "metric_name": metric.name,
            "unit": metric.unit,
            "direction": metric.direction,
            "weight": weight,
            "weight_ratio": weight_ratio,
            "last_actual": last_actual,
            "mean_score": mean_score,

            # 🔥 INI YANG DINAMIS
            "scenario_score": p80_score,
            "scenario_total": scenario_total,
            "scenario_percentile": scenario_percentile,

            "actual_total": simulation["actual_total"],
            "future_mean_total": simulation["future_mean_total"],
            "full_year_expected": simulation["full_year_expected"],
            "projection_rows": simulation["projection_rows"],
        })

    composite_score = sum([
        row["mean_score"] * row["weight_ratio"]
        for row in metric_results
    ])

    p80_score = sum([
        row["p80_score"] * row["weight_ratio"]
        for row in metric_results
    ])

    status_hasil = _status_from_score(composite_score)

    result, _created = MultiMetricMonteCarloResult.objects.update_or_create(
        corporate_risk_item=item,
        forecast_periode=forecast_periode,
        defaults={
            "composite_score": Decimal(str(round(composite_score, 4))),
            "p80_score": Decimal(str(round(p80_score, 4))),
            "status_hasil": status_hasil,
            "metric_snapshot": {
                "metrics": metric_results,
            },
            "simulation_snapshot": {
                "months_ahead": months_ahead,
                "n_simulations": n_simulations,
                "composite_score": composite_score,
                "p80_score": p80_score,
                "status_hasil": status_hasil,
            },
        },
    )

    return result

@dataclass
class MonteCarloComputation:
    mean_value: float
    p50_value: float
    p80_value: float
    p90_value: float
    min_value: float
    max_value: float
    probability_meet_target: float | None
    status_hasil: str
    history_snapshot: list[dict[str, Any]]
    simulation_snapshot: dict[str, Any]


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])

    values = sorted(float(v) for v in values)
    k = (len(values) - 1) * q
    f = math.floor(k)
    c = math.ceil(k)

    if f == c:
        return values[int(k)]

    d0 = values[f] * (c - k)
    d1 = values[c] * (k - f)
    return d0 + d1


def _build_status_hasil(realization_percent: float | None) -> str:
    if realization_percent is None:
        return "-"
    if realization_percent <= 20:
        return "0-20%"
    if realization_percent <= 40:
        return "20-40%"
    if realization_percent <= 60:
        return "40-60%"
    if realization_percent <= 80:
        return "60-80%"
    return "80-100%"


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _history_queryset(item, metric_name: str):
    return (
        MonteCarloKorporatHistory.objects
        .filter(
            corporate_risk_item=item,
            metric_name=metric_name,
        )
        .select_related("periode")
        .order_by("tanggal_data", "id")
    )


def _build_history_snapshot(histories) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for h in histories:
        rows.append({
            "periode": str(h.periode) if h.periode else "-",
            "tanggal": h.tanggal_data.isoformat() if h.tanggal_data else None,
            "value": _safe_float(h.metric_value),
            "target": _safe_float(h.target_value) if h.target_value is not None else None,
        })
    return rows


def _monthly_growth_rates(values: list[float]) -> list[float]:
    growth_rates: list[float] = []
    for i in range(1, len(values)):
        prev_val = float(values[i - 1])
        curr_val = float(values[i])

        if prev_val <= 0:
            continue

        growth = (curr_val - prev_val) / prev_val
        if math.isfinite(growth):
            growth_rates.append(growth)
    return growth_rates


def _simulate_projection(
    actual_values: list[float],
    months_ahead: int,
    n_simulations: int,
) -> dict[str, Any]:
    if len(actual_values) < 3:
        raise ValueError("Data histori belum cukup untuk simulasi time series bulanan.")

    growth_rates = _monthly_growth_rates(actual_values)
    if len(growth_rates) < 2:
        raise ValueError("Data histori belum cukup untuk menghitung pola pertumbuhan bulanan.")

    avg_growth = mean(growth_rates)
    std_growth = 0.0
    if len(growth_rates) > 1:
        variance = mean([(g - avg_growth) ** 2 for g in growth_rates])
        std_growth = math.sqrt(variance)

    current = float(actual_values[-1])
    monthly_results: list[list[float]] = [[] for _ in range(months_ahead)]

    for _ in range(n_simulations):
        simulated = current
        for month_idx in range(months_ahead):
            sampled_growth = random.gauss(avg_growth, std_growth)

            # guard rail agar proyeksi tidak terlalu liar
            sampled_growth = max(min(sampled_growth, 3.0), -0.95)

            simulated = simulated * (1 + sampled_growth)
            simulated = max(simulated, 0.0)

            monthly_results[month_idx].append(simulated)

    projection_rows: list[dict[str, float]] = []
    future_mean_total = 0.0
    p20_total = 0.0
    p40_total = 0.0
    p60_total = 0.0
    p80_total = 0.0

    for idx, values in enumerate(monthly_results):
        mean_val = mean(values) if values else 0.0
        p20 = percentile(values, 0.20)
        p40 = percentile(values, 0.40)
        p60 = percentile(values, 0.60)
        p80 = percentile(values, 0.80)

        projection_rows.append({
            "bulan_index": idx + 1,
            "mean": mean_val,
            "p20": p20,
            "p40": p40,
            "p60": p60,
            "p80": p80,
        })

        future_mean_total += mean_val
        p20_total += p20
        p40_total += p40
        p60_total += p60
        p80_total += p80

    return {
        "growth_mean": avg_growth,
        "growth_std": std_growth,
        "projection_rows": projection_rows,
        "summary": {
            "actual_ytd_total": sum(actual_values),
            "future_mean_total": future_mean_total,
            "full_year_expected": sum(actual_values) + future_mean_total,
            "p20_total": p20_total,
            "p40_total": p40_total,
            "p60_total": p60_total,
            "p80_total": p80_total,
        },
    }


@transaction.atomic
def run_monte_carlo_for_korporat_item(item, forecast_periode, months_ahead: int = 9):
    config = (
        MonteCarloKorporatConfig.objects
        .select_related("corporate_risk_item")
        .get(corporate_risk_item=item, is_active=True)
    )

    histories = list(_history_queryset(item, config.metric_name))
    if len(histories) < max(3, int(config.minimum_history_points or 0)):
        raise ValueError("Data histori belum cukup untuk simulasi time series bulanan.")

    history_values = [_safe_float(h.metric_value) for h in histories]
    history_snapshot = _build_history_snapshot(histories)

    simulation_snapshot = _simulate_projection(
        actual_values=history_values,
        months_ahead=months_ahead,
        n_simulations=int(config.n_simulations or 1000),
    )

    summary = simulation_snapshot.get("summary", {})
    actual_ytd_total = _safe_float(summary.get("actual_ytd_total"))
    future_mean_total = _safe_float(summary.get("future_mean_total"))
    full_year_expected = _safe_float(summary.get("full_year_expected"))
    p20_total = _safe_float(summary.get("p20_total"))
    p40_total = _safe_float(summary.get("p40_total"))
    p60_total = _safe_float(summary.get("p60_total"))
    p80_total = _safe_float(summary.get("p80_total"))

    mean_value = future_mean_total
    p50_value = percentile([row["mean"] for row in simulation_snapshot["projection_rows"]], 0.50)
    p80_value = p80_total
    p90_value = percentile([row["mean"] for row in simulation_snapshot["projection_rows"]], 0.90)
    min_value = min([row["p20"] for row in simulation_snapshot["projection_rows"]], default=0.0)
    max_value = max([row["p80"] for row in simulation_snapshot["projection_rows"]], default=0.0)

    target_values = [
        _safe_float(h.target_value)
        for h in histories
        if h.target_value not in (None, "")
    ]
    target_value = sum(target_values) if target_values else None

    probability_meet_target = None
    if target_value is not None and future_mean_total > 0:
        probability_meet_target = 100.0 if future_mean_total <= target_value else 0.0

    realization_percent = None
    if p80_total > 0:
        realization_percent = (actual_ytd_total / p80_total) * 100.0

    status_hasil = _build_status_hasil(realization_percent)

    # tambah label bulan agar enak dibaca di admin
    bulan_labels = [
        "Apr-26", "May-26", "Jun-26", "Jul-26", "Aug-26", "Sep-26",
        "Oct-26", "Nov-26", "Dec-26", "Jan-27", "Feb-27", "Mar-27",
    ]
    for idx, row in enumerate(simulation_snapshot["projection_rows"]):
        if idx < len(bulan_labels):
            row["bulan"] = bulan_labels[idx]
        else:
            row["bulan"] = f"Month-{idx+1}"

    simulation_snapshot["summary"].update({
        "actual_ytd_total": actual_ytd_total,
        "future_mean_total": future_mean_total,
        "full_year_expected": full_year_expected,
        "p20_total": p20_total,
        "p40_total": p40_total,
        "p60_total": p60_total,
        "p80_total": p80_total,
        "realization_percent": realization_percent or 0.0,
    })

    # =========================
    # KUNCI AGAR TIDAK DOBEL
    # =========================
    result, _created = MonteCarloKorporatResult.objects.update_or_create(
        corporate_risk_item=item,
        forecast_periode=forecast_periode,
        metric_name=config.metric_name,
        defaults={
            "mean_value": mean_value,
            "p50_value": p50_value,
            "p80_value": p80_value,
            "p90_value": p90_value,
            "min_value": min_value,
            "max_value": max_value,
            "probability_meet_target": probability_meet_target,
            "target_value": target_value,
            "status_hasil": status_hasil,
            "history_snapshot": history_snapshot,
            "simulation_snapshot": simulation_snapshot,
        },
    )

    # optional: kalau result diupdate, insight lama untuk result ini dibersihkan
    AIInsightKorporat.objects.filter(monte_carlo_result=result).delete()

    return result


def generate_rule_based_ai_insight_for_result(result):
    summary = (result.simulation_snapshot or {}).get("summary", {})
    projection_rows = (result.simulation_snapshot or {}).get("projection_rows", [])

    actual_ytd = float(summary.get("actual_ytd_total") or 0)
    p80_total = float(summary.get("p80_total") or 0)
    full_year_expected = float(summary.get("full_year_expected") or 0)
    future_mean_total = float(summary.get("future_mean_total") or 0)

    realization_percent = 0.0
    if p80_total > 0:
        realization_percent = (actual_ytd / p80_total) * 100

    if realization_percent <= 20:
        tingkat = "rendah"
        kemungkinan = "20%"
    elif realization_percent <= 40:
        tingkat = "moderat"
        kemungkinan = "40%"
    elif realization_percent <= 60:
        tingkat = "cukup tinggi"
        kemungkinan = "60%"
    elif realization_percent <= 80:
        tingkat = "tinggi"
        kemungkinan = "80%"
    else:
        tingkat = "sangat tinggi"
        kemungkinan = "100%"

    tren = "fluktuatif"
    if projection_rows:
        first_mean = float(projection_rows[0].get("mean") or 0)
        last_mean = float(projection_rows[-1].get("mean") or 0)
        if last_mean > first_mean * 1.1:
            tren = "meningkat"
        elif last_mean < first_mean * 0.9:
            tren = "menurun"
        else:
            tren = "relatif stabil"

    executive_summary = (
        f"Berdasarkan hasil simulasi Monte Carlo, risiko siber pada item "
        f"'{result.corporate_risk_item}' menunjukkan profil eksposur {tingkat} "
        f"dengan tingkat kemungkinan indikatif {kemungkinan}. "
        f"Proyeksi hingga akhir periode memperlihatkan pola {tren}, dengan "
        f"full year expected sebesar {full_year_expected:,.3f} dan "
        f"skenario konservatif P80 sebesar {p80_total:,.3f}. "
        f"Realisasi year-to-date saat ini masih berada pada {realization_percent:,.2f}% "
        f"dari skenario konservatif."
    )

    key_drivers = (
        "1. Volatilitas historis incident cyber yang tinggi.\n"
        f"2. Proyeksi mean sisa periode sebesar {future_mean_total:,.3f}.\n"
        "3. Adanya potensi lonjakan ancaman pada periode proyeksi.\n"
        "4. Risiko utama bukan hanya jumlah threat, tetapi kemungkinan eskalasi "
        "menjadi insiden yang mengganggu atau merusak sistem."
    )

    recommended_actions = (
        "1. Perkuat monitoring dan early warning untuk aset IT/OT kritikal.\n"
        "2. Tingkatkan kesiapan incident response dan containment playbook.\n"
        "3. Prioritaskan hardening, patching, dan segmentasi jaringan pada sistem kritikal.\n"
        "4. Lakukan evaluasi berkala atas kontrol mitigasi agar threat tidak berkembang "
        "menjadi gangguan operasional.\n"
        "5. Fokuskan pengendalian pada zero tolerance terhadap insiden yang merusak sistem."
    )

    insight, _ = AIInsightKorporat.objects.update_or_create(
        corporate_risk_item=result.corporate_risk_item,
        monte_carlo_result=result,
        defaults={
            "executive_summary": executive_summary,
            "key_drivers": key_drivers,
            "recommended_actions": recommended_actions,
        },
    )
    return insight

def map_risk_appetite(probability_percent):
    """
    Custom mapping sesuai selera risiko PLN Batam
    """

    if probability_percent <= 20:
        return 20
    elif probability_percent <= 40:
        return 40
    elif probability_percent <= 80:
        return 40   # ← ini yang kamu mau (80% dianggap 40%)
    else:
        return 60

