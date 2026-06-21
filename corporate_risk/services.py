from __future__ import annotations
from dateutil.relativedelta import relativedelta
from dataclasses import dataclass
from statistics import mean, median
from typing import Any
import json
import logging
import math
import random

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import httpx

from .models import (
    MonteCarloKorporatConfig,
    MonteCarloKorporatHistory,
    MonteCarloKorporatResult,
    AIInsightKorporat,
    RiskMetric,
    MonteCarloMetricHistory,
    MultiMetricMonteCarloResult,
    MultiMetricAIInsightKorporat,
)
from .distribution_analysis import analyze_distribution_recommendation
from risk.models import AppSetting

logger = logging.getLogger(__name__)

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


def _format_month_year_id(value):
    if not value:
        return ""
    return f"{MONTH_NAMES_ID.get(value.month, value.strftime('%B'))} {value.year}"


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
        number = float(value or 0)
        if not math.isfinite(number):
            return 0.0
        return number
    except Exception:
        return 0.0


def _decimal(value, digits=4, max_digits=24):
    if value in (None, ""):
        return None
    number = _safe_float(value)
    if not math.isfinite(number):
        return None

    integer_digits = max(max_digits - digits, 1)
    quantizer = Decimal(1).scaleb(-digits)
    # SQLite stores large NUMERIC values as floats in some cases. A mathematical
    # max like 99999999999999.9999 can round up to 100000000000000 and break
    # Django's Decimal converter on read, so keep a small safety margin.
    max_abs = (Decimal(10) ** integer_digits) * Decimal("0.99")

    try:
        decimal_value = Decimal(str(number))
        if decimal_value > max_abs:
            decimal_value = max_abs
        elif decimal_value < -max_abs:
            decimal_value = -max_abs
        return decimal_value.quantize(quantizer, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _decimal_18(value, digits=4):
    return _decimal(value, digits=digits, max_digits=18)


def _decimal_probability(value):
    return _decimal(value, digits=2, max_digits=6)


def _extract_json_object(text: str) -> dict[str, Any]:
    if not text:
        return {}
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
    return {}


def _gemini_generate_management_language(setting: AppSetting, prompt: str) -> dict[str, str]:
    model_name = setting.ai_model or "gemini-3.1-flash-lite"
    if model_name.startswith("gpt-"):
        model_name = "gemini-3.1-flash-lite"
    base_url = setting.ai_base_url or "https://generativelanguage.googleapis.com/v1beta"
    if "api.openai.com" in base_url:
        base_url = "https://generativelanguage.googleapis.com/v1beta"
    base_url = base_url.rstrip("/")
    if base_url == "https://generativelanguage.googleapis.com":
        base_url = f"{base_url}/v1beta"
    url = f"{base_url}/models/{model_name}:generateContent"
    response = httpx.post(
        url,
        headers={"x-goog-api-key": setting.ai_api_key},
        json={
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": float(setting.ai_temperature or 0.2),
                "responseMimeType": "application/json",
            },
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    candidates = payload.get("candidates") or []
    if not candidates:
        return {}
    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    text = "\n".join(part.get("text", "") for part in parts).strip()
    return _extract_json_object(text)


def _coerce_ai_text(value, fallback: str) -> str:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or fallback
    if isinstance(value, list):
        cleaned = "\n".join(str(item).strip() for item in value if str(item).strip())
        return cleaned or fallback
    return fallback


def _polish_multi_metric_insight_with_ai(
    result,
    executive_summary: str,
    key_findings: str,
    recommended_actions: str,
) -> tuple[str, str, str]:
    setting = AppSetting.get_solo()
    if not setting.ai_aktif or not setting.ai_api_key:
        return executive_summary, key_findings, recommended_actions
    if setting.ai_provider != AppSetting.AI_PROVIDER_GEMINI:
        return executive_summary, key_findings, recommended_actions

    prompt = f"""
Anda adalah konsultan Enterprise Risk Management untuk Direksi PLN Batam.

Tugas:
1. Tulis ulang insight menjadi memo manajemen untuk Direksi, bukan sekadar parafrase template.
2. Pertahankan semua angka penting dan konteks risiko. Jangan menambah fakta baru.
3. Gunakan Bahasa Indonesia.
4. Gunakan gaya yang tajam, natural, dan berorientasi keputusan.
5. Jangan memakai kalimat template seperti "prioritaskan mitigasi pada metric dengan kontribusi risiko terbesar" kecuali dibuat spesifik.
6. Kembalikan JSON valid saja dengan key:
   executive_summary, key_findings, recommended_actions.

Format isi:
- executive_summary: 1-2 paragraf pendek, diawali dengan implikasi manajemen utama.
- key_findings: 3-5 poin ringkas dalam baris terpisah; jelaskan sinyal risiko, driver, dan dampak terhadap target.
- recommended_actions: 3-5 aksi spesifik dalam format 30/60/90 hari atau trigger eskalasi, bukan daftar generik.

Konteks hasil simulasi:
- Risiko: {result.corporate_risk_item}
- Periode forecast: {result.forecast_periode}
- Status target: {result.target_status or "-"}
- Status risiko: {result.risk_status or "-"}
- Composite score: {result.composite_score}
- P80 score: {result.p80_score}

Teks awal:
{{
  "executive_summary": {json.dumps(executive_summary, ensure_ascii=False)},
  "key_findings": {json.dumps(key_findings, ensure_ascii=False)},
  "recommended_actions": {json.dumps(recommended_actions, ensure_ascii=False)}
}}
"""

    try:
        data = _gemini_generate_management_language(setting, prompt)
    except Exception as exc:
        logger.exception("Gemini AI polish failed for multi metric result %s: %s", result.pk, exc)
        return executive_summary, key_findings, recommended_actions

    if not data:
        logger.warning("Gemini AI polish returned empty response for multi metric result %s", result.pk)
        return executive_summary, key_findings, recommended_actions

    return (
        _coerce_ai_text(data.get("executive_summary"), executive_summary),
        _coerce_ai_text(data.get("key_findings"), key_findings),
        _coerce_ai_text(data.get("recommended_actions"), recommended_actions),
    )


def _replace_result(model, lookup, defaults):
    existing_pk = (
        model.objects
        .filter(**lookup)
        .values_list("pk", flat=True)
        .first()
    )

    if existing_pk:
        model.objects.filter(pk=existing_pk).update(**defaults)
        return model.objects.get(pk=existing_pk)

    return model.objects.create(**lookup, **defaults)


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


def _stdev(values):
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    return math.sqrt(mean([(value - avg) ** 2 for value in values]))


def _skewness(values):
    if len(values) < 3:
        return 0.0
    avg = mean(values)
    std = _stdev(values)
    if std <= 0:
        return 0.0
    return mean([((value - avg) / std) ** 3 for value in values])


def _distribution_label(distribution_type):
    labels = dict(MonteCarloKorporatConfig.DISTRIBUTION_CHOICES)
    return labels.get(distribution_type, distribution_type)


def _distribution_reason(distribution_type, values, rates):
    if distribution_type == "normal":
        return "Pola growth relatif simetris dan tidak terlihat sangat condong."
    if distribution_type == "lognormal":
        return "Data bernilai positif dan growth condong ke kanan, cocok untuk variabel yang tidak boleh negatif."
    if distribution_type == "triangular":
        return "Data histori terbatas, tetapi nilai minimum, paling mungkin, dan maksimum masih dapat dibaca."
    if distribution_type == "uniform":
        return "Sebaran histori relatif datar atau ketidakpastian dianggap sama di rentang minimum-maksimum."
    if distribution_type == "beta":
        return "Data terlihat berada dalam rentang terbatas sehingga cocok dimodelkan sebagai proporsi/range bounded."
    if distribution_type == "gamma":
        return "Data positif dan condong ke kanan, cocok untuk nilai dengan ekor kanan."
    if distribution_type == "weibull":
        return "Data positif dan cocok untuk pola risiko/waktu kejadian dengan ekor kanan."
    if distribution_type == "empirical":
        return "Histori masih terbatas atau pola tidak stabil, sehingga sampling langsung dari data historis lebih aman."
    return "Distribusi kandidat untuk simulasi."


def recommend_monte_carlo_distribution(values):
    values = [_safe_float(value) for value in values if value not in (None, "")]
    rates = _growth_rates(values)
    sample = rates if len(rates) >= 2 else values
    sample = [value for value in sample if math.isfinite(value)]

    if len(sample) < 3:
        recommended = "empirical"
    else:
        skew = _skewness(sample)
        min_value = min(sample)
        max_value = max(sample)
        avg_value = mean(sample)
        std_value = _stdev(sample)
        value_skew = _skewness(values) if len(values) >= 3 else 0
        bounded_range = max_value - min_value
        cv = abs(std_value / avg_value) if avg_value else 0
        all_positive_values = all(value > 0 for value in values)

        if len(sample) < 5:
            recommended = "triangular"
        elif all_positive_values and (skew > 1.0 or value_skew > 1.0):
            recommended = "lognormal"
        elif min_value >= 0 and max_value <= 1:
            recommended = "beta"
        elif all_positive_values and (skew > 0.6 or value_skew > 0.6) and cv > 0.5:
            recommended = "gamma"
        elif abs(skew) <= 0.5:
            recommended = "normal"
        elif bounded_range > 0 and std_value / bounded_range < 0.18:
            recommended = "uniform"
        elif all_positive_values and skew > 0.3:
            recommended = "weibull"
        else:
            recommended = "empirical"

    analysis = analyze_distribution_recommendation(None, values, recommended)
    candidates = []
    for value, label in MonteCarloKorporatConfig.DISTRIBUTION_CHOICES:
        candidate_analysis = analyze_distribution_recommendation(None, values, value)
        candidates.append({
            "value": value,
            "label": label,
            "recommended": value == recommended,
            "reason": candidate_analysis.get("reason_summary") or _distribution_reason(value, values, rates),
            "limitation": candidate_analysis.get("limitations", ""),
        })

    return {
        "recommended": recommended,
        "recommended_label": _distribution_label(recommended),
        "history_count": len(values),
        "growth_count": len(rates),
        "growth_mean": mean(rates) if rates else None,
        "growth_std": _stdev(rates) if rates else None,
        "growth_min": min(rates) if rates else None,
        "growth_max": max(rates) if rates else None,
        "growth_median": median(rates) if rates else None,
        "growth_skewness": _skewness(rates) if len(rates) >= 3 else None,
        "candidates": candidates,
        "reason_summary": analysis["reason_summary"],
        "reason_detail": analysis["reason_detail"],
        "limitations": analysis["limitations"],
        "confidence": analysis["confidence"],
        "data_quality_warnings": analysis["data_quality_warnings"],
        "alternative_distributions": analysis["alternative_distributions"],
        "analysis": analysis,
    }


def _sample_beta_from_rates(rates):
    min_rate = min(rates)
    max_rate = max(rates)
    if max_rate <= min_rate:
        return rates[0]
    normalized = [(rate - min_rate) / (max_rate - min_rate) for rate in rates]
    avg = mean(normalized)
    variance = mean([(value - avg) ** 2 for value in normalized])
    if variance <= 0 or avg <= 0 or avg >= 1:
        sample = random.betavariate(2, 2)
    else:
        common = (avg * (1 - avg) / variance) - 1
        alpha = max(avg * common, 0.5)
        beta = max((1 - avg) * common, 0.5)
        sample = random.betavariate(alpha, beta)
    return min_rate + sample * (max_rate - min_rate)


def _sample_growth(rates, avg_growth, std_growth, distribution_type):
    if distribution_type == "empirical":
        return random.choice(rates)

    if distribution_type == "triangular":
        return random.triangular(min(rates), max(rates), avg_growth)

    if distribution_type == "uniform":
        return random.uniform(min(rates), max(rates))

    if distribution_type == "lognormal":
        gross_rates = [max(1 + rate, 0.0001) for rate in rates]
        logs = [math.log(value) for value in gross_rates]
        return random.lognormvariate(mean(logs), _stdev(logs)) - 1

    if distribution_type == "beta":
        return _sample_beta_from_rates(rates)

    if distribution_type == "gamma":
        shift = abs(min(rates)) + 0.0001 if min(rates) <= 0 else 0
        shifted = [rate + shift for rate in rates]
        avg = mean(shifted)
        variance = _stdev(shifted) ** 2
        if avg <= 0 or variance <= 0:
            return avg_growth
        shape = max((avg ** 2) / variance, 0.1)
        scale = max(variance / avg, 0.0001)
        return random.gammavariate(shape, scale) - shift

    if distribution_type == "weibull":
        shift = abs(min(rates)) + 0.0001 if min(rates) <= 0 else 0
        shifted = [rate + shift for rate in rates]
        avg = mean(shifted)
        if avg <= 0:
            return avg_growth
        shape = 1.5
        scale = avg / math.gamma(1 + (1 / shape))
        return random.weibullvariate(scale, shape) - shift

    return random.gauss(avg_growth, std_growth)


def _simulate_metric(
    values,
    months_ahead=9,
    n_simulations=10000,
    actual_total=None,
    distribution_type="normal",
    sma_window: int | None = None,
):
    """
    Excel reference (KK Risiko Cyber):
    - SMA untuk f_p50 (median forecast)
    - P15 (percentile 0.15) dari histori untuk menghitung Std Dev per bulan: StdDev = P50 - P15
    - Sampling langsung dari Normal(mu=f_p50, sigma=StdDev) per bulan
    - Total percentiles (P5/P50/P95) HARUS dari distribution total (simulation_totals)
    """
    if len(values) < 3:
        raise ValueError("Data histori metric belum cukup. Minimal 3 periode.")

    values = [_safe_float(v) for v in values]
    values = [v for v in values if math.isfinite(v)]
    if not values:
        raise ValueError("Data histori metric kosong/invalid.")

    window = int(sma_window or min(len(values), 3))
    window = max(1, window)

    f_p50 = mean(values[-window:])
    f_p15 = _percentile(values, 0.15)
    std_dev = f_p50 - f_p15
    sigma = max(abs(std_dev), 0.0001)

    actual_total = _safe_float(actual_total) if actual_total is not None else sum(values)

    simulation_totals: list[float] = []
    for _ in range(n_simulations):
        total = float(actual_total)
        for _month_idx in range(months_ahead):
            sampled = random.gauss(f_p50, sigma)
            sampled = max(sampled, 0.0)
            total += sampled
        simulation_totals.append(total)

    # Percentile total dari distribusi total (bukan penjumlahan per-bulan)
    p5_total = _percentile(simulation_totals, 0.05)
    p20_total = _percentile(simulation_totals, 0.20)
    p40_total = _percentile(simulation_totals, 0.40)
    p50_total = _percentile(simulation_totals, 0.50)
    p60_total = _percentile(simulation_totals, 0.60)
    p80_total = _percentile(simulation_totals, 0.80)
    p90_total = _percentile(simulation_totals, 0.90)
    p95_total = _percentile(simulation_totals, 0.95)

    future_mean_total = months_ahead * f_p50
    full_year_expected = float(actual_total) + future_mean_total

    # Projection rows untuk UI (P15 + Std Dev per bulan; P50/Mean konstan mengikuti SMA)
    projection_rows = []
    for idx in range(months_ahead):
        projection_rows.append({
            "bulan_index": idx + 1,
            "mean": f_p50,
            "p15": f_p15,
            "p50": f_p50,
            "p20": _percentile([max(random.gauss(f_p50, sigma), 0.0) for _ in range(2000)], 0.20),
            "p40": _percentile([max(random.gauss(f_p50, sigma), 0.0) for _ in range(2000)], 0.40),
            "p60": _percentile([max(random.gauss(f_p50, sigma), 0.0) for _ in range(2000)], 0.60),
            "p80": _percentile([max(random.gauss(f_p50, sigma), 0.0) for _ in range(2000)], 0.80),
            "stdev_f": abs(f_p50 - f_p15),
        })

    # safeguard: jika spread simulasi/sampling terlalu sempit sehingga stdev_f jadi 0,
    # gunakan fallback stdev histori (atau minimal epsilon)
    fallback_sigma = max(_stdev(values), 0.0001)
    if abs(f_p50 - f_p15) == 0:
        for row in projection_rows:
            row["stdev_f"] = fallback_sigma

    return {
        "actual_total": float(actual_total),
        "future_mean_total": float(future_mean_total),
        "full_year_expected": float(full_year_expected),
        "p5_total": float(p5_total),
        "p20_total": float(p20_total),
        "p40_total": float(p40_total),
        "p50_total": float(p50_total),
        "p60_total": float(p60_total),
        "p80_total": float(p80_total),
        "p90_total": float(p90_total),
        "p95_total": float(p95_total),
        "min_total": float(min(simulation_totals) if simulation_totals else 0.0),
        "max_total": float(max(simulation_totals) if simulation_totals else 0.0),
        "distribution_type": distribution_type,
        "distribution_label": _distribution_label(distribution_type),
        "projection_rows": projection_rows,
        "simulation_totals": simulation_totals,
        "descriptive_stats": {
            "mean": float(mean(values)),
            "std": float(_stdev(values)),
            "min": float(min(values)),
            "max": float(max(values)),
            "skewness": float(_skewness(values)),
            "sma_window": window,
            "f_p50": float(f_p50),
            "f_p15": float(f_p15),
            "std_dev": float(std_dev),
        },
    }


def _latest_target_from_histories(histories):
    for history in reversed(histories):
        if history.target_value not in (None, ""):
            return _safe_float(history.target_value)
    return None


def _build_target_analysis(
    simulation_totals,
    target_value,
    actual_total=None,
    average_selling_price=0,
    risk_appetite_threshold=20,
    risk_appetite_value=None,
):
    if not simulation_totals or target_value in (None, ""):
        return {}

    totals = [float(value) for value in simulation_totals]
    total_simulation = len(totals)
    target = _safe_float(target_value)
    selling_price = _safe_float(average_selling_price)
    threshold = _safe_float(risk_appetite_threshold)
    appetite_value = None if risk_appetite_value in (None, "") else _safe_float(risk_appetite_value)

    achieved_count = sum(1 for value in totals if value >= target)
    not_achieved_count = len(totals) - achieved_count
    probability_achieve = achieved_count / len(totals) * 100
    probability_not_achieve = not_achieved_count / len(totals) * 100

    worst_case = _percentile(totals, 0.05)
    baseline = _percentile(totals, 0.50)
    best_case = _percentile(totals, 0.95)
    forecast_total = baseline
    target_gap = max(target - forecast_total, 0)
    potential_loss = target_gap * selling_price
    var_95 = max(target - worst_case, 0)

    target_status = "Tercapai" if forecast_total >= target else "Tidak Tercapai"
    risk_status = "Aman" if forecast_total >= target else "Berisiko"
    requires_mitigation = probability_not_achieve >= threshold
    if appetite_value is not None and potential_loss > appetite_value:
        requires_mitigation = True

    recommendation = (
        "Perlu mitigasi: probabilitas tidak tercapai atau potential loss melewati risk appetite."
        if requires_mitigation
        else "Belum perlu mitigasi tambahan: tetap monitor realisasi dan driver utama."
    )

    return {
        "forecast_total": forecast_total,
        "actual_total": _safe_float(actual_total),
        "target_value": target,
        "target_gap": target_gap,
        "average_selling_price": selling_price,
        "potential_loss": potential_loss,
        "probability_achieve_target": probability_achieve,
        "probability_not_achieve_target": probability_not_achieve,
        "target_status": target_status,
        "risk_status": risk_status,
        "worst_case_value": worst_case,
        "baseline_value": baseline,
        "best_case_value": best_case,
        "var_95": var_95,
        "requires_mitigation": requires_mitigation,
        "risk_appetite_threshold": threshold,
        "risk_appetite_value": appetite_value,
        "achieved_count": achieved_count,
        "not_achieved_count": not_achieved_count,
        "total_simulation": total_simulation,
        "recommendation": recommendation,
        "distribution_sample": totals,
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

def _build_multi_metric_projection_rows(metric_results):
    """
    Membentuk proyeksi bulanan agregat untuk Multi Metric Monte Carlo.
    Output berupa composite score bulanan berbasis bobot metric.
    """

    if not metric_results:
        return []

    total_months = len(metric_results[0].get("projection_rows", []))
    rows = []

    for idx in range(total_months):
        mean_score_total = 0.0
        p20_score_total = 0.0
        p40_score_total = 0.0
        p60_score_total = 0.0
        p80_score_total = 0.0

        contributions = []

        for metric_row in metric_results:
            projection_rows = metric_row.get("projection_rows", [])

            if idx >= len(projection_rows):
                continue

            projection = projection_rows[idx]
            weight_ratio = _safe_float(metric_row.get("weight_ratio"))

            mean_score = _safe_float(projection.get("mean_score"))
            p20_score = _safe_float(projection.get("p20_score"))
            p40_score = _safe_float(projection.get("p40_score"))
            p60_score = _safe_float(projection.get("p60_score"))
            p80_score = _safe_float(projection.get("p80_score"))

            mean_score_total += mean_score * weight_ratio
            p20_score_total += p20_score * weight_ratio
            p40_score_total += p40_score * weight_ratio
            p60_score_total += p60_score * weight_ratio
            p80_score_total += p80_score * weight_ratio

            contributions.append({
                "metric_name": metric_row.get("metric_name"),
                "contribution": p80_score * weight_ratio,
            })

        dominant_metric = "-"
        if contributions:
            dominant_metric = max(
                contributions,
                key=lambda x: _safe_float(x.get("contribution"))
            ).get("metric_name") or "-"

        rows.append({
            "bulan_index": idx + 1,
            "mean_score": round(mean_score_total, 4),
            "p20_score": round(p20_score_total, 4),
            "p40_score": round(p40_score_total, 4),
            "p60_score": round(p60_score_total, 4),
            "p80_score": round(p80_score_total, 4),
            "dominant_metric": dominant_metric,
        })

    return rows

def _build_multi_metric_history_rows(metric_results):
    if not metric_results:
        return []

    # Bug 4: gabungkan by tanggal (bukan index)
    all_dates = sorted(set(
        h.get("tanggal")
        for mr in metric_results
        for h in (mr.get("history_rows") or [])
        if h.get("tanggal")
    ))

    rows = []
    for tanggal in all_dates:
        actual_score_total = 0.0
        periode_label = "-"
        metric_values = []

        for metric_row in metric_results:
            history_rows = metric_row.get("history_rows", []) or []
            matching = next(
                (h for h in history_rows if h.get("tanggal") == tanggal),
                None
            )
            if not matching:
                continue

            weight_ratio = _safe_float(metric_row.get("weight_ratio"))
            actual_score = _safe_float(matching.get("actual_score"))
            actual_score_total += actual_score * weight_ratio
            periode_label = matching.get("periode") or periode_label

            metric_values.append({
                "metric_name": metric_row.get("metric_name") or "-",
                "actual": matching.get("actual"),
                "actual_score": actual_score,
                "weight_ratio": weight_ratio,
            })

        rows.append({
            "periode": periode_label,
            "tanggal": tanggal,
            "actual_score": round(actual_score_total, 4),
            "metric_values": metric_values,
        })

    return rows


def _has_meaningful_descriptive_metric(metric_row):
    if not metric_row:
        return False
    stats = metric_row.get("descriptive_stats") or {}
    if any(_safe_float(stats.get(key)) != 0 for key in ("f_p50", "f_p15", "std_dev", "mean", "max")):
        return True
    for row in metric_row.get("projection_rows", []) or []:
        if any(_safe_float(row.get(key)) != 0 for key in ("p50", "p15", "stdev_f", "mean", "p80")):
            return True
    for row in metric_row.get("history_rows", []) or []:
        if _safe_float(row.get("actual")) != 0:
            return True
    return False


def _select_descriptive_metric(metric_results, target_metric_row=None):
    candidates = []
    if target_metric_row:
        candidates.append(target_metric_row)
    candidates.extend([
        row for row in metric_results
        if row is not target_metric_row
    ])

    for row in candidates:
        if _has_meaningful_descriptive_metric(row):
            return row
    return target_metric_row or (metric_results[0] if metric_results else None)


def run_multi_metric_monte_carlo_for_korporat_item(
    item,
    forecast_periode,
    months_ahead=9,
    n_simulations=10000,
    scenario_percentile=80,
    distribution_type="normal",
    selected_distribution_justification="",
):
    n_simulations = int(n_simulations or 10000)
    if n_simulations < 1000:
        raise ValueError("Monte Carlo Trials minimal 1,000. Rekomendasi 10,000 trials untuk hasil yang lebih stabil.")

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
    target_analysis = {}

    if total_weight <= 0:
        total_weight = len(metrics)

    for metric in metrics:
        histories = list(
            MonteCarloMetricHistory.objects.filter(
                metric=metric,
                tanggal_data__lte=forecast_periode.tanggal_selesai,
            )
            .select_related("periode")
            .order_by("tanggal_data", "id")
        )

        if len(histories) < 3:
            raise ValueError(
                f"Data histori untuk metric '{metric.name}' belum cukup. Minimal 3 periode."
            )

        values = [_safe_float(h.metric_value) for h in histories]
        distribution_recommendation = recommend_monte_carlo_distribution(values)
        last_actual = values[-1]
        history_target = _latest_target_from_histories(histories)
        metric_target = metric.effective_target_value
        if metric_target in (None, ""):
            metric_target = history_target
        forecast_year = (
            forecast_periode.tanggal_mulai.year
            if getattr(forecast_periode, "tanggal_mulai", None)
            else None
        )
        actual_ytd_total = sum(
            _safe_float(h.metric_value)
            for h in histories
            if h.tanggal_data
            and forecast_year
            and h.tanggal_data.year == forecast_year
            and h.tanggal_data <= forecast_periode.tanggal_selesai
        )
        # Bug 3: fallback salah — jangan menjumlahkan seluruh histori
        if actual_ytd_total <= 0:
            actual_ytd_total = _safe_float(values[-1]) if values else 0.0

        # Excel reference uses SMA+Normal (not growth-rate)
        simulation = _simulate_metric(
            values=values,
            months_ahead=months_ahead,
            n_simulations=n_simulations,
            actual_total=actual_ytd_total,
            distribution_type=distribution_type,
            sma_window=3,
        )

        weight = _safe_float(metric.weight)
        weight_ratio = weight / total_weight if total_weight else 0

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

        scenario_key = f"p{scenario_percentile}_total"
        scenario_total = simulation.get(scenario_key, simulation["p80_total"])

        scenario_score = _normalize_metric_score(
            metric=metric,
            projected_value=scenario_total,
            last_actual_value=last_actual,
        )

        enriched_projection_rows = []

        for projection in simulation["projection_rows"]:
            mean_month_score = _normalize_metric_score(
                metric=metric,
                projected_value=projection.get("mean"),
                last_actual_value=last_actual,
            )

            p20_month_score = _normalize_metric_score(
                metric=metric,
                projected_value=projection.get("p20"),
                last_actual_value=last_actual,
            )

            p40_month_score = _normalize_metric_score(
                metric=metric,
                projected_value=projection.get("p40"),
                last_actual_value=last_actual,
            )

            p60_month_score = _normalize_metric_score(
                metric=metric,
                projected_value=projection.get("p60"),
                last_actual_value=last_actual,
            )

            p80_month_score = _normalize_metric_score(
                metric=metric,
                projected_value=projection.get("p80"),
                last_actual_value=last_actual,
            )

            enriched_projection_rows.append({
                **projection,
                "mean_score": mean_month_score,
                "p20_score": p20_month_score,
                "p40_score": p40_month_score,
                "p60_score": p60_month_score,
                "p80_score": p80_month_score,
            })

        metric_results.append({
            "metric_id": metric.id,
            "metric_name": metric.name,
            "unit": metric.unit,
            "direction": metric.direction,
            "weight": weight,
            "weight_ratio": weight_ratio,
            "is_target_metric": metric.is_target_metric,
            "rkap_item_id": metric.rkap_item_id,
            "rkap_item_label": str(metric.rkap_item) if metric.rkap_item_id else "",
            "target_value": _safe_float(metric_target) if metric_target not in (None, "") else None,
            "average_selling_price": _safe_float(metric.average_selling_price),
            "risk_appetite_threshold": _safe_float(metric.risk_appetite_threshold),
            "risk_appetite_value": (
                _safe_float(metric.risk_appetite_value)
                if metric.risk_appetite_value not in (None, "")
                else None
            ),
            "last_actual": last_actual,
            "distribution_recommendation": {
                "recommended": distribution_recommendation.get("recommended"),
                "recommended_label": distribution_recommendation.get("recommended_label"),
                "history_count": distribution_recommendation.get("history_count"),
                "growth_mean": distribution_recommendation.get("growth_mean"),
                "growth_std": distribution_recommendation.get("growth_std"),
                "reason_summary": distribution_recommendation.get("reason_summary"),
                "reason_detail": distribution_recommendation.get("reason_detail"),
                "limitations": distribution_recommendation.get("limitations"),
                "confidence": distribution_recommendation.get("confidence"),
                "data_quality_warnings": distribution_recommendation.get("data_quality_warnings", []),
                "alternative_distributions": distribution_recommendation.get("alternative_distributions", []),
            },

            "history_rows": [
                {
                    "periode": str(h.periode) if h.periode else "-",
                    "tanggal": h.tanggal_data.isoformat() if h.tanggal_data else None,
                    "actual": _safe_float(h.metric_value),
                    "actual_score": _normalize_metric_score(
                        metric=metric,
                        projected_value=_safe_float(h.metric_value),
                        last_actual_value=last_actual,
                    ),
                }
                for h in histories
            ],

            "mean_score": mean_score,
            "p80_score": p80_score,

            "scenario_score": scenario_score,
            "scenario_total": scenario_total,
            "scenario_percentile": scenario_percentile,

            "actual_total": simulation["actual_total"],
            "future_mean_total": simulation["future_mean_total"],
            "full_year_expected": simulation["full_year_expected"],
            "p5_total": simulation["p5_total"],
            "p50_total": simulation["p50_total"],
            "p80_total": simulation["p80_total"],
            "p95_total": simulation["p95_total"],
            "projection_rows": enriched_projection_rows,
            # descriptive_stats dari _simulate_metric (untuk Tahap 2)
            "descriptive_stats": simulation.get("descriptive_stats", {}),
        })

        if not target_analysis and metric.is_target_metric:
            target_analysis = _build_target_analysis(
                simulation_totals=simulation["simulation_totals"],
                target_value=metric_target,
                actual_total=simulation["actual_total"],
                average_selling_price=metric.average_selling_price,
                risk_appetite_threshold=metric.risk_appetite_threshold,
                risk_appetite_value=metric.risk_appetite_value,
            )

    if not target_analysis:
        for metric_row in metric_results:
            if metric_row.get("target_value") not in (None, ""):
                metric_obj = next(
                    (m for m in metrics if m.id == metric_row.get("metric_id")),
                    None,
                )
                histories = list(
                    MonteCarloMetricHistory.objects.filter(metric=metric_obj)
                    .filter(tanggal_data__lte=forecast_periode.tanggal_selesai)
                    .select_related("periode")
                    .order_by("tanggal_data", "id")
                )

                simulation = _simulate_metric(
                    values=[_safe_float(h.metric_value) for h in histories],
                    months_ahead=months_ahead,
                    n_simulations=n_simulations,
                    actual_total=metric_row.get("actual_total"),
                    distribution_type=distribution_type,
                    sma_window=3,
                )
                target_analysis = _build_target_analysis(
                    simulation_totals=simulation["simulation_totals"],
                    target_value=metric_row.get("target_value"),
                    actual_total=simulation["actual_total"],
                    average_selling_price=metric_row.get("average_selling_price"),
                    risk_appetite_threshold=metric_row.get("risk_appetite_threshold"),
                    risk_appetite_value=metric_row.get("risk_appetite_value"),
                )
                break

    distribution_counts = {}
    confidence_rank = {"Low": 1, "Medium": 2, "High": 3}
    aggregate_warnings = [
        "Simulasi multi metric saat ini memakai satu model distribusi global untuk beberapa metric. Rekomendasi agregat adalah kompromi; karakter tiap metric tetap perlu ditinjau."
    ]
    metric_distribution_analyses = []
    for metric_row in metric_results:
        recommendation = metric_row.get("distribution_recommendation", {})
        recommended = recommendation.get("recommended") or "empirical"
        distribution_counts[recommended] = distribution_counts.get(recommended, 0) + 1
        aggregate_warnings.extend(recommendation.get("data_quality_warnings") or [])
        metric_distribution_analyses.append({
            "metric_id": metric_row.get("metric_id"),
            "metric_name": metric_row.get("metric_name"),
            "recommended_distribution": recommended,
            "recommended_label": recommendation.get("recommended_label"),
            "data_count": recommendation.get("history_count"),
            "mean_growth": recommendation.get("growth_mean"),
            "std_growth": recommendation.get("growth_std"),
            "reason_summary": recommendation.get("reason_summary"),
            "reason_detail": recommendation.get("reason_detail"),
            "limitations": recommendation.get("limitations"),
            "confidence": recommendation.get("confidence"),
            "warnings": recommendation.get("data_quality_warnings") or [],
            "alternative_distributions": recommendation.get("alternative_distributions") or [],
        })

    recommended_distribution = "empirical"
    if distribution_counts:
        recommended_distribution = sorted(
            distribution_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[0][0]
    selected_recommendations = [
        row for row in metric_distribution_analyses
        if row.get("recommended_distribution") == recommended_distribution
    ]
    aggregate_confidence = "Low"
    if selected_recommendations:
        lowest_rank = min(
            confidence_rank.get(row.get("confidence") or "Low", 1)
            for row in selected_recommendations
        )
        aggregate_confidence = next(
            label for label, rank in confidence_rank.items()
            if rank == lowest_rank
        )
    aggregate_profile = recommend_monte_carlo_distribution([
        row.get("last_actual") for row in metric_results
    ])
    aggregate_reason_summary = (
        f"Mayoritas metric aktif merekomendasikan {_distribution_label(recommended_distribution)} "
        f"({distribution_counts.get(recommended_distribution, 0)} dari {len(metric_results)} metric)."
    )
    aggregate_reason_detail = (
        aggregate_reason_summary
        + " Pilihan global harus dibaca sebagai kompromi karena setiap metric dapat memiliki karakter distribusi berbeda. "
        + (aggregate_profile.get("reason_detail") or "")
    )
    aggregate_limitations = (
        "Satu distribusi global dapat kurang akurat bila metric memiliki bentuk data berbeda. "
        "Untuk presisi lebih tinggi, distribusi per metric perlu diimplementasikan pada fase refactor berikutnya."
    )
    aggregate_warnings = list(dict.fromkeys(warning for warning in aggregate_warnings if warning))

    composite_score = sum([
        row["mean_score"] * row["weight_ratio"]
        for row in metric_results
    ])

    p80_score = sum([
        row["p80_score"] * row["weight_ratio"]
        for row in metric_results
    ])

    scenario_score = sum([
        row["scenario_score"] * row["weight_ratio"]
        for row in metric_results
    ])

    multi_metric_history_rows = _build_multi_metric_history_rows(metric_results)
    multi_metric_projection_rows = _build_multi_metric_projection_rows(metric_results)
    target_metric_row = next(
        (
            row for row in metric_results
            if row.get("is_target_metric") and row.get("target_value") not in (None, "")
        ),
        None,
    )
    if target_metric_row is None:
        target_metric_row = next(
            (row for row in metric_results if row.get("target_value") not in (None, "")),
            None,
        )
    target_projection_rows = []

    last_history_date = None

    for metric_row in metric_results:
        history_rows = metric_row.get("history_rows", [])
        if history_rows:
            tanggal = history_rows[-1].get("tanggal")
            if tanggal:
                from datetime import date
                parsed_date = date.fromisoformat(tanggal)
                if last_history_date is None or parsed_date > last_history_date:
                    last_history_date = parsed_date

    for idx, row in enumerate(multi_metric_projection_rows):
        if last_history_date:
            forecast_date = last_history_date + relativedelta(months=idx + 1)
            row["bulan"] = _format_month_year_id(forecast_date)
        else:
            row["bulan"] = f"Bulan-{idx + 1}"

    if target_metric_row:
        for idx, row in enumerate(target_metric_row.get("projection_rows", [])):
            if last_history_date:
                forecast_date = last_history_date + relativedelta(months=idx + 1)
                bulan = _format_month_year_id(forecast_date)
            else:
                bulan = f"Bulan-{idx + 1}"
            target_projection_rows.append({
                "bulan_index": idx + 1,
                "bulan": bulan,
                "metric_name": target_metric_row.get("metric_name"),
                "forecast_median": row.get("p50"),
                "forecast_p15": row.get("p15"),
                "stdev_f": row.get("stdev_f"),
                "mean": row.get("mean"),
                "p20": row.get("p20"),
                "p40": row.get("p40"),
                "p60": row.get("p60"),
                "p80": row.get("p80"),
            })

    chart_series = {
        "labels": [
            row.get("bulan") or f"Bulan-{row.get('bulan_index')}"
            for row in multi_metric_projection_rows
        ],
        "mean": [
            row.get("mean_score", 0)
            for row in multi_metric_projection_rows
        ],
        "p20": [
            row.get("p20_score", 0)
            for row in multi_metric_projection_rows
        ],
        "p40": [
            row.get("p40_score", 0)
            for row in multi_metric_projection_rows
        ],
        "p60": [
            row.get("p60_score", 0)
            for row in multi_metric_projection_rows
        ],
        "p80": [
            row.get("p80_score", 0)
            for row in multi_metric_projection_rows
        ],
    }
    # Tahap 2: tampilkan deskriptif prediksi sebelum simulasi (Excel-style)
    # Ambil descriptive rows dari metric target (jika ada), jika tidak: dari metric pertama.
    descriptive_projection_rows = []
    descriptive_stats = {}
    source_metric_for_descriptive = _select_descriptive_metric(metric_results, target_metric_row)
    if source_metric_for_descriptive and source_metric_for_descriptive.get("projection_rows"):
        # projection_rows untuk metric hasil berisi mean_score/p15_score dst; tapi yang kita butuhkan F P50/F P15/Std Dev
        # untuk UI Excel: gunakan proyeksi mentah dari _simulate_metric tersimpan di simulation snapshot per metric.
        # Karena sekarang projection_rows metric_results adalah score-normalized, kita bangun ulang berdasarkan stdev_f yang tersimpan di projection_rows.
        for idx, row in enumerate(source_metric_for_descriptive.get("projection_rows", [])):
            if last_history_date:
                forecast_date = last_history_date + relativedelta(months=idx + 1)
                bulan = _format_month_year_id(forecast_date)
            else:
                bulan = f"Bulan-{idx + 1}"
            descriptive_projection_rows.append({
                "bulan_index": idx + 1,
                "bulan": bulan,
                "f_p50": row.get("p50"),
                "f_p15": row.get("p15"),
                "std_dev": row.get("stdev_f"),
                "mean": row.get("mean"),
            })
        descriptive_stats = source_metric_for_descriptive.get("descriptive_stats", {}) or {}
        descriptive_stats["source_metric_name"] = source_metric_for_descriptive.get("metric_name") or "-"

    if target_analysis:
        chart_series["target_distribution"] = target_analysis.get("distribution_sample", [])
        chart_series["target_distribution_total_simulation"] = target_analysis.get("total_simulation") or n_simulations
        chart_series["target_value"] = target_analysis.get("target_value")
        chart_series["target_monthly_projection"] = target_projection_rows

    # Dampak Excel: Target - (Best/Base/Worst)
    # Best  = P95 total
    # Base  = P50 total
    # Worst = P5 total
    dampak_best_case = None
    dampak_base_case = None
    dampak_worst_case = None
    if target_analysis:
        target_val = _safe_float(target_analysis.get("target_value"))
        dampak_best_case = target_val - _safe_float(target_analysis.get("best_case_value"))
        dampak_base_case = target_val - _safe_float(target_analysis.get("baseline_value"))
        dampak_worst_case = target_val - _safe_float(target_analysis.get("worst_case_value"))

    status_hasil = _status_from_score(scenario_score)

    result = _replace_result(
        MultiMetricMonteCarloResult,
        {
            "corporate_risk_item": item,
            "forecast_periode": forecast_periode,
        },
        {
            "composite_score": _decimal_18(composite_score) or Decimal("0"),
            "p80_score": _decimal_18(p80_score) or Decimal("0"),
            "forecast_total": _decimal(target_analysis.get("forecast_total")),
            "target_value": _decimal(target_analysis.get("target_value")),
            "target_gap": _decimal(target_analysis.get("target_gap")) or Decimal("0"),
            "average_selling_price": _decimal(target_analysis.get("average_selling_price")) or Decimal("0"),
            "potential_loss": _decimal(target_analysis.get("potential_loss")) or Decimal("0"),
            "dampak_best_case": _decimal(dampak_best_case),
            "dampak_base_case": _decimal(dampak_base_case),
            "dampak_worst_case": _decimal(dampak_worst_case),
            "probability_achieve_target": _decimal_probability(target_analysis.get("probability_achieve_target")),
            "probability_not_achieve_target": _decimal_probability(target_analysis.get("probability_not_achieve_target")),
            "target_status": target_analysis.get("target_status", ""),
            "risk_status": target_analysis.get("risk_status", ""),
            "worst_case_value": _decimal(target_analysis.get("worst_case_value")),
            "baseline_value": _decimal(target_analysis.get("baseline_value")),
            "best_case_value": _decimal(target_analysis.get("best_case_value")),
            "var_95": _decimal(target_analysis.get("var_95")) or Decimal("0"),
            "requires_mitigation": bool(target_analysis.get("requires_mitigation", False)),
            "status_hasil": status_hasil,
            "distribution_type": distribution_type,
            "recommended_distribution": recommended_distribution,
            "distribution_reason_summary": aggregate_reason_summary,
            "distribution_reason_detail": aggregate_reason_detail,
            "distribution_limitations": aggregate_limitations,
            "distribution_confidence": aggregate_confidence,
            "distribution_data_quality_warnings": aggregate_warnings,
            "selected_distribution": distribution_type,
            "selected_distribution_justification": selected_distribution_justification or "",
            "metric_snapshot": {
                "metrics": metric_results,
                "distribution_analyses": metric_distribution_analyses,
            },
            "simulation_snapshot": {
                "months_ahead": months_ahead,
                "n_simulations": n_simulations,
                "scenario_percentile": scenario_percentile,
                "distribution_type": distribution_type,
                "recommended_distribution": recommended_distribution,
                "distribution_analysis": {
                    "recommended_distribution": recommended_distribution,
                    "recommended_label": _distribution_label(recommended_distribution),
                    "selected_distribution": distribution_type,
                    "selected_distribution_label": _distribution_label(distribution_type),
                    "reason_summary": aggregate_reason_summary,
                    "reason_detail": aggregate_reason_detail,
                    "limitations": aggregate_limitations,
                    "confidence": aggregate_confidence,
                    "warnings": aggregate_warnings,
                    "metric_analyses": metric_distribution_analyses,
                    "selected_distribution_justification": selected_distribution_justification or "",
                },
                "composite_score": composite_score,
                "p80_score": p80_score,
                "scenario_score": scenario_score,
                "status_hasil": status_hasil,
                "target_analysis": target_analysis,
                "target_projection_rows": target_projection_rows,
                # Tahap 1
                "history_rows": multi_metric_history_rows,
                # Tahap 2
                "descriptive_projection_rows": descriptive_projection_rows,
                "descriptive_stats": descriptive_stats,
                # Multi metric projection (untuk grafik & score bulanan)
                "projection_rows": multi_metric_projection_rows,
                "chart_series": chart_series,
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
        number = float(value or 0)
        if not math.isfinite(number):
            return 0.0
        return number
    except (TypeError, ValueError, OverflowError):
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
    distribution_type: str = "normal",
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
    actual_total = sum(actual_values)
    simulation_totals: list[float] = []

    for _ in range(n_simulations):
        simulated = current
        future_total = 0.0
        for month_idx in range(months_ahead):
            sampled_growth = _sample_growth(growth_rates, avg_growth, std_growth, distribution_type)

            # guard rail agar proyeksi tidak terlalu liar
            sampled_growth = max(min(sampled_growth, 3.0), -0.95)

            simulated = simulated * (1 + sampled_growth)
            simulated = max(simulated, 0.0)
            future_total += simulated

            monthly_results[month_idx].append(simulated)

        simulation_totals.append(actual_total + future_total)

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
        "distribution_type": distribution_type,
        "distribution_label": _distribution_label(distribution_type),
        "projection_rows": projection_rows,
        "summary": {
            "actual_ytd_total": sum(actual_values),
            "future_mean_total": future_mean_total,
            "full_year_expected": sum(actual_values) + future_mean_total,
            "p5_total": percentile(simulation_totals, 0.05),
            "p50_total": percentile(simulation_totals, 0.50),
            "p95_total": percentile(simulation_totals, 0.95),
            "min_total": min(simulation_totals) if simulation_totals else 0.0,
            "max_total": max(simulation_totals) if simulation_totals else 0.0,
            "p20_total": p20_total,
            "p40_total": p40_total,
            "p60_total": p60_total,
            "p80_total": p80_total,
            "simulation_totals": simulation_totals,
        },
    }


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
        n_simulations=int(config.n_simulations or 10000),
        distribution_type=config.distribution_type or "normal",
    )

    summary = simulation_snapshot.get("summary", {})
    actual_ytd_total = _safe_float(summary.get("actual_ytd_total"))
    future_mean_total = _safe_float(summary.get("future_mean_total"))
    full_year_expected = _safe_float(summary.get("full_year_expected"))
    p20_total = _safe_float(summary.get("p20_total"))
    p40_total = _safe_float(summary.get("p40_total"))
    p60_total = _safe_float(summary.get("p60_total"))
    p80_total = _safe_float(summary.get("p80_total"))
    p50_total = _safe_float(summary.get("p50_total"))
    p95_total = _safe_float(summary.get("p95_total"))
    p5_total = _safe_float(summary.get("p5_total"))

    mean_value = future_mean_total
    p50_value = p50_total
    p80_value = p80_total
    p90_value = percentile(summary.get("simulation_totals", []), 0.90)
    min_value = _safe_float(summary.get("min_total"))
    max_value = _safe_float(summary.get("max_total"))

    target_values = [
        _safe_float(h.target_value)
        for h in histories
        if h.target_value not in (None, "")
    ]
    target_value = sum(target_values) if target_values else None

    target_analysis = _build_target_analysis(
        simulation_totals=summary.get("simulation_totals", []),
        target_value=target_value,
        actual_total=actual_ytd_total,
        average_selling_price=0,
        risk_appetite_threshold=20,
        risk_appetite_value=None,
    )
    probability_meet_target = target_analysis.get("probability_achieve_target")

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
        "p95_total": p95_total,
        "target_analysis": target_analysis,
        "realization_percent": realization_percent or 0.0,
        "distribution_type": config.distribution_type or "normal",
        "distribution_label": _distribution_label(config.distribution_type or "normal"),
    })

    # =========================
    # KUNCI AGAR TIDAK DOBEL
    # =========================
    result = _replace_result(
        MonteCarloKorporatResult,
        {
            "corporate_risk_item": item,
            "forecast_periode": forecast_periode,
            "metric_name": config.metric_name,
        },
        {
            "mean_value": _decimal_18(mean_value),
            "p50_value": _decimal_18(p50_value),
            "p80_value": _decimal_18(p80_value),
            "p90_value": _decimal_18(p90_value),
            "min_value": _decimal_18(min_value),
            "max_value": _decimal_18(max_value),
            "probability_meet_target": _decimal_probability(probability_meet_target),
            "target_value": _decimal_18(target_value),
            "forecast_total": _decimal(target_analysis.get("forecast_total")),
            "target_gap": _decimal(target_analysis.get("target_gap")) or Decimal("0"),
            "average_selling_price": _decimal(target_analysis.get("average_selling_price")) or Decimal("0"),
            "potential_loss": _decimal(target_analysis.get("potential_loss")) or Decimal("0"),
            "probability_achieve_target": _decimal_probability(target_analysis.get("probability_achieve_target")),
            "probability_not_achieve_target": _decimal_probability(target_analysis.get("probability_not_achieve_target")),
            "target_status": target_analysis.get("target_status", ""),
            "risk_status": target_analysis.get("risk_status", ""),
            "worst_case_value": _decimal(target_analysis.get("worst_case_value")) or _decimal(p5_total),
            "baseline_value": _decimal(target_analysis.get("baseline_value")) or _decimal(p50_total),
            "best_case_value": _decimal(target_analysis.get("best_case_value")) or _decimal(p95_total),
            "var_95": _decimal(target_analysis.get("var_95")) or Decimal("0"),
            "requires_mitigation": bool(target_analysis.get("requires_mitigation", False)),
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
    metric_name = result.metric_name or "metric risiko"
    metric_lower = metric_name.lower()

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

    if "piutang" in metric_lower:
        risk_label = "risiko saldo piutang"
        driver_1 = "Volatilitas historis saldo piutang dan pola pembayaran pelanggan."
        driver_3 = "Adanya potensi peningkatan outstanding atau keterlambatan pembayaran pada periode proyeksi."
        driver_4 = "Risiko utama adalah tekanan terhadap arus kas, aging piutang, dan potensi penurunan kolektibilitas."
        actions = (
            "1. Percepat penagihan dan monitoring aging piutang secara berkala.\n"
            "2. Prioritaskan penyelesaian pelanggan/saldo dengan risiko keterlambatan terbesar.\n"
            "3. Koordinasikan rencana penurunan outstanding dengan unit komersial dan keuangan.\n"
            "4. Tetapkan trigger eskalasi untuk saldo piutang yang melewati risk appetite.\n"
            "5. Evaluasi efektivitas kebijakan pembayaran, reminder, dan mekanisme penagihan."
        )
    elif "cyber" in metric_lower or "siber" in metric_lower or "incident" in metric_lower:
        risk_label = "risiko siber"
        driver_1 = "Volatilitas historis incident cyber yang tinggi."
        driver_3 = "Adanya potensi lonjakan ancaman pada periode proyeksi."
        driver_4 = (
            "Risiko utama bukan hanya jumlah threat, tetapi kemungkinan eskalasi "
            "menjadi insiden yang mengganggu atau merusak sistem."
        )
        actions = (
            "1. Perkuat monitoring dan early warning untuk aset IT/OT kritikal.\n"
            "2. Tingkatkan kesiapan incident response dan containment playbook.\n"
            "3. Prioritaskan hardening, patching, dan segmentasi jaringan pada sistem kritikal.\n"
            "4. Lakukan evaluasi berkala atas kontrol mitigasi agar threat tidak berkembang "
            "menjadi gangguan operasional.\n"
            "5. Fokuskan pengendalian pada zero tolerance terhadap insiden yang merusak sistem."
        )
    else:
        risk_label = f"risiko pada metric {metric_name}"
        driver_1 = f"Volatilitas historis {metric_name}."
        driver_3 = "Adanya potensi perubahan nilai pada periode proyeksi."
        driver_4 = "Risiko utama adalah deviasi terhadap target, threshold, atau risk appetite yang ditetapkan."
        actions = (
            "1. Monitor realisasi dan deviasi terhadap target secara berkala.\n"
            "2. Identifikasi driver utama yang memengaruhi perubahan proyeksi.\n"
            "3. Tetapkan trigger eskalasi saat proyeksi melewati risk appetite.\n"
            "4. Evaluasi efektivitas kontrol dan rencana mitigasi berjalan.\n"
            "5. Perbarui data historis agar simulasi mencerminkan kondisi terbaru."
        )

    executive_summary = (
        f"Berdasarkan hasil simulasi Monte Carlo untuk metric '{metric_name}', {risk_label} pada item "
        f"'{result.corporate_risk_item}' menunjukkan profil eksposur {tingkat} "
        f"dengan tingkat kemungkinan indikatif {kemungkinan}. "
        f"Proyeksi hingga akhir periode memperlihatkan pola {tren}, dengan "
        f"full year expected sebesar {full_year_expected:,.3f} dan "
        f"skenario konservatif P80 sebesar {p80_total:,.3f}. "
        f"Realisasi year-to-date saat ini masih berada pada {realization_percent:,.2f}% "
        f"dari skenario konservatif."
    )

    key_drivers = (
        f"1. {driver_1}\n"
        f"2. Proyeksi mean sisa periode sebesar {future_mean_total:,.3f}.\n"
        f"3. {driver_3}\n"
        f"4. {driver_4}"
    )

    insight, _ = AIInsightKorporat.objects.update_or_create(
        corporate_risk_item=result.corporate_risk_item,
        monte_carlo_result=result,
        defaults={
            "executive_summary": executive_summary,
            "key_drivers": key_drivers,
            "recommended_actions": actions,
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
    

def generate_rule_based_ai_insight_for_multi_metric_result(result):
    metrics = (result.metric_snapshot or {}).get("metrics", [])
    snapshot = result.simulation_snapshot or {}
    projection_rows = snapshot.get("projection_rows", [])
    target_analysis = snapshot.get("target_analysis") or {}

    if not metrics:
        raise ValueError("Metric snapshot belum tersedia.")

    top_metric = max(
        metrics,
        key=lambda x: float(x.get("mean_score") or 0)
    )

    weak_metrics = [
        m.get("metric_name", "-")
        for m in metrics
        if float(m.get("mean_score") or 0) <= 20
    ]

    trend = "relatif stabil"
    if projection_rows:
        first_score = float(projection_rows[0].get("mean_score") or 0)
        last_score = float(projection_rows[-1].get("mean_score") or 0)

        if last_score > first_score + 5:
            trend = "meningkat"
        elif last_score < first_score - 5:
            trend = "menurun"

    risk_item = result.corporate_risk_item
    risk_number = getattr(risk_item, "no_item", None)
    risk_title = getattr(risk_item, "peristiwa_risiko", None) or str(risk_item)
    risk_label = f"Risiko {risk_number} - {risk_title}" if risk_number else risk_title

    executive_summary = (
        f"Berdasarkan hasil simulasi multi-metric Monte Carlo, {risk_label} "
        f"untuk periode forecast {result.forecast_periode} berada pada level {result.status_hasil} "
        f"dengan Composite Risk Score sebesar {float(result.composite_score):,.2f} "
        f"dan skenario konservatif P80 sebesar {float(result.p80_score):,.2f}. "
        f"Tren proyeksi bulanan menunjukkan pola {trend}."
    )
    if target_analysis:
        mitigation_text = (
            "perlu mitigasi"
            if result.requires_mitigation
            else "cukup dimonitor dengan trigger bulanan"
        )
        executive_summary = (
            f"{risk_label} untuk periode forecast {result.forecast_periode} memiliki status target "
            f"{result.target_status or '-'} dan status risiko {result.risk_status or '-'}. "
            f"Forecast total berbasis median/P50 sebesar {float(result.forecast_total or 0):,.0f}, "
            f"dibandingkan target RKAP {float(result.target_value or 0):,.0f}. "
            f"Gap terhadap target sebesar {float(result.target_gap or 0):,.0f} dengan estimasi "
            f"potential loss {float(result.potential_loss or 0):,.0f}. "
            f"Probabilitas target tercapai {float(result.probability_achieve_target or 0):,.2f}% "
            f"dan probabilitas target tidak tercapai {float(result.probability_not_achieve_target or 0):,.2f}%. "
            f"VaR 95% tercatat sebesar {float(result.var_95 or 0):,.0f}. "
            f"Berdasarkan risk appetite, risiko ini {mitigation_text}."
        )

    key_findings = (
        f"Driver utama risiko adalah {top_metric.get('metric_name', '-')} "
        f"dengan score {float(top_metric.get('mean_score') or 0):,.2f}. "
        f"Hal ini menunjukkan bahwa profil risiko sangat dipengaruhi oleh metric tersebut."
    )

    if weak_metrics:
        key_findings += (
            f"\nMetric yang perlu perhatian khusus adalah: {', '.join(weak_metrics)} "
            f"karena memiliki score rendah terhadap target/threshold."
        )
    if target_analysis:
        key_findings += (
            f"\nForecast total berbasis median/P50 sebesar {float(result.forecast_total or 0):,.2f}, "
            f"target RKAP {float(result.target_value or 0):,.2f}, gap {float(result.target_gap or 0):,.2f}, "
            f"potential loss {float(result.potential_loss or 0):,.2f}, dan VaR 95% {float(result.var_95 or 0):,.2f}."
        )

    recommended_actions = (
        "1. Prioritaskan mitigasi pada metric dengan kontribusi risiko terbesar.\n"
        "2. Review threshold dan target pada metric dengan score rendah.\n"
        "3. Lakukan monitoring bulanan terhadap tren aktual dan proyeksi.\n"
        "4. Bandingkan hasil simulasi dengan risk appetite perusahaan.\n"
        "5. Gunakan skenario P80 sebagai dasar kewaspadaan manajemen."
    )
    if target_analysis and result.requires_mitigation:
        recommended_actions += (
            "\n6. Karena probabilitas target tidak tercapai atau potential loss melewati risk appetite, "
            "siapkan rencana mitigasi demand/penjualan dan trigger eskalasi bulanan."
        )

    executive_summary, key_findings, recommended_actions = _polish_multi_metric_insight_with_ai(
        result,
        executive_summary,
        key_findings,
        recommended_actions,
    )

    insight, _ = MultiMetricAIInsightKorporat.objects.update_or_create(
        multi_metric_result=result,
        defaults={
            "executive_summary": executive_summary,
            "key_findings": key_findings,
            "recommended_actions": recommended_actions,
        },
    )

    return insight
