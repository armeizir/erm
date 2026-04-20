import math
import random
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from .models import (
    MonteCarloKorporatHistory,
    MonteCarloKorporatResult,
)


def _to_decimal(value):
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _mean(values):
    return sum(values) / len(values) if values else 0.0


def _percentile(values, p):
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * (p / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return values[int(k)]
    d0 = values[f] * (c - k)
    d1 = values[c] * (k - f)
    return d0 + d1


def _std(values):
    if len(values) <= 1:
        return 0.0
    avg = _mean(values)
    return math.sqrt(sum((x - avg) ** 2 for x in values) / (len(values) - 1))


def _safe_growth(prev_value, current_value):
    if prev_value in (0, None):
        return 0.0
    return (current_value - prev_value) / prev_value


def _month_label(dt):
    return dt.strftime("%b-%y")


def _next_month(dt):
    if dt.month == 12:
        return date(dt.year + 1, 1, 1)
    return date(dt.year, dt.month + 1, 1)


def _build_growth_series(values):
    growths = []
    for i in range(1, len(values)):
        growths.append(_safe_growth(values[i - 1], values[i]))
    return growths


def _simulate_future_paths(last_actual, growth_mean, growth_std, months_ahead, n_simulations):
    all_paths = []

    for _ in range(n_simulations):
        current = last_actual
        path = []

        for _m in range(months_ahead):
            sampled_growth = random.gauss(growth_mean, growth_std) if growth_std > 0 else growth_mean
            next_value = current * (1 + sampled_growth)

            # proteksi agar tidak negatif
            if next_value < 0:
                next_value = 0

            path.append(next_value)
            current = next_value

        all_paths.append(path)

    return all_paths


def _derive_probability_band(realization_percent):
    if realization_percent is None:
        return None

    if realization_percent <= 20:
        return "0-20%"
    if realization_percent <= 40:
        return "20-40%"
    if realization_percent <= 60:
        return "40-60%"
    if realization_percent <= 80:
        return "60-80%"
    return "80-100%"


@transaction.atomic
def run_monte_carlo_for_korporat_item(item, forecast_periode, months_ahead=9):
    config = item.monte_carlo_config

    histories = MonteCarloKorporatHistory.objects.filter(
        corporate_risk_item=item,
        metric_name=config.metric_name,
    ).order_by("tanggal_data")

    history_values = [float(h.metric_value) for h in histories]

    if len(history_values) < max(config.minimum_history_points, 3):
        raise ValueError("Data histori belum cukup untuk simulasi time series bulanan.")

    growths = _build_growth_series(history_values)

    growth_mean = _mean(growths)
    growth_std = _std(growths)

    last_history = histories.last()
    last_actual_value = float(last_history.metric_value)

    simulated_paths = _simulate_future_paths(
        last_actual=last_actual_value,
        growth_mean=growth_mean,
        growth_std=growth_std,
        months_ahead=months_ahead,
        n_simulations=config.n_simulations,
    )

    # total forecast per simulasi (Apr–Dec 2026)
    total_forecasts = [sum(path) for path in simulated_paths]

    mean_total = _mean(total_forecasts)
    p20_total = _percentile(total_forecasts, 20)
    p40_total = _percentile(total_forecasts, 40)
    p60_total = _percentile(total_forecasts, 60)
    p80_total = _percentile(total_forecasts, 80)

    p50_total = _percentile(total_forecasts, 50)
    p90_total = _percentile(total_forecasts, 90)
    min_total = min(total_forecasts)
    max_total = max(total_forecasts)

    # proyeksi per bulan dari percentile
    projection_rows = []
    start_date = _next_month(last_history.tanggal_data)

    for month_idx in range(months_ahead):
        month_values = [path[month_idx] for path in simulated_paths]
        current_month = date(start_date.year, start_date.month, 1)

        projection_rows.append({
            "bulan": _month_label(current_month),
            "mean": round(_mean(month_values), 3),
            "p20": round(_percentile(month_values, 20), 3),
            "p40": round(_percentile(month_values, 40), 3),
            "p60": round(_percentile(month_values, 60), 3),
            "p80": round(_percentile(month_values, 80), 3),
        })

        start_date = _next_month(start_date)

    # hitung realisasi tahun berjalan dari data actual Jan–Mar 2026
    actual_year = forecast_periode.tahun if hasattr(forecast_periode, "tahun") else last_history.tanggal_data.year
    actual_ytd = [
        float(h.metric_value)
        for h in histories
        if h.tanggal_data.year == actual_year
    ]
    actual_ytd_total = sum(actual_ytd)

    # total ekspektasi full-year = actual YTD + mean future
    full_year_expected = actual_ytd_total + mean_total if actual_ytd else mean_total

    realization_percent = None
    if full_year_expected > 0 and actual_ytd_total > 0:
        realization_percent = (actual_ytd_total / full_year_expected) * 100

    probability_meet_target = None
    target = float(last_history.target_value) if last_history.target_value is not None else None
    if target is not None:
        if config.direction == "lower":
            probability_meet_target = (
                sum(1 for x in total_forecasts if x <= target) / len(total_forecasts) * 100
            )
        else:
            probability_meet_target = (
                sum(1 for x in total_forecasts if x >= target) / len(total_forecasts) * 100
            )

    result = MonteCarloKorporatResult.objects.create(
        corporate_risk_item=item,
        forecast_periode=forecast_periode,
        metric_name=config.metric_name,
        mean_value=_to_decimal(mean_total),
        p50_value=_to_decimal(p50_total),
        p80_value=_to_decimal(p80_total),
        p90_value=_to_decimal(p90_total),
        min_value=_to_decimal(min_total),
        max_value=_to_decimal(max_total),
        probability_meet_target=_to_decimal(probability_meet_target) if probability_meet_target is not None else None,
        target_value=_to_decimal(target) if target is not None else None,
        status_hasil=_derive_probability_band(realization_percent),
        history_snapshot=[
            {
                "periode": h.periode.nama_periode if hasattr(h.periode, "nama_periode") else str(h.periode_id),
                "tanggal": str(h.tanggal_data),
                "value": float(h.metric_value),
                "target": float(h.target_value) if h.target_value is not None else None,
            }
            for h in histories
        ],
        simulation_snapshot={
            "growth_mean": round(growth_mean, 6),
            "growth_std": round(growth_std, 6),
            "projection_rows": projection_rows,
            "summary": {
                "actual_ytd_total": round(actual_ytd_total, 3),
                "future_mean_total": round(mean_total, 3),
                "full_year_expected": round(full_year_expected, 3),
                "realization_percent": round(realization_percent, 2) if realization_percent is not None else None,
                "p20_total": round(p20_total, 3),
                "p40_total": round(p40_total, 3),
                "p60_total": round(p60_total, 3),
                "p80_total": round(p80_total, 3),
            },
        },
    )

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
        f"1. Volatilitas historis incident cyber yang tinggi.\n"
        f"2. Proyeksi mean sisa periode sebesar {future_mean_total:,.3f}.\n"
        f"3. Adanya potensi lonjakan ancaman pada periode proyeksi.\n"
        f"4. Risiko utama bukan hanya jumlah threat, tetapi kemungkinan eskalasi "
        f"menjadi insiden yang mengganggu atau merusak sistem."
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