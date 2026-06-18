from __future__ import annotations

import math
from statistics import mean, median


DISTRIBUTION_PROFILES = {
    "normal": {
        "summary": "Data relatif stabil dan variasinya berada di sekitar nilai rata-rata.",
        "detail": (
            "Distribusi Normal cocok ketika data relatif simetris, variasi tidak ekstrem, "
            "dan nilai dapat menyebar di sekitar rata-rata."
        ),
        "limitations": (
            "Distribusi Normal dapat menghasilkan nilai negatif, sehingga kurang cocok untuk "
            "metric yang secara bisnis tidak mungkin negatif kecuali hasil simulasi dibatasi minimum 0."
        ),
    },
    "lognormal": {
        "summary": "Data non-negatif dengan variasi pertumbuhan tinggi atau kecenderungan skew kanan.",
        "detail": (
            "Lognormal direkomendasikan karena data bernilai non-negatif dan cocok untuk metric "
            "yang dapat meningkat secara multiplikatif atau tidak linear."
        ),
        "limitations": (
            "Lognormal sensitif terhadap outlier dan dapat menghasilkan ekor kanan panjang; "
            "skenario ekstrem perlu divalidasi dengan expert judgment."
        ),
    },
    "triangular": {
        "summary": "Data historis terbatas, sehingga pendekatan sederhana berbasis min-most likely-max lebih realistis.",
        "detail": (
            "Triangular dapat digunakan ketika data historis sedikit tetapi tersedia estimasi minimum, "
            "nilai paling mungkin, dan maksimum dari expert judgment."
        ),
        "limitations": "Sangat bergantung pada asumsi subjektif dan tidak menangkap bentuk distribusi historis secara penuh.",
    },
    "uniform": {
        "summary": "Tidak ada bukti kuat bahwa satu nilai dalam rentang historis lebih mungkin dari nilai lain.",
        "detail": (
            "Uniform dapat dipakai ketika informasi bentuk distribusi tidak cukup dan seluruh nilai "
            "dalam rentang min-maks dianggap sama kemungkinannya."
        ),
        "limitations": "Terlalu sederhana dan sering tidak realistis karena menganggap semua nilai sama kemungkinannya.",
    },
    "beta": {
        "summary": "Metric tampak bounded atau dapat dinormalisasi ke rentang terbatas.",
        "detail": (
            "Beta cocok untuk probabilitas, rasio, persentase, tingkat pencapaian, atau indikator yang "
            "memiliki batas bawah dan atas yang jelas."
        ),
        "limitations": "Perlu batas minimum dan maksimum yang valid; batas bisnis yang keliru dapat menyesatkan simulasi.",
    },
    "gamma": {
        "summary": "Data continuous non-negatif dan cenderung skew ke kanan.",
        "detail": (
            "Gamma cocok untuk data continuous non-negatif yang skew ke kanan seperti biaya, durasi, "
            "severity, atau besaran kerugian."
        ),
        "limitations": "Kurang cocok bila data berisi banyak nol atau merupakan hitungan kejadian diskrit.",
    },
    "weibull": {
        "summary": "Metric dapat merepresentasikan failure rate, downtime, reliability, atau pola risiko terhadap waktu.",
        "detail": (
            "Weibull cocok bila metric berkaitan dengan waktu sampai kejadian atau tingkat kegagalan "
            "yang berubah terhadap waktu."
        ),
        "limitations": "Tidak ideal untuk metric operasional umum tanpa justifikasi bisnis terkait failure/time-to-event.",
    },
    "empirical": {
        "summary": "Pola historis digunakan langsung tanpa asumsi distribusi parametrik.",
        "detail": (
            "Empirical Distribution cocok jika data historis cukup banyak dan pola masa lalu dianggap "
            "representatif."
        ),
        "limitations": (
            "Tidak mengekstrapolasi skenario di luar data historis dengan baik dan sangat bergantung "
            "pada representativitas data masa lalu."
        ),
    },
}


def _safe_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _stdev(values):
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / (len(values) - 1))


def _skewness(values):
    if len(values) < 3:
        return 0.0
    avg = mean(values)
    std = _stdev(values)
    if not std:
        return 0.0
    return sum(((value - avg) / std) ** 3 for value in values) / len(values)


def _growth_rates(values):
    rates = []
    for idx in range(1, len(values)):
        previous = values[idx - 1]
        current = values[idx]
        if previous:
            rates.append((current - previous) / abs(previous))
    return rates


