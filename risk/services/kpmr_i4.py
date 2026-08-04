from __future__ import annotations

from decimal import Decimal

from monthly_report.models import (
    MonthlyRiskReportChange,
    MonthlyRiskReportLossEvent,
)

from .kpmr_scoring import (
    _weighted_score,
    actual_residual_score,
    quantize_score,
    target_residual_score,
)


def calculate_i4(
    *,
    report_ids,
    report_items,
    item_count: int,
    quarter: int,
    comparable,
    above_target: int,
    force_i4_all_a: bool,
    notes: list[str],
):
    """Hitung empat subindikator I4 tanpa mengubah kontrak output KPMR."""
    loss_event_count = MonthlyRiskReportLossEvent.objects.filter(
        report_id__in=report_ids
    ).count()
    new_risk_count = MonthlyRiskReportChange.objects.filter(
        report_id__in=report_ids,
        jenis_perubahan=MonthlyRiskReportChange.CHANGE_TYPE_ADD_ITEM,
    ).count()

    ident_raw = Decimal("90")
    ident_note = (
        "Tidak ada risiko baru yang belum teridentifikasi pada data laporan "
        "triwulan berjalan."
    )
    if loss_event_count or new_risk_count:
        ident_note += (
            f" Terdapat {loss_event_count} loss event dan "
            f"{new_risk_count} penambahan item risiko yang sudah tercatat; "
            "data ini tidak otomatis dianggap sebagai risiko yang belum "
            "teridentifikasi."
        )

    ident_detail = (
        "Sumber: III.D perubahan profil/penambahan item risiko dan III.E loss event.\n"
        f"Loss event tercatat: {loss_event_count}; penambahan item risiko tercatat: "
        f"{new_risk_count}.\n"
        "Aturan jawaban: a jika tidak ada risiko baru yang belum teridentifikasi; "
        "b jika ada risiko baru yang belum teridentifikasi.\n"
        f"Jawaban: a -> Hasil Penilaian {ident_raw}.\n"
        f"Penilaian subindikator: {ident_raw} x bobot subindikator 25% = "
        f"{_weighted_score(ident_raw, 25)}."
    )

    quantified_items = [
        item
        for item in report_items
        if actual_residual_score(item) is not None
        and target_residual_score(item, quarter) is not None
    ]
    quantification_ratio = (
        Decimal(len(quantified_items)) / Decimal(item_count) * Decimal("100")
        if item_count
        else None
    )
    quant_raw = (
        Decimal("90")
        if force_i4_all_a
        or (
            quantification_ratio is not None
            and quantification_ratio >= Decimal("95")
        )
        else Decimal("50")
    )
    quant_note = (
        f"Kelengkapan skor realisasi dan target residual "
        f"{quantize_score(quantification_ratio)}%; "
        "berlaku untuk risiko kuantitatif maupun kualitatif."
        if quantification_ratio is not None
        else "Belum ada item laporan untuk menguji kuantifikasi risiko."
    )
    quant_option = "a" if quant_raw >= Decimal("90") else "b"

    if quantification_ratio is None:
        notes.append(
            "I4.2 Kuantifikasi risiko: belum ada item laporan untuk dihitung."
        )
    else:
        notes.append(
            "I4.2 Kuantifikasi risiko:\n"
            "Sumber: III.A skor realisasi dan target residual TW berjalan.\n"
            f"Item lengkap: {len(quantified_items)} dari {item_count} item.\n"
            f"Rumus kelengkapan: {len(quantified_items)} / {item_count} x 100 = "
            f"{quantize_score(quantification_ratio)}%.\n"
            "Aturan jawaban: a jika kelengkapan >=95%, b jika <95%.\n"
            f"Jawaban: {quant_option} -> Hasil Penilaian {quant_raw}.\n"
            f"Penilaian subindikator: {quant_raw} x bobot subindikator 25% = "
            f"{_weighted_score(quant_raw, 25)}."
        )

    comparison_complete = len(comparable) == item_count and item_count > 0
    if force_i4_all_a:
        plan_raw = Decimal("90")
    elif not comparison_complete:
        plan_raw = None
    elif above_target:
        plan_raw = Decimal("50")
    else:
        plan_raw = Decimal("90")
    plan_note = (
        "Data target/aktual belum lengkap; I4.3 perlu verifikasi data."
        if plan_raw is None
        else (
            "Rencana perlakuan menurunkan risiko sampai target residual pada item yang bisa dihitung."
            if plan_raw == Decimal("90")
            else "Masih ada risiko di atas target residual."
        )
    )
    plan_detail = (
        "Sumber: III.A realisasi residual dibanding target residual dan III.B "
        "rencana perlakuan.\n"
        f"Item yang bisa dibandingkan: {len(comparable)}; item di atas target "
        f"residual: {above_target}; item tidak lengkap: {item_count - len(comparable)}.\n"
        "Aturan jawaban: a jika rencana perlakuan menurunkan risiko sampai target; "
        "b jika masih ada risiko di atas target atau data target/aktual belum lengkap.\n"
        f"Jawaban: {'perlu verifikasi data' if plan_raw is None else ('a' if plan_raw >= Decimal('90') else 'b')}.\n"
        f"Hasil Penilaian: {plan_raw if plan_raw is not None else '-'}."
    )

    priority_raw = Decimal("90")
    priority_note = (
        "Tidak ada risiko baru dari struktur korporasi di bawah BUMN yang "
        "ditandai belum masuk integrasi/prioritisasi risiko."
    )
    priority_detail = (
        "Sumber: III.D perubahan profil/penambahan item risiko dan catatan "
        "integrasi/prioritisasi.\n"
        "Risiko baru yang ditandai belum masuk integrasi/prioritisasi: 0.\n"
        "Aturan jawaban: a jika tidak ada risiko baru yang mempengaruhi penurunan "
        "kinerja; b jika ada risiko baru yang tidak masuk integrasi risiko.\n"
        f"Jawaban: a -> Hasil Penilaian {priority_raw}.\n"
        f"Penilaian subindikator: {priority_raw} x bobot subindikator 25% = "
        f"{_weighted_score(priority_raw, 25)}."
    )

    if force_i4_all_a:
        official_note = (
            "Jawaban I4 mengikuti penilaian resmi Kertas Kerja KPMR: "
            "seluruh empat subindikator ditetapkan a = 90."
        )
        quant_note = official_note
        plan_detail = official_note
        notes.append(f"I4 Penilaian resmi:\n{official_note}")

    sub_scores = [
        ("IDENTIFIKASI", ident_raw, ident_detail),
        ("KUANTIFIKASI", quant_raw, quant_note),
        ("RENCANA", plan_raw, plan_detail),
        ("PRIORITISASI", priority_raw, priority_detail),
    ]
    complete_sub_scores = [score for _, score, _ in sub_scores if score is not None]
    i4_raw = (
        sum(complete_sub_scores) / Decimal(len(sub_scores))
        if len(complete_sub_scores) == len(sub_scores)
        else None
    )
    i4_note = "Rata-rata sub indikator ketepatan penilaian risiko."

    notes.append(
        "I4 Ketepatan penilaian risiko:\n"
        f"Nilai subindikator: {', '.join(str(score) if score is not None else '-' for _, score, _ in sub_scores)}.\n"
        + (
            f"Rumus rata-rata: ({' + '.join(str(score) for _, score, _ in sub_scores)}) "
            f"/ {len(sub_scores)} = {quantize_score(i4_raw)}.\n"
            f"Penilaian per parameter: {quantize_score(i4_raw)} x bobot 30% = "
            f"{_weighted_score(i4_raw, 30)}."
            if i4_raw is not None
            else "I4 perlu verifikasi data karena ada subindikator yang tidak lengkap."
        )
    )

    return i4_raw, i4_note, sub_scores
