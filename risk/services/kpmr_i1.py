from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal

from .kpmr_aggregation import _aggregate_exposure_for_i1, _format_report_scope
from .kpmr_owner import residual_owner_items
from .risk_exposure import formula_exposure_or_none
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

    value = formula_exposure_or_none(risk_event, quarter)
    return value, ("target exposure dihitung dari dampak Q × probabilitas Q / 100"
                   if value is not None else "komponen target belum lengkap/valid")


def _actual_exposure(item):
    value = formula_exposure_or_none(item)
    if value is not None:
        return value, "actual exposure dihitung dari dampak aktual × probabilitas aktual / 100"

    # Monthly report imports may carry an authoritative exposure value while
    # the impact component is unavailable.  Do not discard that value and make
    # I1 appear incomplete; it is the same stored III.A value shown to users.
    stored = _decimal(getattr(item, "realisasi_eksposur", None))
    if stored is not None and stored >= 0:
        return stored, "actual exposure memakai nilai tersimpan dari III.A"

    return None, "Data aktual belum lengkap/valid"


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
    Residual hanya dibaca dari baris utama III.A, sesuai pemilik formulir.
    Baris penyebab III.B tidak menjadi kandidat residual.
    """
    groups = OrderedDict()

    for item in residual_owner_items(report_items):
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
                "score baris utama III.A per top-risk; "
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

        reason += "; item utama=" + ",".join(str(item.pk) for item in items)

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


def _cumulative_ratio_i1(summary):
    """Equal-weight ratios; exact rational arithmetic determines a/b/c."""
    from fractions import Fraction
    if (summary["group_count"] <= 0
            or summary["complete_group_count"] != summary["group_count"]
            or summary["conflicts"]):
        return None, "", None, [], "Data top-risk belum lengkap/konflik."
    ratios = []
    for row in summary["groups"]:
        target, actual = row["target"], row["actual"]
        if target is None or actual is None or not target.is_finite() or not actual.is_finite():
            return None, "", None, [], "Target/realisasi tidak valid."
        if target < 0 or actual < 0:
            return None, "", None, [], "Target/realisasi negatif perlu verifikasi."
        if target == 0:
            if actual != 0:
                return None, "", None, [], f"Top-risk {row['group']}: target nol dan actual positif; rasio tidak terdefinisi."
            ratio = Fraction(1)  # zero exposure equals zero target
        else:
            ratio = Fraction(actual) / Fraction(target)
        ratios.append((row["group"], ratio))
    mean = sum((r for _, r in ratios), Fraction(0)) / len(ratios)
    option, raw = ("a", Decimal("90")) if mean < 1 else (("b", Decimal("60")) if mean == 1 else ("c", Decimal("40")))
    return raw, option, mean, ratios, ""


def _ratio_decimal_i1(ratio):
    return Decimal(ratio.numerator) / Decimal(ratio.denominator)


def calculate_i1(
    *, report_items, quarter: int, unit, year: int, reports, comparable,
    above_target: int, same_target: int, below_target: int, notes: list[str],
):
    """I1: rata-rata rasio actual/target seluruh top-risk, bobot sama."""
    hybrid = _aggregate_hybrid_i1(residual_owner_items(report_items), quarter)
    raw, option, mean, ratios, error = _cumulative_ratio_i1(hybrid)
    prefix = (
        "[METODE KUMULATIF RASIO - BOBOT SAMA PER TOP-RISK]\n"
        f"Unit: {unit.name}; Tahun: {year}; Triwulan: Q{quarter}.\n"
        f"Laporan: {_format_report_scope(reports)}.\n"
        "Setiap no_item dihitung satu kali dari baris utama III.A.\n"
        "Rasio = actual / target; kuantitatif memakai exposure, kualitatif memakai skor matriks.\n"
        "Rupiah tidak dijumlahkan dengan skor matriks. Semua risiko berbobot sama.\n"
        "Target=actual=0 diperlakukan sebagai rasio 1 (sama); target=0 dan actual>0 perlu verifikasi.\n"
        f"Top-risk: {hybrid['group_count']}; kuantitatif={hybrid['quantitative_count']}; "
        f"kualitatif={hybrid['qualitative_count']}.\n"
        "Aturan: rata-rata rasio < 1 => a/90; = 1 => b/60; > 1 => c/40.\n"
    )
    if raw is None:
        note = "I1 kumulatif belum dapat dinilai: " + error
        notes.append(note)
        reasons = [f"Top-risk {r['group']}: {r['reason']}" for r in hybrid['groups'] if not r['complete']]
        return None, "", note, prefix + note + "\n" + "\n".join(reasons + hybrid['conflicts'])
    ratio_map = dict(ratios)
    details = []
    for row in hybrid['groups']:
        symbol = '<' if row['comparison'] == 'below' else ('=' if row['comparison'] == 'same' else '>')
        details.append(
            f"Top-risk {row['group']}: {row['kind']} / {row['method']} "
            f"actual {_fmt(row['actual'])} {symbol} target {_fmt(row['target'])}; "
            f"rasio={_ratio_decimal_i1(ratio_map[row['group']]):.8f}; sumber: {row['reason']}"
        )
    mean_decimal = _ratio_decimal_i1(mean)
    note = f"Rata-rata rasio actual/target = {mean_decimal:.8f}; jawaban {option}."
    detail = prefix + (
        f"Jumlah rasio = {_ratio_decimal_i1(sum((r for _, r in ratios))):.8f}; "
        f"dibagi {len(ratios)} top-risk.\n"
        f"Rata-rata rasio = {mean_decimal:.8f} ({mean_decimal * 100:.6f}%).\n"
        "Keputusan memakai rasio presisi penuh, bukan angka tampilan yang dibulatkan.\n"
        f"Jawaban '{option}' -> Hasil {_fmt(raw)}; skor berbobot = {_weighted_score(raw, 30)}.\n\n"
        "[RINCIAN]\n" + "\n".join(details)
    )
    return raw, option, note, detail
