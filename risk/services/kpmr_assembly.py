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
    score_total = quantize_score(
        sum(indicator["skor"] for indicator in indicators)
    )
    return KPMRCalculation(
        year=year,
        quarter=quarter,
        unit=unit,
        report_count=report_count,
        item_count=item_count,
        score_total=score_total,
        rating=rating_for_score(score_total),
        indicators=indicators,
        notes=notes,
        month=month,
        data_status=(
            "perlu_verifikasi_data"
            if diagnostics and diagnostics.get("needs_verification")
            else "valid"
        ),
        diagnostics=diagnostics,
    )
