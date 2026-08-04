from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


INDICATOR_DEFINITIONS = {
    "I1": {
        "nama": "Pencapaian Nilai Eksposur Risiko dibandingkan target Risiko Residual",
        "bobot": Decimal("30.00"),
    },
    "I2": {
        "nama": "Pencapaian output pelaksanaan perlakuan Risiko dibandingkan target total output",
        "bobot": Decimal("20.00"),
    },
    "I3": {
        "nama": "Realisasi biaya pelaksanaan perlakuan Risiko dibandingkan anggaran",
        "bobot": Decimal("20.00"),
    },
    "I4": {
        "nama": "Ketepatan penilaian Risiko",
        "bobot": Decimal("30.00"),
    },
}

SUBINDICATOR_DEFINITIONS = {
    "IDENTIFIKASI": "Ketepatan identifikasi Risiko",
    "KUANTIFIKASI": "Ketepatan kuantifikasi Risiko",
    "RENCANA": "Ketepatan rencana perlakuan Risiko",
    "PRIORITISASI": "Ketepatan prioritisasi Risiko",
}


def month_to_quarter(month: int | None) -> int | None:
    if not month:
        return None
    return ((month - 1) // 3) + 1


def quarter_months(quarter: int) -> list[int]:
    start = ((quarter - 1) * 3) + 1
    return [start, start + 1, start + 2]


def quantize_score(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fmt(value) -> str:
    if value is None:
        return "-"
    return str(quantize_score(value))


def int_or_none(value):
    if value in (None, ""):
        return None
    try:
        return int(Decimal(str(value).strip()))
    except Exception:
        return None


def risk_matrix_for_item(item):
    risk_event = getattr(item, "risk_event", None)
    summary = getattr(risk_event, "summary", None)
    if summary and summary.risk_matrix_id:
        return summary.risk_matrix
    return None


def _matrix_score(matrix, impact, likelihood):
    if not matrix or not impact or not likelihood:
        return None
    cell = matrix.get_cell(impact, likelihood)
    return cell.skor if cell else None


def target_residual_score(item, quarter: int):
    """Target score from target impact/likelihood on the profile matrix.

    ``target_residual_level`` is a legacy scalar whose domain is ambiguous and
    must not be compared with a matrix-cell score.
    """
    risk_event = getattr(item, "risk_event", None)
    if not risk_event:
        return None
    return _matrix_score(
        risk_matrix_for_item(item),
        getattr(risk_event, f"skala_dampak_q{quarter}", None),
        getattr(risk_event, f"skala_probabilitas_q{quarter}", None),
    )


def actual_residual_score(item):
    """Actual score from actual impact/likelihood on the same profile matrix."""
    return _matrix_score(
        risk_matrix_for_item(item),
        getattr(item, "realisasi_skala_dampak", None),
        getattr(item, "realisasi_skala_probabilitas", None),
    )


def rating_for_score(score: Decimal) -> str:
    if score > Decimal("90"):
        return "STRONG"
    if Decimal("85") <= score <= Decimal("90"):
        return "SATISFACTORY"
    if Decimal("80") <= score <= Decimal("84"):
        return "FAIR"
    if Decimal("75") <= score <= Decimal("79"):
        return "MARGINAL"
    return "UNSATISFACTORY"


def _score_output_progress(progress):
    if progress is None:
        return None, "Belum ada data progress pelaksanaan perlakuan risiko."
    progress = Decimal(progress)
    if progress >= Decimal("90"):
        return Decimal("100"), "a. Terealisasi 90-100%"
    if progress >= Decimal("80"):
        return Decimal("80"), "b. Terealisasi 80-89%"
    if progress >= Decimal("70"):
        return Decimal("60"), "c. Terealisasi 70-79%"
    if progress >= Decimal("60"):
        return Decimal("40"), "d. Terealisasi 60-69%"
    return Decimal("20"), "e. Terealisasi kurang dari 60%"


def _score_budget_absorption(absorption):
    if absorption is None:
        return None, "Belum ada data realisasi biaya/serapan biaya perlakuan risiko."
    absorption = Decimal(absorption)
    if absorption <= Decimal("100"):
        return Decimal("80"), "a. Realisasi biaya sama dengan atau lebih rendah dari anggaran"
    return Decimal("40"), "b. Realisasi biaya lebih tinggi dari anggaran"


def _weighted_score(raw_score, weight):
    if raw_score is None:
        return Decimal("0.00")
    return quantize_score(Decimal(raw_score) * Decimal(weight) / Decimal("100"))


def _indicator(code, raw_score, weight, option, note, reference="Laporan Risiko Bulanan"):
    return {
        "kode": code,
        "nama": INDICATOR_DEFINITIONS[code]["nama"],
        "bobot": Decimal(weight),
        "hasil": quantize_score(raw_score) if raw_score is not None else None,
        "skor": _weighted_score(raw_score, weight),
        "jawaban": option or "",
        "dokumen_referensi": reference,
        "keterangan": note,
    }
