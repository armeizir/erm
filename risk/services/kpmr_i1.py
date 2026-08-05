from __future__ import annotations

from decimal import Decimal

from .kpmr_aggregation import _aggregate_exposure_for_i1, _format_report_scope
from .kpmr_scoring import _fmt, _weighted_score


def calculate_i1(
    *,
    report_items,
    quarter: int,
    unit,
    year: int,
    reports,
    comparable,
    above_target: int,
    same_target: int,
    below_target: int,
    notes: list[str],
):
    """Hitung indikator I1 tanpa mengubah kontrak output KPMR yang sudah berjalan.

    ``comparable`` dan jumlah above/same/below tetap dihitung oleh orchestrator
    karena konteks yang sama masih dipakai oleh perhitungan I4.
    """
    exposure_summary = _aggregate_exposure_for_i1(report_items, quarter)
    exposure_ready = (
        exposure_summary is not None
        and exposure_summary["comparable_group_count"] > 0
        and exposure_summary["incomplete_group_count"] == 0
        and not exposure_summary["conflicts"]
    )

    if exposure_ready:
        total_exposure_target = exposure_summary["total_target"]
        total_exposure_residual = exposure_summary["total_residual"]
        exposure_group_count = exposure_summary["comparable_group_count"]

        if total_exposure_residual < total_exposure_target:
            i1_raw = Decimal("90")
            i1_option = "a"
            comparison_text = "lebih rendah dari"
        elif total_exposure_residual == total_exposure_target:
            i1_raw = Decimal("60")
            i1_option = "b"
            comparison_text = "sama dengan"
        else:
            i1_raw = Decimal("40")
            i1_option = "c"
            comparison_text = "lebih tinggi dari"

        i1_note = (
            f"Total Exposure Residual {_fmt(total_exposure_residual)} {comparison_text} "
            f"Total Exposure Target {_fmt(total_exposure_target)}."
        )
        i1_detail = (
            "[SUMBER DATA]\n"
            f"Unit: {unit.name}; Tahun: {year}; Triwulan: Q{quarter}.\n"
            f"Laporan yang masuk perhitungan: {_format_report_scope(reports)}.\n"
            "Metode mengikuti Kertas Kerja KPMR user: membandingkan TOTAL Nilai Eksposur "
            "Risiko Residual dengan TOTAL Target Risiko Residual.\n\n"
            "[DATA YANG DIHITUNG]\n"
            f"Top-risk/group lengkap: {exposure_group_count}.\n"
            f"Total Exposure Target = {_fmt(total_exposure_target)}.\n"
            f"Total Exposure Residual = {_fmt(total_exposure_residual)}.\n\n"
            "[LOGIKA KPMR SESUAI ASESMEN USER]\n"
            "a = Total Exposure Residual < Total Exposure Target (nilai 90); "
            "b = sama (nilai 60); c = Total Exposure Residual > Total Exposure Target (nilai 40).\n"
            f"Jawaban '{i1_option}' -> Hasil Penilaian {i1_raw}.\n"
            f"Skor berbobot = {i1_raw} x 30% = {_weighted_score(i1_raw, 30)}.\n\n"
            "[CATATAN]\n"
            "Perhitungan dilakukan satu kali per top-risk/no_item, sehingga nilai eksposur "
            "tidak terduplikasi meskipun satu risiko memiliki beberapa penyebab/perlakuan."
        )
    else:
        # Tidak ada dasar konfigurasi bisnis yang mengizinkan substitusi nilai
        # eksposur dengan score matriks. Jangan menghasilkan jawaban a/b/c saat
        # data eksposur kelompok belum lengkap.
        i1_raw = None
        i1_option = ""
        i1_note = (
            "Data eksposur kelompok belum lengkap. Parameter I1 perlu verifikasi "
            "data dan fallback skor matriks tidak digunakan."
        )
        notes.append(i1_note)

        exposure_reason = "Data eksposur belum lengkap."
        if exposure_summary is not None:
            exposure_reason = (
                f"Group eksposur lengkap {exposure_summary['comparable_group_count']} dari "
                f"{exposure_summary['group_count']}; konflik={len(exposure_summary['conflicts'])}."
            )

        i1_detail = (
            "[DATA TIDAK LENGKAP — FALLBACK TIDAK DIGUNAKAN]\n"
            f"{exposure_reason}\n"
            "Perbandingan skor matriks per item hanya ditampilkan untuk diagnosis dan "
            "tidak menggantikan perbandingan total eksposur tanpa aturan bisnis eksplisit.\n"
            f"Rincian diagnostik skor: {below_target} di bawah; {same_target} sama; "
            f"{above_target} di atas; {len(report_items) - len(comparable)} tidak lengkap.\n"
            "Jawaban I1: perlu verifikasi data; skor I1 tidak diberikan."
        )

    return i1_raw, i1_option, i1_note, i1_detail
