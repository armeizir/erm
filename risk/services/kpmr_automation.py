from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.models import Group

from .kpmr_aggregation import (
    _aggregate_budget_absorption,
    _aggregate_exposure_for_i1,
    _format_report_scope,
    _format_report_sum_details,
    _sum_detail_by_report,
)
from .kpmr_i1 import calculate_i1
from .kpmr_i2 import calculate_i2
from .kpmr_i3 import calculate_i3
from .kpmr_i4 import calculate_i4
from .kpmr_scoring import (
    INDICATOR_DEFINITIONS,
    SUBINDICATOR_DEFINITIONS,
    _fmt,
    _indicator,
    _score_budget_absorption,
    _score_output_progress,
    _weighted_score,
    actual_residual_score,
    int_or_none,
    month_to_quarter,
    quantize_score,
    quarter_months,
    rating_for_score,
    target_residual_score,
)
from .kpmr_types import KPMRCalculation

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


OFFICIAL_ANSWER_RAW_SCORES = {
    "I1": {"a": Decimal("90"), "b": Decimal("60"), "c": Decimal("40")},
    "I2": {
        "a": Decimal("100"), "b": Decimal("80"), "c": Decimal("70"),
        "d": Decimal("60"), "e": Decimal("40"),
    },
    "I3": {"a": Decimal("80"), "b": Decimal("40")},
}

OFFICIAL_I4_SUB_RAW_SCORES = {
    "a": Decimal("90"),
    "b": Decimal("50"),
}


def _normalized_official_answer(value):
    return str(value or "").strip().lower()


def _apply_official_assessment_precedence(
    *,
    year,
    quarter,
    unit,
    indicators,
    notes,
):
    # Jawaban resmi menjadi source of truth bila tersedia.
    official_indicators = {}
    for obj in (
        KPMRIndikatorResmi.objects.filter(
            periode__tahun=year,
            periode__triwulan=quarter,
            periode__unit_bisnis=unit,
        )
        .order_by("kode", "-pk")
    ):
        if obj.kode and obj.kode not in official_indicators:
            official_indicators[obj.kode] = obj

    applied = []

    for indicator in indicators:
        code = indicator.get("kode")
        official = official_indicators.get(code)

        if code in OFFICIAL_ANSWER_RAW_SCORES and official is not None:
            answer = _normalized_official_answer(official.jawaban)
            raw = OFFICIAL_ANSWER_RAW_SCORES[code].get(answer)
            if raw is not None:
                indicator["hasil"] = quantize_score(raw)
                indicator["skor"] = _weighted_score(
                    raw,
                    INDICATOR_DEFINITIONS[code]["bobot"],
                )
                indicator["jawaban"] = answer
                indicator["keterangan"] = (
                    f"Jawaban resmi KPMR digunakan sebagai source of truth: "
                    f"{code}={answer}. Perhitungan otomatis tetap menjadi fallback "
                    "bila asesmen resmi tidak tersedia."
                )
                applied.append(f"{code}={answer}")

        if code != "I4" or official is None:
            continue

        official_subs = {}
        for obj in (
            KPMRSubIndikatorResmi.objects.filter(indikator=official)
            .order_by("kode", "-pk")
        ):
            if obj.kode and obj.kode not in official_subs:
                official_subs[obj.kode] = obj

        changed = []
        for sub in indicator.get("subindikator") or []:
            sub_code = sub.get("kode")
            official_sub = official_subs.get(sub_code)
            if official_sub is None:
                continue

            answer = _normalized_official_answer(official_sub.jawaban)
            raw = OFFICIAL_I4_SUB_RAW_SCORES.get(answer)
            if raw is None:
                continue

            sub["hasil"] = quantize_score(raw)
            sub["skor"] = _weighted_score(raw, Decimal("25"))
            sub["jawaban"] = answer

            if sub_code == "RENCANA" and answer == "a":
                sub["keterangan"] = (
                    "Jawaban resmi KPMR digunakan sebagai source of truth: "
                    "I4.3/RENCANA=a. Untuk asesmen BIS TW II 2026, perubahan profil "
                    "masih diakomodasi sampai dengan Juni 2026. Periode berikutnya "
                    "mengikuti asesmen resmi baru atau perhitungan data aktual."
                )
            else:
                sub["keterangan"] = (
                    f"Jawaban resmi KPMR digunakan sebagai source of truth: "
                    f"{sub_code}={answer}."
                )
            changed.append((sub_code, raw, answer))

        if changed and len(changed) == len(indicator.get("subindikator") or []):
            i4_raw = sum((raw for _, raw, _ in changed), Decimal("0")) / Decimal(len(changed))
            indicator["hasil"] = quantize_score(i4_raw)
            indicator["skor"] = _weighted_score(
                i4_raw,
                INDICATOR_DEFINITIONS["I4"]["bobot"],
            )
            indicator["jawaban"] = ",".join(answer for _, _, answer in changed)
            indicator["keterangan"] = (
                "I4 mengikuti jawaban resmi KPMR pada empat subindikator. "
                f"Nilai rata-rata resmi = {quantize_score(i4_raw)}."
            )
            applied.append(
                "I4=" + ",".join(answer for _, _, answer in changed)
            )

    if applied:
        notes.append(
            "ASESMEN RESMI KPMR:\n"
            "Jawaban resmi memiliki precedence atas kalkulasi otomatis untuk "
            "unit/periode yang sama. Diterapkan: "
            + ", ".join(applied)
            + "."
        )

    return indicators