def _has_outlier(values):
    if len(values) < 4:
        return False
    sorted_values = sorted(values)
    q1 = sorted_values[len(sorted_values) // 4]
    q3 = sorted_values[(len(sorted_values) * 3) // 4]
    iqr = q3 - q1
    if iqr <= 0:
        return False
    lower = q1 - (1.5 * iqr)
    upper = q3 + (1.5 * iqr)
    return any(value < lower or value > upper for value in values)


def _alternative_distributions(recommended_distribution, data_count):
    alternatives = {
        "lognormal": [
            ("gamma", "Sama-sama cocok untuk data non-negatif skewed.", "Kurang cocok jika data banyak nol."),
            ("empirical", "Menghindari asumsi parametrik.", "Butuh data historis representatif."),
        ],
        "beta": [
            ("empirical", "Dapat mengikuti pola historis bounded secara langsung.", "Data terbatas dapat membuat hasil rapuh."),
            ("triangular", "Bisa digunakan jika batas min-most likely-max jelas.", "Bergantung pada expert judgment."),
        ],
        "gamma": [
            ("lognormal", "Alternatif untuk data non-negatif dengan ekor kanan.", "Sensitif terhadap outlier."),
            ("empirical", "Lebih sedikit asumsi bentuk distribusi.", "Tidak mengekstrapolasi ekstrem baru dengan baik."),
        ],
    }.get(
        recommended_distribution,
        [
            ("empirical", "Dapat digunakan bila tidak ingin asumsi parametrik.", "Membutuhkan data representatif."),
            ("triangular", "Berguna saat data terbatas dan ada expert judgment.", "Sangat subjektif."),
        ],
    )
    if data_count < 12 and recommended_distribution != "triangular":
        alternatives.insert(
            0,
            ("triangular", "Data historis terbatas sehingga expert judgment dapat membantu.", "Asumsi sangat subjektif."),
        )
    return [
        {"distribution": value, "reason": reason, "limitation": limitation}
        for value, reason, limitation in alternatives[:3]
    ]


def analyze_distribution_recommendation(metric, history_values, recommended_distribution):
    values = [_safe_float(value) for value in history_values]
    values = [value for value in values if value is not None]
    rates = _growth_rates(values)
    data_count = len(values)
    zero_count = sum(1 for value in values if value == 0)
    non_negative = bool(values) and all(value >= 0 for value in values)
    all_integer = bool(values) and all(float(value).is_integer() for value in values)
    avg = mean(values) if values else None
    med = median(values) if values else None
    std = _stdev(values) if values else None
    cv = abs(std / avg) if avg else 0
    skew = _skewness(values) if len(values) >= 3 else 0
    growth_mean = mean(rates) if rates else None
    growth_std = _stdev(rates) if rates else None
    outlier = _has_outlier(values)

    warnings = []
    if data_count < 24:
        warnings.append("Data historis kurang dari 24 periode. Rekomendasi perlu divalidasi dengan expert judgment.")
    if data_count < 12:
        warnings.append("Jumlah data historis sangat terbatas sehingga confidence rendah.")
    if values and zero_count / data_count >= 0.25:
        warnings.append("Data mengandung banyak nilai nol. Pertimbangkan distribusi diskrit, zero-inflated, atau empirical.")
    if outlier:
        warnings.append("Terdapat indikasi outlier. Validasi apakah outlier merupakan kejadian valid atau anomali pencatatan.")
    if growth_std is not None and abs(growth_std) > 1:
        warnings.append("Volatilitas pertumbuhan tinggi. Distribusi ekor kanan perlu ditinjau agar skenario ekstrem tidak berlebihan.")
    if non_negative and recommended_distribution == "normal":
        warnings.append("Metric ini secara bisnis tampak tidak boleh negatif. Hindari Normal kecuali simulasi dibatasi minimum 0.")
    if all_integer and non_negative:
        warnings.append("Data tampak berupa count/frequency. Pertimbangkan juga pendekatan distribusi diskrit atau empirical.")

    if data_count >= 36 and not outlier and len(warnings) <= 1:
        confidence = "High"
    elif data_count >= 12 and len(warnings) <= 3:
        confidence = "Medium"
    else:
        confidence = "Low"

    profile = DISTRIBUTION_PROFILES.get(recommended_distribution, DISTRIBUTION_PROFILES["empirical"])
    characteristics = [
        f"Jumlah data: {data_count}",
        f"Non-negatif: {'ya' if non_negative else 'tidak'}",
        f"Zero count: {zero_count}",
        f"Mean: {avg:.4f}" if avg is not None else "Mean: -",
        f"Median: {med:.4f}" if med is not None else "Median: -",
        f"Std dev: {std:.4f}" if std is not None else "Std dev: -",
        f"Coefficient of variation: {cv:.4f}",
        f"Skewness: {skew:.4f}",
        f"Mean growth: {growth_mean:.6f}" if growth_mean is not None else "Mean growth: -",
        f"Std growth: {growth_std:.6f}" if growth_std is not None else "Std growth: -",
    ]

    return {
        "recommended_distribution": recommended_distribution,
        "reason_summary": profile["summary"],
        "reason_detail": f"{profile['detail']} Karakteristik data: " + "; ".join(characteristics) + ".",
        "limitations": profile["limitations"],
        "confidence": confidence,
        "data_quality_warnings": warnings,
        "alternative_distributions": _alternative_distributions(recommended_distribution, data_count),
        "data_count": data_count,
        "zero_count": zero_count,
        "non_negative": non_negative,
        "is_count_like": all_integer and non_negative,
        "mean": avg,
        "median": med,
        "std_dev": std,
        "coefficient_variation": cv,
        "skewness": skew,
        "growth_mean": growth_mean,
        "growth_std": growth_std,
    }
