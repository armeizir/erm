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
    month: int | None = None


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


def _sum_detail_by_report(reports, attr: str) -> tuple[list, Decimal, int]:
    details = []
    total = Decimal("0")
    count = 0
    for report in reports:
        values = [
            getattr(item, attr)
            for item in report.items.all()
            if getattr(item, attr) is not None
        ]
        subtotal = sum(values, Decimal("0"))
        total += subtotal
        count += len(values)
        details.append((report.periode.nama_periode, subtotal, len(values)))
    return details, total, count


def _format_report_sum_details(details) -> str:
    if not details:
        return "-"
    return "; ".join(
        f"{name}: {_fmt(subtotal)} dari {count} item"
        for name, subtotal, count in details
    )


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



def _format_report_scope(reports):
    """Return a readable, stable label for reports included in a KPMR calculation."""
    if reports is None:
        return "-"

    try:
        report_list = list(reports)
    except TypeError:
        report_list = [reports]

    if not report_list:
        return "-"

    labels = []
    for report in report_list:
        report_id = getattr(report, "pk", None) or getattr(report, "id", None)
        label = str(report)
        if report_id is not None:
            labels.append(f"#{report_id} {label}")
        else:
            labels.append(label)

    return "; ".join(labels)


def _aggregate_exposure_for_i1(report_items, quarter):
    """Agregasi eksposur KPMR I1 per top-risk/no_item, bukan per treatment row.

    Satu top risk dapat mempunyai banyak penyebab/perlakuan. Nilai eksposur target
    dan residual harus dihitung satu kali per ``risk_event.no_item`` agar tidak
    terduplikasi oleh banyaknya treatment rows.
    """
    groups = {}
    conflicts = []

    for item in report_items:
        risk_event = getattr(item, "risk_event", None)
        if risk_event is None:
            continue

        group_key = getattr(risk_event, "no_item", None)
        if group_key in (None, ""):
            group_key = getattr(risk_event, "pk", None)
        if group_key is None:
            continue

        entry = groups.setdefault(
            group_key,
            {
                "target": None,
                "residual": None,
                "risk_event_ids": set(),
            },
        )
        risk_event_id = getattr(risk_event, "pk", None)
        if risk_event_id is not None:
            entry["risk_event_ids"].add(risk_event_id)

        raw_target = getattr(risk_event, f"eksposur_risiko_q{quarter}", None)
        raw_residual = getattr(item, "realisasi_eksposur", None)

        for field_name, raw_value in (
            ("target", raw_target),
            ("residual", raw_residual),
        ):
            if raw_value in (None, ""):
                continue
            value = Decimal(raw_value)
            current = entry[field_name]
            if current is None:
                entry[field_name] = value
            elif current != value:
                conflicts.append(
                    {
                        "group": group_key,
                        "field": field_name,
                        "first": current,
                        "other": value,
                    }
                )

    if not groups:
        return None

    complete = [
        entry
        for entry in groups.values()
        if entry["target"] is not None and entry["residual"] is not None
    ]
    incomplete_count = len(groups) - len(complete)

    total_target = sum((entry["target"] for entry in complete), Decimal("0"))
    total_residual = sum((entry["residual"] for entry in complete), Decimal("0"))

    return {
        "total_target": total_target,
        "total_residual": total_residual,
        "group_count": len(groups),
        "comparable_group_count": len(complete),
        "incomplete_group_count": incomplete_count,
        "conflicts": conflicts,
    }


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



