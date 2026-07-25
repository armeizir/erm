from __future__ import annotations

from decimal import Decimal

from .kpmr_aggregation import _aggregate_budget_absorption
from .kpmr_scoring import (
    _fmt,
    _weighted_score,
    quantize_score,
)


def calculate_i3(*, report_items, item_count: int, notes: list[str]):
    """Hitung indikator I3 tanpa mengubah kontrak output KPMR."""
    budget_summary = _aggregate_budget_absorption(report_items)

    if budget_summary is None:
        i3_raw = None
        i3_option = ""
        i3_note = (
            "Belum ada anggaran perlakuan risiko yang dapat "
            "dibandingkan dengan realisasi biaya."
        )
        notes.append(i3_note)

    else:
        total_budget = budget_summary["total_budget"]
        total_actual = budget_summary["total_actual"]
        aggregate_absorption = budget_summary["ratio"]
        unbudgeted_actual = budget_summary["unbudgeted_actual"]
        comparable_budget_count = budget_summary["comparable_count"]
        is_over_budget = budget_summary["is_over_budget"]

        i3_raw = Decimal("40") if is_over_budget else Decimal("80")
        i3_option = "b" if is_over_budget else "a"

        i3_note = (
            f"Total realisasi biaya {_fmt(total_actual)} "
            f"dibanding total anggaran {_fmt(total_budget)} "
            f"({quantize_score(aggregate_absorption)}%)."
        )

        notes.append(
            "I3 Realisasi biaya perlakuan risiko:\n"
            "Sumber anggaran: Profil Risiko - Biaya Perlakuan Risiko.\n"
            "Sumber realisasi: III.B - Realisasi Biaya Perlakuan Risiko pada snapshot bulan laporan.\n"
            f"Item dengan anggaran positif: {comparable_budget_count} dari {item_count} item.\n"
            f"Total anggaran: {_fmt(total_budget)}.\n"
            f"Total realisasi pada item beranggaran: {_fmt(total_actual)}.\n"
            f"Serapan agregat: {_fmt(total_actual)} / {_fmt(total_budget)} x 100 = "
            f"{quantize_score(aggregate_absorption)}%.\n"
            f"Realisasi pada item tanpa anggaran: {_fmt(unbudgeted_actual)}.\n"
            "Aturan jawaban: a jika total realisasi <= total anggaran dan tidak ada "
            "realisasi tanpa anggaran; b jika total realisasi > total anggaran atau "
            "terdapat realisasi tanpa anggaran.\n"
            f"Jawaban: {i3_option} -> Hasil Penilaian {i3_raw}.\n"
            f"Penilaian per parameter: {i3_raw} x bobot 20% = "
            f"{_weighted_score(i3_raw, 20)}."
        )

    return i3_raw, i3_option, i3_note
