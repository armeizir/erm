from __future__ import annotations

from decimal import Decimal

from .kpmr_scoring import (
    SUBINDICATOR_DEFINITIONS,
    _indicator,
    _weighted_score,
    quantize_score,
    rating_for_score,
)
from .kpmr_types import KPMRCalculation


def build_i4_subindicators(sub_scores):
    return [
        {
            "kode": code,
            "nama": SUBINDICATOR_DEFINITIONS[code],
            "bobot": Decimal("25.00"),
            "hasil": quantize_score(score) if score is not None else None,
            "skor": _weighted_score(score, 25),
            "jawaban": "" if score is None else ("a" if score >= Decimal("90") else "b"),
            "keterangan": note,
        }
        for code, score, note in sub_scores
    ]


def build_kpmr_indicators(
    *,
    i1_raw,
    i1_option,
    i1_note,
    i2_raw,
    i2_option,
    i2_note,
    i3_raw,
    i3_option,
    i3_note,
    i4_raw,
    i4_note,
    i4_sub_scores,
):
    indicators = [
        _indicator("I1", i1_raw, 30, i1_option, i1_note, "III.C / III.D Laporan Risiko Bulanan"),
        _indicator("I2", i2_raw, 20, i2_option, i2_note, "III.D Laporan Risiko Bulanan"),
        _indicator("I3", i3_raw, 20, i3_option, i3_note, "III.D Laporan Risiko Bulanan"),
        _indicator("I4", i4_raw, 30, "", i4_note, "III.A-E Laporan Risiko Bulanan"),
    ]
    indicators[-1]["subindikator"] = build_i4_subindicators(i4_sub_scores)

    # I4.jawaban harus selalu merefleksikan empat jawaban subindikator
    # dalam urutan resmi: IDENTIFIKASI, KUANTIFIKASI, RENCANA, PRIORITISASI.
    indicators[-1]["jawaban"] = ",".join(
        subindicator["jawaban"]
        for subindicator in indicators[-1]["subindikator"]
    )
    return indicators


def finalize_kpmr_result(
    *,
    year,
    quarter,
    unit,
    report_count,
    item_count,
    indicators,
    notes,
    month,
    diagnostics=None,
):
    assessed_indicators = [
        indicator for indicator in indicators if indicator["hasil"] is not None
    ]
    provisional_score = quantize_score(
        sum(indicator["skor"] for indicator in assessed_indicators)
    )
    assessed_weight = quantize_score(
        sum(indicator["bobot"] for indicator in assessed_indicators)
    )
    unassessed_weight = quantize_score(Decimal("100") - assessed_weight)
    is_complete = len(assessed_indicators) == len(indicators) and unassessed_weight == 0
    final_score = provisional_score if is_complete else None
    final_rating = rating_for_score(final_score) if final_score is not None else None
    normalized_indicative_score = (
        quantize_score(provisional_score / assessed_weight * Decimal("100"))
        if assessed_weight > 0 and not is_complete
        else None
    )
    return KPMRCalculation(
        year=year,
        quarter=quarter,
        unit=unit,
        report_count=report_count,
        item_count=item_count,
        score_total=provisional_score,
        rating=final_rating or "",
        indicators=indicators,
        notes=notes,
        month=month,
        data_status="valid" if is_complete else "perlu_verifikasi_data",
        diagnostics=diagnostics,
        is_complete=is_complete,
        requires_verification=not is_complete,
        assessed_weight=assessed_weight,
        unassessed_weight=unassessed_weight,
        provisional_score=provisional_score,
        final_score=final_score,
        final_rating=final_rating,
        normalized_indicative_score=normalized_indicative_score,
    )