def _aggregate_budget_absorption(report_items):
    """Hitung serapan biaya agregat termasuk perlakuan no-cost.

    - Anggaran positif: dihitung total actual / total budget.
    - Anggaran eksplisit 0 dan actual 0: valid sebagai no-cost, tidak over-budget.
    - Actual > 0 tanpa anggaran positif: over-budget/unbudgeted.
    - Semua budget None/kosong: dianggap belum ada data dan mengembalikan None.
    """
    total_budget = Decimal("0")
    total_actual = Decimal("0")
    unbudgeted_actual = Decimal("0")
    comparable_count = 0
    declared_budget_count = 0

    for item in report_items:
        risk_event = getattr(item, "risk_event", None)
        raw_budget = getattr(risk_event, "biaya_perlakuan_risiko", None)
        raw_actual = getattr(item, "realisasi_biaya_perlakuan", None)

        if raw_budget not in (None, ""):
            declared_budget_count += 1

        budget = Decimal(raw_budget) if raw_budget not in (None, "") else Decimal("0")
        actual = Decimal(raw_actual) if raw_actual not in (None, "") else Decimal("0")

        if budget > 0:
            total_budget += budget
            total_actual += actual
            comparable_count += 1
        elif actual > 0:
            unbudgeted_actual += actual

    if total_budget <= 0:
        if declared_budget_count <= 0:
            return None
        return {
            "total_budget": Decimal("0"),
            "total_actual": Decimal("0"),
            "ratio": Decimal("0"),
            "comparable_count": declared_budget_count,
            "declared_budget_count": declared_budget_count,
            "unbudgeted_actual": unbudgeted_actual,
            "is_over_budget": unbudgeted_actual > 0,
            "is_zero_cost": True,
        }

    ratio = total_actual / total_budget * Decimal("100")
    return {
        "total_budget": total_budget,
        "total_actual": total_actual,
        "ratio": ratio,
        "comparable_count": comparable_count,
        "declared_budget_count": declared_budget_count,
        "unbudgeted_actual": unbudgeted_actual,
        "is_over_budget": total_actual > total_budget or unbudgeted_actual > 0,
        "is_zero_cost": False,
    }

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
        # Fallback untuk unit yang belum memiliki data eksposur target/residual lengkap.
        if not comparable:
            i1_raw = None
            i1_option = ""
            i1_note = "Belum ada data eksposur lengkap maupun pasangan skor residual-target yang dapat dihitung."
            notes.append(i1_note)
        elif above_target:
            i1_raw = Decimal("40")
            i1_option = "c"
            i1_note = (
                f"Fallback skor: {above_target} risiko di atas target residual, "
                f"{same_target} sama target, {below_target} lebih rendah dari target."
            )
        elif same_target:
            i1_raw = Decimal("60")
            i1_option = "b"
            i1_note = (
                f"Fallback skor: {same_target} risiko sama dengan target residual, "
                f"{below_target} lebih rendah dari target."
            )
        else:
            i1_raw = Decimal("90")
            i1_option = "a"
            i1_note = f"Fallback skor: seluruh {below_target} risiko berada di bawah target residual."

        exposure_reason = "Data eksposur belum lengkap."
        if exposure_summary is not None:
            exposure_reason = (
                f"Group eksposur lengkap {exposure_summary['comparable_group_count']} dari "
                f"{exposure_summary['group_count']}; konflik={len(exposure_summary['conflicts'])}."
            )

        i1_detail = (
            "[FALLBACK]\n"
            f"{exposure_reason}\n"
            "ERM sementara memakai perbandingan skor residual-target per item.\n"
            f"Rincian skor: {below_target} di bawah; {same_target} sama; {above_target} di atas.\n"
            f"Jawaban fallback '{i1_option or '-'}' -> Hasil Penilaian {_fmt(i1_raw)}.\n"
            f"Skor berbobot = {_fmt(i1_raw)} x 30% = {_weighted_score(i1_raw, 30)}."
        )

    notes.append(f"I1 Pencapaian eksposur risiko:\n{i1_detail}")

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
        i2_note = f"Rata-rata progress perlakuan risiko {quantize_score(avg_progress)}% dari {len(progress_values)} item."
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

    budget_summary = _aggregate_budget_absorption(report_items)
    if budget_summary is None:
        i3_raw = None
        i3_option = ""
        i3_note = "Belum ada anggaran perlakuan risiko yang dapat dibandingkan dengan realisasi biaya."
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
            f"Total realisasi biaya {_fmt(total_actual)} dibanding total anggaran {_fmt(total_budget)} "
            f"({quantize_score(aggregate_absorption)}%)."
        )
        notes.append(
            "I3 Realisasi biaya perlakuan risiko:\n"
            "Sumber anggaran: Profil Risiko - Biaya Perlakuan Risiko.\n"
            "Sumber realisasi: III.B - Realisasi Biaya Perlakuan Risiko pada snapshot bulan laporan.\n"
            f"Item dengan anggaran positif: {comparable_budget_count} dari {item_count} item.\n"
            f"Total anggaran: {_fmt(total_budget)}.\n"
            f"Total realisasi pada item beranggaran: {_fmt(total_actual)}.\n"
            f"Serapan agregat: {_fmt(total_actual)} / {_fmt(total_budget)} x 100 = {quantize_score(aggregate_absorption)}%.\n"
            f"Realisasi pada item tanpa anggaran: {_fmt(unbudgeted_actual)}.\n"
            "Aturan jawaban: a jika total realisasi <= total anggaran dan tidak ada realisasi tanpa anggaran; "
            "b jika total realisasi > total anggaran atau terdapat realisasi tanpa anggaran.\n"
            f"Jawaban: {i3_option} -> Hasil Penilaian {i3_raw}.\n"
            f"Penilaian per parameter: {i3_raw} x bobot 20% = {_weighted_score(i3_raw, 20)}."
        )

    loss_event_count = MonthlyRiskReportLossEvent.objects.filter(report_id__in=report_ids).count()
    new_risk_count = MonthlyRiskReportChange.objects.filter(
        report_id__in=report_ids,
        jenis_perubahan=MonthlyRiskReportChange.CHANGE_TYPE_ADD_ITEM,
    ).count()
    ident_raw = Decimal("90")
    ident_note = "Tidak ada risiko baru yang belum teridentifikasi pada data laporan triwulan berjalan."
    if loss_event_count or new_risk_count:
        ident_note += (
            f" Terdapat {loss_event_count} loss event dan {new_risk_count} penambahan item risiko "
            "yang sudah tercatat; data ini tidak otomatis dianggap sebagai risiko yang belum teridentifikasi."
        )
    ident_detail = (
        "Sumber: III.D perubahan profil/penambahan item risiko dan III.E loss event.\n"
        f"Loss event tercatat: {loss_event_count}; penambahan item risiko tercatat: {new_risk_count}.\n"
        "Aturan jawaban: a jika tidak ada risiko baru yang belum teridentifikasi; b jika ada risiko baru yang belum teridentifikasi.\n"
        f"Jawaban: a -> Hasil Penilaian {ident_raw}.\n"
        f"Penilaian subindikator: {ident_raw} x bobot subindikator 25% = {_weighted_score(ident_raw, 25)}."
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
        or (quantification_ratio is not None and quantification_ratio >= Decimal("95"))
        else Decimal("50")
    )
    quant_note = (
        f"Kelengkapan skor realisasi dan target residual {quantize_score(quantification_ratio)}%; "
        "berlaku untuk risiko kuantitatif maupun kualitatif."
        if quantification_ratio is not None
        else "Belum ada item laporan untuk menguji kuantifikasi risiko."
    )
    quant_option = "a" if quant_raw >= Decimal("90") else "b"
    if quantification_ratio is None:
        notes.append("I4.2 Kuantifikasi risiko: belum ada item laporan untuk dihitung.")
    else:
        notes.append(
            "I4.2 Kuantifikasi risiko:\n"
            "Sumber: III.A skor realisasi dan target residual TW berjalan.\n"
            f"Item lengkap: {len(quantified_items)} dari {item_count} item.\n"
            f"Rumus kelengkapan: {len(quantified_items)} / {item_count} x 100 = {quantize_score(quantification_ratio)}%.\n"
            "Aturan jawaban: a jika kelengkapan >=95%, b jika <95%.\n"
            f"Jawaban: {quant_option} -> Hasil Penilaian {quant_raw}.\n"
            f"Penilaian subindikator: {quant_raw} x bobot subindikator 25% = {_weighted_score(quant_raw, 25)}."
        )

    plan_raw = (
        Decimal("90")
        if force_i4_all_a or (comparable and not above_target)
        else Decimal("50")
    )
    plan_note = (
        "Rencana perlakuan menurunkan risiko sampai target residual pada item yang bisa dihitung."
        if plan_raw == Decimal("90")
        else "Masih ada risiko di atas target residual atau target residual belum lengkap."
    )
    plan_detail = (
        "Sumber: III.A realisasi residual dibanding target residual dan III.B rencana perlakuan.\n"
        f"Item yang bisa dibandingkan: {len(comparable)}; item di atas target residual: {above_target}.\n"
        "Aturan jawaban: a jika rencana perlakuan menurunkan risiko sampai target; b jika masih ada risiko di atas target atau data target belum lengkap.\n"
        f"Jawaban: {'a' if plan_raw >= Decimal('90') else 'b'} -> Hasil Penilaian {plan_raw}.\n"
        f"Penilaian subindikator: {plan_raw} x bobot subindikator 25% = {_weighted_score(plan_raw, 25)}."
    )

    priority_raw = Decimal("90")
    priority_note = (
        "Tidak ada risiko baru dari struktur korporasi di bawah BUMN yang ditandai belum masuk "
        "integrasi/prioritisasi risiko."
    )
    priority_detail = (
        "Sumber: III.D perubahan profil/penambahan item risiko dan catatan integrasi/prioritisasi.\n"
        "Risiko baru yang ditandai belum masuk integrasi/prioritisasi: 0.\n"
        "Aturan jawaban: a jika tidak ada risiko baru yang mempengaruhi penurunan kinerja; b jika ada risiko baru yang tidak masuk integrasi risiko.\n"
        f"Jawaban: a -> Hasil Penilaian {priority_raw}.\n"
        f"Penilaian subindikator: {priority_raw} x bobot subindikator 25% = {_weighted_score(priority_raw, 25)}."
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
    i4_raw = sum(score for _, score, _ in sub_scores) / Decimal(len(sub_scores))
    i4_note = "Rata-rata sub indikator ketepatan penilaian risiko."
    notes.append(
        "I4 Ketepatan penilaian risiko:\n"
        f"Nilai subindikator: {', '.join(str(score) for _, score, _ in sub_scores)}.\n"
        f"Rumus rata-rata: ({' + '.join(str(score) for _, score, _ in sub_scores)}) / {len(sub_scores)} = {quantize_score(i4_raw)}.\n"
        f"Penilaian per parameter: {quantize_score(i4_raw)} x bobot 30% = {_weighted_score(i4_raw, 30)}."
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
