from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal

from .kpmr_aggregation import _aggregate_exposure_for_i1, _format_report_scope
from .kpmr_scoring import (
    _fmt,
    _weighted_score,
    actual_residual_score,
    target_residual_score,
)


def _decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).strip())
    except Exception:
        return None


def _normalize_kind(value):
    text = str(value or "").strip().lower()
    if "kualitatif" in text:
        return "kualitatif"
    if "kuantitatif" in text:
        return "kuantitatif"
    return None


def _target_probability_fraction(value):
    value = _decimal(value)
    if value is None or value < 0:
        return None
    if value <= Decimal("1"):
        return value
    if value <= Decimal("100"):
        return value / Decimal("100")
    return None


def _actual_probability_fraction(value):
    value = _decimal(value)
    if value is None or value < 0 or value > Decimal("100"):
        return None
    return value / Decimal("100")


def _target_exposure(item, quarter):
    risk_event = getattr(item, "risk_event", None)
    if risk_event is None:
        return None, "target exposure tidak tersedia"

    explicit = _decimal(getattr(risk_event, f"eksposur_risiko_q{quarter}", None))
    if explicit is not None:
        return explicit, "target exposure tersimpan"

    impact = _decimal(getattr(risk_event, f"nilai_dampak_q{quarter}", None))
    probability = _target_probability_fraction(
        getattr(risk_event, f"nilai_probabilitas_q{quarter}", None)
    )
    if impact is None or probability is None:
        return None, "target exposure/komponen target belum lengkap"

    return impact * probability, "target exposure dihitung dari dampak × probabilitas"


def _actual_exposure(item):
    explicit = _decimal(getattr(item, "realisasi_eksposur", None))
    if explicit is not None:
        return explicit, "actual exposure tersimpan"

    impact = _decimal(getattr(item, "realisasi_nilai_dampak", None))
    probability = _actual_probability_fraction(
        getattr(item, "realisasi_nilai_probabilitas", None)
    )
    if impact is None or probability is None:
        return None, "actual exposure/komponen realisasi belum lengkap"

    return impact * probability, "actual exposure dihitung dari dampak × probabilitas"


def _group_key(item):
    risk_event = getattr(item, "risk_event", None)
    if risk_event is None:
        return None
    no_item = getattr(risk_event, "no_item", None)
    if no_item not in (None, ""):
        return no_item
    return getattr(risk_event, "pk", None) or getattr(risk_event, "id", None)


def _unique_decimal(values):
    unique = []
    for value in values:
        if value is None:
            continue
        if value not in unique:
            unique.append(value)
    return unique



def _hybrid_target_residual_score(item, quarter):
    """Resolve target qualitative score.

    Prioritas:
    1. score dari impact/likelihood pada risk matrix;
    2. fallback ke score residual target yang sudah tersimpan.
    """
    score = target_residual_score(item, quarter)
    if score is not None:
        return _decimal(score)

    risk_event = getattr(item, "risk_event", None)
    if not risk_event:
        return None

    return _decimal(
        getattr(risk_event, f"skala_risiko_q{quarter}", None)
    )


def _hybrid_actual_residual_score(item):
    """Resolve actual qualitative score.

    Prioritas:
    1. score dari actual impact/likelihood pada risk matrix;
    2. fallback ke score realisasi yang sudah tersimpan.
    """
    score = actual_residual_score(item)
    if score is not None:
        return _decimal(score)

    return _decimal(
        getattr(item, "realisasi_skor_risiko", None)
    )


