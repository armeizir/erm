from __future__ import annotations

from decimal import Decimal

from .kpmr_aggregation import (
    _format_report_sum_details,
    _sum_detail_by_report,
)
from .kpmr_scoring import (
    _score_output_progress,
    _weighted_score,
    quantize_score,
)


def calculate_i2(*, report_items, reports, notes: list[str]):
    """Hitung indikator I2 tanpa mengubah kontrak output KPMR."""
    progress_values = [
        item.progress_pelaksanaan_percent
        for item in report_items
        if item.progress_pelaksanaan_percent is not None
    ]

    avg_progress = (
        sum(progress_values, Decimal("0")) / Decimal(len(progress_values))
        if progress_values
        else None
    )

    i2_raw, i2_note = _score_output_progress(avg_progress)
    i2_option = i2_note[:1] if i2_raw is not None else ""

    if i2_raw is None:
        notes.append(i2_note)
    else:
        progress_details, progress_total, progress_count = _sum_detail_by_report(
            reports,
            "progress_pelaksanaan_percent",
        )

        i2_note = (
            f"Rata-rata progress perlakuan risiko "
            f"{quantize_score(avg_progress)}% dari {len(progress_values)} item."
        )

        notes.append(
            "I2 Output perlakuan risiko:\n"
            "Sumber: III.B kolom Progress Pelaksanaan Rencana Perlakuan.\n"
            f"Rincian sumber: {_format_report_sum_details(progress_details)}.\n"
            f"Total progress: {quantize_score(progress_total)} = jumlah seluruh nilai progress dari {progress_count} item.\n"
            f"Rumus rata-rata: {quantize_score(progress_total)} / {progress_count} = {quantize_score(avg_progress)}%.\n"
            "Aturan jawaban: a=90-100%, b=80-89%, c=70-79%, d=60-69%, e=<60%.\n"
            f"Jawaban: {i2_option} -> Hasil Penilaian {i2_raw}.\n"
            f"Penilaian per parameter: {i2_raw} x bobot 20% = {_weighted_score(i2_raw, 20)}."
        )

    return i2_raw, i2_option, i2_note
