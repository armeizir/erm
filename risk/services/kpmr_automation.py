from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth.models import Group

from monthly_report.models import (
    MonthlyRiskReport,
    MonthlyRiskReportChange,
    MonthlyRiskReportLossEvent,
)
from risk.models import (
    KPMRIndikatorResmi,
    KPMRPeriode,
    KPMRSubIndikatorResmi,
)


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


@dataclass(frozen=True)
class KPMRCalculation:
    year: int
    quarter: int
    unit: Group
    report_count: int
    item_count: int
    score_total: Decimal
    rating: str
    indicators: list[dict]
    notes: list[str]


def month_to_quarter(month: int | None) -> int | None:
    if not month:
        return None
    return ((month - 1) // 3) + 1


def quarter_months(quarter: int) -> list[int]:
    start = ((quarter - 1) * 3) + 1
    return [start, start + 1, start + 2]


def quantize_score(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def int_or_none(value):
    if value in (None, ""):
        return None
    try:
        return int(Decimal(str(value).strip()))
    except Exception:
        return None


def target_residual_score(item, quarter: int):
    if item.target_residual_level is not None:
        return item.target_residual_level
    if item.risk_event_id:
        return int_or_none(getattr(item.risk_event, f"skala_risiko_q{quarter}", None))
    return None


def actual_residual_score(item):
    if item.realisasi_skor_risiko is not None:
        return item.realisasi_skor_risiko
    return item.residual_level


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


def _calculation_from_saved_period(period: KPMRPeriode, report_count: int, item_count: int):
    indicators = []
    for indicator in period.indikator_resmi.prefetch_related("subindikator").order_by("kode"):
        indicator_data = {
            "kode": indicator.kode,
            "nama": indicator.nama,
            "bobot": indicator.bobot,
            "hasil": indicator.hasil,
            "skor": indicator.skor,
            "jawaban": indicator.jawaban or "",
            "dokumen_referensi": indicator.dokumen_referensi or "",
            "keterangan": indicator.keterangan or "",
        }
        if indicator.kode == "I4":
            indicator_data["subindikator"] = [
                {
                    "kode": sub.kode,
                    "nama": sub.nama,
                    "bobot": sub.bobot,
                    "hasil": sub.hasil,
                    "skor": sub.skor,
                    "jawaban": sub.jawaban or "",
                    "keterangan": sub.keterangan or "",
                }
                for sub in indicator.subindikator.order_by("kode")
            ]
        indicators.append(indicator_data)
    return KPMRCalculation(
        year=period.tahun,
        quarter=period.triwulan,
        unit=period.unit_bisnis,
        report_count=report_count,
        item_count=item_count,
        score_total=period.skor_total,
        rating=period.rating or rating_for_score(period.skor_total),
        indicators=indicators,
        notes=[period.catatan] if period.catatan else [],
    )


def calculate_kpmr_for_unit(year: int, quarter: int, unit: Group) -> KPMRCalculation:
    reports = (
        MonthlyRiskReport.objects.filter(
            reassessment__tahun=year,
            reassessment__unit_bisnis=unit,
            periode__tanggal_mulai__month__in=quarter_months(quarter),
        )
        .select_related("periode", "reassessment", "reassessment__unit_bisnis")
        .order_by("periode__tanggal_mulai", "-versi")
    )
    report_ids = list(reports.values_list("id", flat=True))
    report_items = []
    for report in reports.prefetch_related("items__risk_event"):
        report_items.extend(list(report.items.all()))

    notes = []
    item_count = len(report_items)
    comparable = [
        item
        for item in report_items
        if target_residual_score(item, quarter) is not None
        and actual_residual_score(item) is not None
    ]
    above_target = 0
    same_target = 0
    below_target = 0
    for item in comparable:
        actual = actual_residual_score(item)
        target = target_residual_score(item, quarter)
        if actual > target:
            above_target += 1
        elif actual == target:
            same_target += 1
        else:
            below_target += 1

    if not comparable:
        i1_raw = None
        i1_option = ""
        i1_note = "Belum ada item dengan realisasi risiko dan target residual yang lengkap."
        notes.append(i1_note)
    elif above_target:
        i1_raw = Decimal("40")
        i1_option = "c"
        i1_note = (
            f"{above_target} risiko di atas target residual, {same_target} sama target, "
            f"{below_target} lebih rendah dari target."
        )
    elif same_target:
        i1_raw = Decimal("60")
        i1_option = "b"
        i1_note = f"{same_target} risiko sama dengan target residual, {below_target} lebih rendah dari target."
    else:
        i1_raw = Decimal("90")
        i1_option = "a"
        i1_note = f"Seluruh {below_target} risiko yang bisa dihitung berada di bawah target residual."

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
        i2_note = f"Rata-rata progress perlakuan risiko {quantize_score(avg_progress)}% dari {len(progress_values)} item."

    absorption_values = [
        item.persentase_serapan_biaya
        for item in report_items
        if item.persentase_serapan_biaya is not None
    ]
    avg_absorption = (
        sum(absorption_values, Decimal("0")) / Decimal(len(absorption_values))
        if absorption_values
        else None
    )
    i3_raw, i3_note = _score_budget_absorption(avg_absorption)
    i3_option = i3_note[:1] if i3_raw is not None else ""
    if i3_raw is None:
        notes.append(i3_note)
    else:
        i3_note = f"Rata-rata serapan biaya perlakuan risiko {quantize_score(avg_absorption)}% dari {len(absorption_values)} item."

    loss_event_count = MonthlyRiskReportLossEvent.objects.filter(report_id__in=report_ids).count()
    new_risk_count = MonthlyRiskReportChange.objects.filter(
        report_id__in=report_ids,
        jenis_perubahan=MonthlyRiskReportChange.CHANGE_TYPE_ADD_ITEM,
    ).count()
    ident_raw = Decimal("50") if loss_event_count or new_risk_count else Decimal("90")
    ident_note = (
        f"Terdapat {loss_event_count} loss event dan {new_risk_count} penambahan item risiko pada triwulan berjalan."
        if ident_raw == Decimal("50")
        else "Tidak ada risiko baru/loss event yang tercatat pada laporan triwulan berjalan."
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
    quant_raw = Decimal("90") if quantification_ratio is not None and quantification_ratio >= Decimal("95") else Decimal("50")
    quant_note = (
        f"Kelengkapan skor realisasi dan target residual {quantize_score(quantification_ratio)}%; "
        "berlaku untuk risiko kuantitatif maupun kualitatif."
        if quantification_ratio is not None
        else "Belum ada item laporan untuk menguji kuantifikasi risiko."
    )
    if quantification_ratio is not None and quantification_ratio < Decimal("95"):
        notes.append("Kuantifikasi realisasi belum lengkap pada seluruh item laporan.")

    plan_raw = Decimal("90") if comparable and not above_target else Decimal("50")
    plan_note = (
        "Rencana perlakuan menurunkan risiko sampai target residual pada item yang bisa dihitung."
        if plan_raw == Decimal("90")
        else "Masih ada risiko di atas target residual atau target residual belum lengkap."
    )

    priority_raw = Decimal("90") if not loss_event_count else Decimal("50")
    priority_note = (
        "Tidak ada loss event baru yang mengindikasikan prioritas risiko terlewat."
        if priority_raw == Decimal("90")
        else f"Terdapat {loss_event_count} loss event; perlu validasi prioritisasi risiko."
    )

    sub_scores = [
        ("IDENTIFIKASI", ident_raw, ident_note),
        ("KUANTIFIKASI", quant_raw, quant_note),
        ("RENCANA", plan_raw, plan_note),
        ("PRIORITISASI", priority_raw, priority_note),
    ]
    i4_raw = sum(score for _, score, _ in sub_scores) / Decimal(len(sub_scores))
    i4_note = "Rata-rata sub indikator ketepatan penilaian risiko."

    indicators = [
        _indicator("I1", i1_raw, 30, i1_option, i1_note, "III.C / III.D Laporan Risiko Bulanan"),
        _indicator("I2", i2_raw, 20, i2_option, i2_note, "III.D Laporan Risiko Bulanan"),
        _indicator("I3", i3_raw, 20, i3_option, i3_note, "III.D Laporan Risiko Bulanan"),
        _indicator("I4", i4_raw, 30, "", i4_note, "III.A-E Laporan Risiko Bulanan"),
    ]
    indicators[-1]["subindikator"] = [
        {
            "kode": code,
            "nama": SUBINDICATOR_DEFINITIONS[code],
            "bobot": Decimal("25.00"),
            "hasil": quantize_score(score),
            "skor": _weighted_score(score, 25),
            "jawaban": "a" if score >= Decimal("90") else "b",
            "keterangan": note,
        }
        for code, score, note in sub_scores
    ]

    score_total = quantize_score(sum(indicator["skor"] for indicator in indicators))
    return KPMRCalculation(
        year=year,
        quarter=quarter,
        unit=unit,
        report_count=len(report_ids),
        item_count=item_count,
        score_total=score_total,
        rating=rating_for_score(score_total),
        indicators=indicators,
        notes=notes,
    )


def save_kpmr_calculation(calculation: KPMRCalculation) -> KPMRPeriode:
    periode, _ = KPMRPeriode.objects.update_or_create(
        tahun=calculation.year,
        triwulan=calculation.quarter,
        unit_bisnis=calculation.unit,
        defaults={
            "skor_total": calculation.score_total,
            "rating": calculation.rating,
            "catatan": "\n".join(calculation.notes),
        },
    )
    for indicator_data in calculation.indicators:
        indicator, _ = KPMRIndikatorResmi.objects.update_or_create(
            periode=periode,
            kode=indicator_data["kode"],
            defaults={
                "nama": indicator_data["nama"],
                "bobot": indicator_data["bobot"],
                "jawaban": indicator_data.get("jawaban", ""),
                "hasil": indicator_data["hasil"],
                "skor": indicator_data["skor"],
                "dokumen_referensi": indicator_data["dokumen_referensi"],
                "keterangan": indicator_data["keterangan"],
            },
        )
        if indicator_data["kode"] == "I4":
            for sub_data in indicator_data.get("subindikator", []):
                KPMRSubIndikatorResmi.objects.update_or_create(
                    indikator=indicator,
                    kode=sub_data["kode"],
                    defaults={
                        "nama": sub_data["nama"],
                        "bobot": sub_data["bobot"],
                        "jawaban": sub_data["jawaban"],
                        "hasil": sub_data["hasil"],
                        "skor": sub_data["skor"],
                        "keterangan": sub_data["keterangan"],
                    },
                )
    return periode


def calculate_kpmr_for_period(year: int, quarter: int):
    unit_ids = (
        MonthlyRiskReport.objects.filter(
            reassessment__tahun=year,
            periode__tanggal_mulai__month__in=quarter_months(quarter),
        )
        .values_list("reassessment__unit_bisnis_id", flat=True)
        .distinct()
    )
    units = Group.objects.filter(id__in=unit_ids).order_by("name")
    return [calculate_kpmr_for_unit(year, quarter, unit) for unit in units]


def kpmr_dashboard_rows(year: int | None, month: int | None):
    if not year:
        return []
    quarter = month_to_quarter(month) if month else None
    if quarter:
        calculations = calculate_kpmr_for_period(year, quarter)
    else:
        calculations = []
        for q in range(1, 5):
            calculations.extend(calculate_kpmr_for_period(year, q))
    return [
        {
            "unit": calculation.unit.name,
            "tahun": calculation.year,
            "triwulan": f"TW{calculation.quarter}",
            "report_count": calculation.report_count,
            "item_count": calculation.item_count,
            "skor_total": calculation.score_total,
            "rating": calculation.rating,
            "notes": calculation.notes,
            "indicators": calculation.indicators,
        }
        for calculation in calculations
    ]


def kpmr_dashboard_summary(rows):
    if not rows:
        return {
            "count": 0,
            "avg_score": Decimal("0.00"),
            "strong_or_satisfactory": 0,
            "needs_attention": 0,
        }
    avg_score = sum((row["skor_total"] for row in rows), Decimal("0")) / Decimal(len(rows))
    return {
        "count": len(rows),
        "avg_score": quantize_score(avg_score),
        "strong_or_satisfactory": len(
            [row for row in rows if row["rating"] in {"STRONG", "SATISFACTORY"}]
        ),
        "needs_attention": len(
            [row for row in rows if row["rating"] in {"FAIR", "MARGINAL", "UNSATISFACTORY"}]
        ),
    }