def _aggregate_hybrid_i1(report_items, quarter):
    """Perbandingan I1 satu kali per top-risk/no_item.

    Kuantitatif: exposure vs target exposure.
    Kualitatif: matrix score vs target matrix score.
    Jika satu top-risk kualitatif punya beberapa cause, gunakan score maksimum
    (worst case) agar top-risk hanya dihitung satu kali.
    """
    groups = OrderedDict()

    for item in report_items:
        key = _group_key(item)
        if key is None:
            continue
        entry = groups.setdefault(
            key,
            {"group": key, "items": [], "explicit_kinds": set()},
        )
        entry["items"].append(item)
        kind = _normalize_kind(getattr(item, "jenis_risiko", None))
        if kind:
            entry["explicit_kinds"].add(kind)

    results = []
    conflicts = []

    for key, entry in groups.items():
        items = entry["items"]
        explicit_kinds = entry["explicit_kinds"]

        if len(explicit_kinds) > 1:
            reason = (
                "jenis_risiko berbeda dalam top-risk yang sama: "
                + ", ".join(sorted(explicit_kinds))
            )
            results.append({
                "group": key, "kind": "conflict", "method": "jenis risiko",
                "target": None, "actual": None, "comparison": None,
                "complete": False, "reason": reason,
            })
            conflicts.append(reason)
            continue

        inferred = False
        kind = next(iter(explicit_kinds), None)

        quant_pairs = []
        score_pairs = []
        for item in items:
            target_exp, _ = _target_exposure(item, quarter)
            actual_exp, _ = _actual_exposure(item)
            if target_exp is not None and actual_exp is not None:
                quant_pairs.append((target_exp, actual_exp))

            target_score = _hybrid_target_residual_score(item, quarter)
            actual_score = _hybrid_actual_residual_score(item)
            if target_score is not None and actual_score is not None:
                score_pairs.append((
                    Decimal(str(target_score)),
                    Decimal(str(actual_score)),
                ))

        if kind is None:
            inferred = True
            if quant_pairs:
                kind = "kuantitatif"
            elif score_pairs:
                kind = "kualitatif"

        if kind == "kuantitatif":
            target_values = []
            actual_values = []
            target_sources = set()
            actual_sources = set()

            for item in items:
                target, target_source = _target_exposure(item, quarter)
                actual, actual_source = _actual_exposure(item)
                if target is not None:
                    target_values.append(target)
                    target_sources.add(target_source)
                if actual is not None:
                    actual_values.append(actual)
                    actual_sources.add(actual_source)

            targets = _unique_decimal(target_values)
            actuals = _unique_decimal(actual_values)

            if len(targets) > 1 or len(actuals) > 1:
                reason = (
                    f"konflik exposure pada group {key}: "
                    f"target={targets}, actual={actuals}"
                )
                results.append({
                    "group": key, "kind": kind, "method": "exposure",
                    "target": None, "actual": None, "comparison": None,
                    "complete": False, "reason": reason,
                })
                conflicts.append(reason)
                continue

            target = targets[0] if targets else None
            actual = actuals[0] if actuals else None
            method = "exposure"
            reason = (
                f"{'; '.join(sorted(target_sources)) or 'target belum tersedia'}; "
                f"{'; '.join(sorted(actual_sources)) or 'actual belum tersedia'}"
            )

        elif kind == "kualitatif":
            target_scores = []
            actual_scores = []
            for item in items:
                target_score = _hybrid_target_residual_score(item, quarter)
                actual_score = _hybrid_actual_residual_score(item)
                if target_score is not None:
                    target_scores.append(Decimal(str(target_score)))
                if actual_score is not None:
                    actual_scores.append(Decimal(str(actual_score)))

            target = max(target_scores) if target_scores else None
            actual = max(actual_scores) if actual_scores else None
            method = "matrix-score"
            reason = (
                "score maksimum/worst-case per top-risk; "
                f"target candidates={_unique_decimal(target_scores)}, "
                f"actual candidates={_unique_decimal(actual_scores)}"
            )

        else:
            results.append({
                "group": key, "kind": "unknown", "method": "-",
                "target": None, "actual": None, "comparison": None,
                "complete": False,
                "reason": (
                    "jenis risiko tidak terisi dan tidak ada pasangan exposure "
                    "atau score residual-target yang lengkap"
                ),
            })
            continue

        complete = target is not None and actual is not None
        comparison = None
        if complete:
            if actual < target:
                comparison = "below"
            elif actual == target:
                comparison = "same"
            else:
                comparison = "above"

        if inferred:
            reason = "jenis diinferensikan; " + reason

        results.append({
            "group": key,
            "kind": kind,
            "method": method,
            "target": target,
            "actual": actual,
            "comparison": comparison,
            "complete": complete,
            "reason": reason,
        })

    complete = [x for x in results if x["complete"]]
    incomplete = [x for x in results if not x["complete"]]
    below = sum(x["comparison"] == "below" for x in complete)
    same = sum(x["comparison"] == "same" for x in complete)
    above = sum(x["comparison"] == "above" for x in complete)

    return {
        "groups": results,
        "group_count": len(results),
        "complete_group_count": len(complete),
        "incomplete_group_count": len(incomplete),
        "quantitative_count": sum(x["kind"] == "kuantitatif" for x in results),
        "qualitative_count": sum(x["kind"] == "kualitatif" for x in results),
        "unknown_count": sum(x["kind"] == "unknown" for x in results),
        "below_target": below,
        "same_target": same,
        "above_target": above,
        "achieved_count": below + same,
        "achievement_ratio": (
            Decimal(below + same) / Decimal(len(complete)) * Decimal("100")
            if complete else None
        ),
        "conflicts": conflicts,
    }


