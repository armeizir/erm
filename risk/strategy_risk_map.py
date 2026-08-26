from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.shortcuts import render

from .models import RKMItem, RKMSummary


MONTH_NAMES = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
}

MONTH_FIELDS = {
    1: "realisasi_januari",
    2: "realisasi_februari",
    3: "realisasi_maret",
    4: "realisasi_april",
    5: "realisasi_mei",
    6: "realisasi_juni",
    7: "realisasi_juli",
    8: "realisasi_agustus",
    9: "realisasi_september",
    10: "realisasi_oktober",
    11: "realisasi_november",
    12: "realisasi_desember",
}


def _decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", ".").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _status(capaian):
    value = _decimal(capaian)
    if value is None:
        return {
            "key": "nodata",
            "label": "Belum Dinilai",
            "severity": 0,
        }
    if value >= Decimal("100"):
        return {
            "key": "green",
            "label": "Tercapai",
            "severity": 1,
        }
    if value >= Decimal("95"):
        return {
            "key": "amber",
            "label": "Perlu Perhatian",
            "severity": 2,
        }
    return {
        "key": "red",
        "label": "Tidak Tercapai",
        "severity": 3,
    }


def _periods():
    values = (
        RKMSummary.objects
        .values_list("tahun", "bulan")
        .distinct()
        .order_by("-tahun", "-bulan")
    )
    return [
        {
            "year": int(year),
            "month": int(month),
            "label": f"{MONTH_NAMES.get(int(month), month)} {year}",
        }
        for year, month in values
        if year and month
    ]


def _selected_period(request, periods):
    if not periods:
        return None, None

    try:
        year = int(request.GET.get("year", periods[0]["year"]))
        month = int(request.GET.get("month", periods[0]["month"]))
    except (TypeError, ValueError):
        year, month = periods[0]["year"], periods[0]["month"]

    valid = {(x["year"], x["month"]) for x in periods}
    if (year, month) not in valid:
        year, month = periods[0]["year"], periods[0]["month"]
    return year, month


@login_required
def strategy_risk_map(request):
    periods = _periods()
    year, month = _selected_period(request, periods)

    rows = []
    counters = Counter()

    if year and month:
        summaries = list(
            RKMSummary.objects
            .filter(tahun=year, bulan=month)
            .select_related("unit_bisnis", "kontrak_manajemen")
            .order_by("unit_bisnis__name", "kontrak_manajemen__judul", "pk")
        )

        summary_ids = [s.pk for s in summaries]
        summary_map = {s.pk: s for s in summaries}

        items = (
            RKMItem.objects
            .filter(summary_id__in=summary_ids)
            .select_related("summary", "km_item")
            .order_by(
                "summary__unit_bisnis__name",
                "summary__kontrak_manajemen__judul",
                "no_item",
                "pk",
            )
        )

        realization_field = MONTH_FIELDS.get(month)

        for item in items:
            summary = summary_map[item.summary_id]
            status = _status(getattr(item, "persen_capaian", None))
            counters[status["key"]] += 1

            km_item = getattr(item, "km_item", None)
            target = (
                getattr(item, "kpi_target", None)
                or getattr(km_item, "target", None)
                or ""
            )

            realization = ""
            if realization_field:
                realization = getattr(item, realization_field, None)
            if realization in (None, ""):
                realization = getattr(item, "jumlah_realisasi", None)

            unit = getattr(summary, "unit_bisnis", None)
            km = getattr(summary, "kontrak_manajemen", None)

            rows.append({
                "id": item.pk,
                "summary_id": summary.pk,
                "unit": getattr(unit, "name", "") or "-",
                "km": getattr(km, "judul", "") or "-",
                "no_item": getattr(item, "no_item", None),
                "kpi": (
                    getattr(item, "kpi_indikator", None)
                    or getattr(km_item, "indikator_kinerja_kunci", None)
                    or "-"
                ),
                "target": target,
                "unit_measure": getattr(item, "kpi_satuan", None) or "",
                "realization": realization if realization not in (None, "") else None,
                "achievement": getattr(item, "persen_capaian", None),
                "pic": getattr(item, "pic_rkm", None) or "-",
                "analysis": getattr(item, "hasil_analisa_program_kerja", None) or "",
                "status": status,
                "km_linked": km_item is not None,
            })

    unit_filter = (request.GET.get("unit") or "").strip()
    status_filter = (request.GET.get("status") or "").strip()

    available_units = sorted({r["unit"] for r in rows if r["unit"] != "-"})

    filtered_rows = rows
    if unit_filter:
        filtered_rows = [r for r in filtered_rows if r["unit"] == unit_filter]
    if status_filter in {"red", "amber", "green", "nodata"}:
        filtered_rows = [r for r in filtered_rows if r["status"]["key"] == status_filter]

    filtered_rows.sort(
        key=lambda r: (
            -r["status"]["severity"],
            r["unit"],
            r["no_item"] or 9999,
            r["kpi"],
        )
    )

    issue_rows = [
        r for r in filtered_rows
        if r["status"]["key"] in {"red", "amber"}
    ]

    total = len(rows)
    issue_count = counters["red"] + counters["amber"]

    modules = [
        {
            "key": "rkap",
            "title": "RKAP",
            "subtitle": "Sasaran & Target",
            "state": "linked",
            "note": "Sumber sasaran strategis",
        },
        {
            "key": "km",
            "title": "KM",
            "subtitle": "Kontrak Manajemen",
            "state": "linked",
            "note": "Target KPI",
        },
        {
            "key": "rkm",
            "title": "RKM",
            "subtitle": "Realisasi KPI",
            "state": "danger" if counters["red"] else ("warning" if counters["amber"] else "linked"),
            "note": f"{issue_count} KPI perlu perhatian",
        },
        {
            "key": "risk",
            "title": "Profil Risiko",
            "subtitle": "Re-Assessment",
            "state": "pending",
            "note": "Relasi KPI → Risiko disiapkan",
        },
        {
            "key": "icofr",
            "title": "iCOFR",
            "subtitle": "Control Effectiveness",
            "state": "pending",
            "note": "Relasi Risk → Control disiapkan",
        },
        {
            "key": "kpmr",
            "title": "KPMR",
            "subtitle": "ERM Health",
            "state": "linked",
            "note": "Monitoring kualitas ERM",
        },
    ]

    selected_period_label = (
        f"{MONTH_NAMES.get(month, month)} {year}"
        if year and month
        else "Belum ada RKM"
    )

    context = {
        "periods": periods,
        "selected_year": year,
        "selected_month": month,
        "selected_period_label": selected_period_label,
        "rows": filtered_rows,
        "issue_rows": issue_rows,
        "units": available_units,
        "unit_filter": unit_filter,
        "status_filter": status_filter,
        "modules": modules,
        "summary": {
            "total": total,
            "green": counters["green"],
            "amber": counters["amber"],
            "red": counters["red"],
            "nodata": counters["nodata"],
            "issues": issue_count,
        },
    }
    return render(request, "strategy_risk_map.html", context)