def calculate_kpmr_for_unit(
    year: int,
    quarter: int,
    unit: Group,
    *,
    month: int | None = None,
    report_ids: list[int] | None = None,
) -> KPMRCalculation:
    """Hitung KPMR dari satu snapshot bulanan.

    - ``month`` diisi: monitoring KPMR bulan tersebut.
    - ``month`` kosong: KPMR formal triwulan memakai bulan penutup triwulan
      (Maret/Juni/September/Desember), bukan rata-rata tiga bulan.
    - ``report_ids`` dipakai halaman Monthly Risk Report agar perhitungan persis
      menggunakan laporan yang sedang dibuka.
    """
    selected_month = month or quarter_months(quarter)[-1]
    report_qs = MonthlyRiskReport.objects.filter(
        reassessment__tahun=year,
        reassessment__unit_bisnis=unit,
    )
    if report_ids is not None:
        report_qs = report_qs.filter(id__in=report_ids)
    else:
        report_qs = report_qs.filter(periode__tanggal_mulai__month=selected_month)

    candidates = list(
        report_qs
        .select_related("periode", "reassessment", "reassessment__unit_bisnis")
        .prefetch_related("items__risk_event")
        .order_by("periode__tanggal_mulai", "reassessment_id", "-versi", "-id")
    )

    # Jika ada beberapa versi laporan pada bulan yang sama, gunakan versi terbaru
    # agar satu risiko tidak dihitung berulang. Pemanggilan dengan report_ids
    # sengaja memakai laporan yang dipilih secara eksplisit.
    if report_ids is None:
        reports = []
        seen_report_keys = set()
        for report in candidates:
            key = (report.reassessment_id, report.periode_id)
            if key in seen_report_keys:
                continue
            seen_report_keys.add(key)
            reports.append(report)
    else:
        reports = candidates

    report_ids = [report.id for report in reports]
    report_items = []
    for report in reports:
        report_items.extend(list(report.items.all()))

    # A formally imported KPMR working paper is the reviewed source of truth.
    # Show that assessment consistently on monthly monitoring pages instead of
    # replacing it with an inference from incomplete monthly detail fields.
    official_period = (
        KPMRPeriode.objects.filter(
            tahun=year,
            triwulan=quarter,
            unit_bisnis=unit,
            catatan__startswith="Diimpor dari",
        )
        .prefetch_related("indikator_resmi__subindikator")
        .first()
    )
    if official_period and official_period.indikator_resmi.count() == 4:
        return _calculation_from_saved_period(
            official_period,
            report_count=len(reports),
            item_count=len(report_items),
        )

    # An assessment recorded in the official KPMR working paper is an explicit
    # reviewer decision.  Honour the "all a" I4 decision instead of replacing
    # it with an inference from monthly residual values when recalculating the
    # monthly monitoring page.
    saved_i4 = (
        KPMRIndikatorResmi.objects.filter(
            periode__tahun=year,
            periode__triwulan=quarter,
            periode__unit_bisnis=unit,
            kode="I4",
        )
        .order_by("-pk")
        .first()
    )
    saved_i4_answers = [
        answer.strip().lower()
        for answer in ((saved_i4.jawaban or "") if saved_i4 else "").split(",")
        if answer.strip()
    ]
    force_i4_all_a = saved_i4_answers == ["a", "a", "a", "a"]

    month_label = (
        reports[0].periode.nama_periode
        if reports and reports[0].periode_id
        else f"Bulan {selected_month}"
    )
    if month is None:
        period_note = f"Snapshot KPMR TW{quarter}: posisi akhir {month_label}."
    else:
        period_note = f"KPMR bulanan: {month_label} {year}."
    notes = [
        period_note + " Perhitungan tidak merata-ratakan laporan bulan lain dalam triwulan."
    ]
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

    i1_raw, i1_option, i1_note, i1_detail = calculate_i1(
        report_items=report_items,
        quarter=quarter,
        unit=unit,
        year=year,
        reports=reports,
        comparable=comparable,
        above_target=above_target,
        same_target=same_target,
        below_target=below_target,
        notes=notes,
    )
    notes.append(f"I1 Pencapaian eksposur risiko:\n{i1_detail}")

    i2_raw, i2_option, i2_note = calculate_i2(
        report_items=report_items,
        reports=reports,
        notes=notes,
    )

    i3_raw, i3_option, i3_note = calculate_i3(
        report_items=report_items,
        item_count=item_count,
        notes=notes,
    )

    i4_raw, i4_note, sub_scores = calculate_i4(
        report_ids=report_ids,
        report_items=report_items,
        item_count=item_count,
        quarter=quarter,
        comparable=comparable,
        above_target=above_target,
        force_i4_all_a=force_i4_all_a,
        notes=notes,
    )

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

    # I4.jawaban harus selalu merefleksikan empat jawaban subindikator
    # dalam urutan resmi: IDENTIFIKASI, KUANTIFIKASI, RENCANA, PRIORITISASI.
    indicators[-1]["jawaban"] = ",".join(
        subindicator["jawaban"]
        for subindicator in indicators[-1]["subindikator"]
    )

    indicators = _apply_official_assessment_precedence(
        year=year,
        quarter=quarter,
        unit=unit,
        indicators=indicators,
        notes=notes,
    )

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
        month=selected_month,
    )