def _raw_from_group_comparison(summary):
    if (
        summary["group_count"] <= 0
        or summary["complete_group_count"] != summary["group_count"]
        or summary["conflicts"]
    ):
        return None, ""
    if summary["above_target"] > 0:
        return Decimal("40"), "c"
    if summary["same_target"] > 0:
        return Decimal("60"), "b"
    return Decimal("90"), "a"


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
    """KPMR I1 hybrid kuantitatif-kualitatif.

    Backward compatibility:
    - seluruh top-risk kuantitatif + exposure tersimpan lengkap:
      tetap gunakan agregasi TOTAL Exposure lama;
    - mixed/kualitatif: bandingkan per top-risk dengan satuan masing-masing.
    """
    hybrid = _aggregate_hybrid_i1(report_items, quarter)
    exposure_summary = _aggregate_exposure_for_i1(report_items, quarter)

    all_quantitative = (
        hybrid["group_count"] > 0
        and hybrid["quantitative_count"] == hybrid["group_count"]
    )
    exposure_ready = (
        all_quantitative
        and exposure_summary is not None
        and exposure_summary["group_count"] == hybrid["group_count"]
        and exposure_summary["comparable_group_count"] > 0
        and exposure_summary["incomplete_group_count"] == 0
        and not exposure_summary["conflicts"]
    )

    if exposure_ready:
        target = exposure_summary["total_target"]
        actual = exposure_summary["total_residual"]
        if actual < target:
            i1_raw, i1_option, comparison = Decimal("90"), "a", "lebih rendah dari"
        elif actual == target:
            i1_raw, i1_option, comparison = Decimal("60"), "b", "sama dengan"
        else:
            i1_raw, i1_option, comparison = Decimal("40"), "c", "lebih tinggi dari"

        i1_note = (
            f"Total Exposure Residual {_fmt(actual)} {comparison} "
            f"Total Exposure Target {_fmt(target)}."
        )
        i1_detail = (
            "[METODE KUANTITATIF - BACKWARD COMPATIBLE]\n"
            f"Unit: {unit.name}; Tahun: {year}; Triwulan: Q{quarter}.\n"
            f"Laporan: {_format_report_scope(reports)}.\n"
            "Seluruh top-risk kuantitatif dan exposure tersimpan lengkap; "
            "metode lama TOTAL Exposure tetap dipertahankan.\n"
            f"Top-risk: {hybrid['group_count']}.\n"
            f"Total Target Exposure = {_fmt(target)}.\n"
            f"Total Actual/Residual Exposure = {_fmt(actual)}.\n"
            f"Jawaban '{i1_option}' -> Hasil {_fmt(i1_raw)}; "
            f"skor berbobot = {_weighted_score(i1_raw, 30)}."
        )
        return i1_raw, i1_option, i1_note, i1_detail

    i1_raw, i1_option = _raw_from_group_comparison(hybrid)

    if i1_raw is None:
        incomplete = [
            f"{x['group']} ({x['kind']}): {x['reason']}"
            for x in hybrid["groups"] if not x["complete"]
        ]
        i1_note = (
            "I1 hybrid belum dapat dihitung karena belum semua top-risk "
            "memiliki pasangan target-aktual yang dapat dibandingkan."
        )
        i1_detail = (
            "[METODE HYBRID KUANTITATIF-KUALITATIF]\n"
            f"Unit: {unit.name}; Tahun: {year}; Triwulan: Q{quarter}.\n"
            f"Laporan: {_format_report_scope(reports)}.\n"
            "Kuantitatif: actual exposure dibanding target exposure.\n"
            "Kualitatif: actual matrix score dibanding target matrix score.\n"
            "Rupiah tidak dijumlahkan dengan matrix score.\n"
            "I1 hybrid belum dapat dihitung karena belum semua top-risk lengkap.\n"
            f"Top-risk lengkap: {hybrid['complete_group_count']} dari "
            f"{hybrid['group_count']}.\n"
            "Belum lengkap/konflik:\n- "
            + "\n- ".join(incomplete or ["tidak teridentifikasi"])
        )
        notes.append(i1_note)
        return None, "", i1_note, i1_detail

    if hybrid["above_target"] > 0:
        conclusion = "terdapat top-risk di atas target residual"
    elif hybrid["same_target"] > 0:
        conclusion = "tidak ada yang di atas target, tetapi ada yang sama dengan target"
    else:
        conclusion = "seluruh top-risk berada di bawah target residual"

    i1_note = (
        "Hybrid per top-risk: "
        f"{hybrid['below_target']} di bawah, "
        f"{hybrid['same_target']} sama, "
        f"{hybrid['above_target']} di atas target residual."
    )

    details = []
    for row in hybrid["groups"]:
        if row["complete"]:
            symbol = (
                "<" if row["comparison"] == "below"
                else "=" if row["comparison"] == "same"
                else ">"
            )
            details.append(
                f"Top-risk {row['group']}: {row['kind']} / {row['method']} "
                f"actual {_fmt(row['actual'])} {symbol} target {_fmt(row['target'])}"
            )

    i1_detail = (
        "[METODE HYBRID KUANTITATIF-KUALITATIF]\n"
        f"Unit: {unit.name}; Tahun: {year}; Triwulan: Q{quarter}.\n"
        f"Laporan: {_format_report_scope(reports)}.\n"
        "Kuantitatif: actual exposure dibanding target exposure. Jika exposure "
        "kosong tetapi nilai dampak dan probabilitas lengkap, exposure dihitung "
        "Dampak × Probabilitas.\n"
        "Kualitatif: actual matrix score dibanding target matrix score. Untuk "
        "top-risk dengan beberapa cause dipakai score maksimum/worst-case.\n"
        "Setiap no_item dihitung satu kali; rupiah tidak pernah dijumlahkan "
        "dengan matrix score.\n\n"
        f"Top-risk: {hybrid['group_count']}; kuantitatif="
        f"{hybrid['quantitative_count']}; kualitatif="
        f"{hybrid['qualitative_count']}.\n"
        f"Hasil: bawah={hybrid['below_target']}; sama={hybrid['same_target']}; "
        f"atas={hybrid['above_target']}.\n"
        f"Pencapaian actual <= target = {hybrid['achieved_count']} / "
        f"{hybrid['complete_group_count']} = {_fmt(hybrid['achievement_ratio'])}%.\n"
        "Policy hasil existing tetap dipakai: ada actual > target => c/40; "
        "jika tidak ada yang di atas tetapi ada actual = target => b/60; "
        "seluruh actual < target => a/90.\n"
        f"Kesimpulan: {conclusion}.\n"
        f"Jawaban '{i1_option}' -> Hasil {_fmt(i1_raw)}; "
        f"skor berbobot = {_weighted_score(i1_raw, 30)}.\n\n"
        "[RINCIAN]\n" + "\n".join(details)
    )

    return i1_raw, i1_option, i1_note, i1_detail
