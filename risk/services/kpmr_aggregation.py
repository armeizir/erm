from __future__ import annotations

from decimal import Decimal

from .kpmr_scoring import _fmt


def normalize_no_item(value):
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(int(Decimal(text)))
    except Exception:
        return text.casefold()


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

        group_key = normalize_no_item(getattr(risk_event, "no_item", None))
        if group_key in (None, ""):
            group_key = f"risk:{getattr(risk_event, 'pk', '')}"
        if group_key is None:
            continue

        entry = groups.setdefault(
            group_key,
            {
                "target": None,
                "residual": None,
                "risk_event_ids": set(),
                "missing": set(),
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
                entry["missing"].add(field_name)
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
        "groups": groups,
    }


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