def calculate_kpmr_for_report(report: MonthlyRiskReport) -> KPMRCalculation:
    """Hitung KPMR bulanan persis dari Monthly Risk Report yang sedang dibuka."""
    if not report.periode_id or not report.reassessment_id or not report.reassessment.unit_bisnis_id:
        raise ValueError("Monthly Risk Report belum memiliki periode/reassessment/unit yang lengkap.")
    month = report.periode.tanggal_mulai.month
    quarter = month_to_quarter(month)
    return calculate_kpmr_for_unit(
        report.reassessment.tahun,
        quarter,
        report.reassessment.unit_bisnis,
        month=month,
        report_ids=[report.id],
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


def calculate_kpmr_for_month(year: int, month: int):
    """Hitung monitoring KPMR untuk setiap unit pada satu bulan."""
    quarter = month_to_quarter(month)
    unit_ids = (
        MonthlyRiskReport.objects.filter(
            reassessment__tahun=year,
            periode__tanggal_mulai__month=month,
        )
        .values_list("reassessment__unit_bisnis_id", flat=True)
        .distinct()
    )
    units = Group.objects.filter(id__in=unit_ids).order_by("name")
    return [
        calculate_kpmr_for_unit(year, quarter, unit, month=month)
        for unit in units
    ]


def calculate_kpmr_for_period(year: int, quarter: int):
    """Hitung KPMR formal triwulan dari snapshot bulan terakhir triwulan."""
    snapshot_month = quarter_months(quarter)[-1]
    unit_ids = (
        MonthlyRiskReport.objects.filter(
            reassessment__tahun=year,
            periode__tanggal_mulai__month=snapshot_month,
        )
        .values_list("reassessment__unit_bisnis_id", flat=True)
        .distinct()
    )
    units = Group.objects.filter(id__in=unit_ids).order_by("name")
    return [calculate_kpmr_for_unit(year, quarter, unit) for unit in units]


def kpmr_dashboard_rows(year: int | None, month: int | None):
    if not year:
        return []
    if month:
        calculations = calculate_kpmr_for_month(year, month)
    else:
        calculations = []
        for q in range(1, 5):
            calculations.extend(calculate_kpmr_for_period(year, q))
    return [
        {
            "unit": calculation.unit.name,
            "tahun": calculation.year,
            "triwulan": f"TW{calculation.quarter}",
            "bulan": calculation.month,
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
