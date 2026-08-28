# STRATEGY_RISK_RELATIONSHIP_V4
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from monthly_report.models import MonthlyRiskReport

from .models import (
    KPMRPeriode,
    ProfilRisikoKorporatItem,
    ProfilRisikoKorporatSummary,
    RKMSummary,
)


MONTH_LABELS = {
    1: "Januari", 2: "Februari", 3: "Maret", 4: "April",
    5: "Mei", 6: "Juni", 7: "Juli", 8: "Agustus",
    9: "September", 10: "Oktober", 11: "November", 12: "Desember",
}

FINAL_KPMR_STATUSES = {
    "approved", "final", "finalized", "disetujui", "selesai",
}


def _decimal(value):
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace("%", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _format_decimal(value, digits=2):
    value = _decimal(value)
    if value is None:
        return "-"
    quant = Decimal("1") if digits <= 0 else Decimal("1." + ("0" * digits))
    value = value.quantize(quant)
    if value == value.to_integral():
        return f"{value:.0f}"
    return f"{value:f}".rstrip("0").rstrip(".")


def _normalize_level(level):
    return " ".join(str(level or "").strip().casefold().replace("_", " ").split())


def _level_rank(level):
    text = _normalize_level(level)
    aliases = {
        "low": 1,
        "rendah": 1,
        "low to moderate": 2,
        "low-to-moderate": 2,
        "rendah ke sedang": 2,
        "moderate": 3,
        "sedang": 3,
        "moderate to high": 4,
        "moderate-to-high": 4,
        "sedang ke tinggi": 4,
        "high": 5,
        "tinggi": 5,
        "very high": 6,
        "sangat tinggi": 6,
    }
    if text in aliases:
        return aliases[text]
    if "very high" in text or "sangat tinggi" in text:
        return 6
    if "moderate" in text and "high" in text:
        return 4
    if "low" in text and "moderate" in text:
        return 2
    if text.endswith("high"):
        return 5
    if text.endswith("moderate"):
        return 3
    if text.endswith("low"):
        return 1
    return 0


def _risk_status_from_level(level):
    """
    Ringkasan eksekutif:
    Low / Low to Moderate -> Aman
    Moderate -> Perlu Perhatian
    Moderate to High / High -> Tidak Aman
    """
    rank = _level_rank(level)
    if rank == 0:
        return {"key": "nodata", "label": "Belum Ada Data", "level": level or "-", "severity": 0}
    if rank <= 2:
        return {"key": "green", "label": "Aman", "level": level, "severity": rank}
    if rank == 3:
        return {"key": "amber", "label": "Perlu Perhatian", "level": level, "severity": rank}
    return {"key": "red", "label": "Tidak Aman", "level": level, "severity": rank}


def _nko_status(value):
    value = _decimal(value)
    if value is None:
        return {"key": "nodata", "label": "Belum Ada Data"}
    if value >= Decimal("100"):
        return {"key": "green", "label": "Tercapai"}
    if value >= Decimal("95"):
        return {"key": "amber", "label": "Hampir Tercapai"}
    return {"key": "red", "label": "Perlu Peningkatan"}


def _period_options():
    pairs = set()

    for year, month in (
        MonthlyRiskReport.objects.exclude(periode__tanggal_mulai__isnull=True)
        .values_list("reassessment__tahun", "periode__tanggal_mulai__month")
        .distinct()
    ):
        if year and month:
            pairs.add((int(year), int(month)))

    for year, month in RKMSummary.objects.values_list("tahun", "bulan").distinct():
        if year and month:
            pairs.add((int(year), int(month)))

    if not pairs:
        latest_year = (
            ProfilRisikoKorporatSummary.objects.order_by("-tahun")
            .values_list("tahun", flat=True)
            .first()
        )
        if latest_year:
            return [{
                "year": int(latest_year),
                "month": None,
                "value": str(int(latest_year)),
                "label": str(int(latest_year)),
            }]

    return [
        {
            "year": year,
            "month": month,
            "value": f"{year}-{month:02d}",
            "label": f"{MONTH_LABELS.get(month, month)} {year}",
        }
        for year, month in sorted(pairs, reverse=True)
    ]


def _selected_period(request, periods):
    if not periods:
        return None, None, ""

    requested = str(request.GET.get("period") or "").strip()
    requested_year = request.GET.get("year") or request.GET.get("tahun")
    requested_month = request.GET.get("month") or request.GET.get("bulan")

    year = month = None
    if requested:
        parts = requested.split("-", 1)
        try:
            year = int(parts[0])
            month = int(parts[1]) if len(parts) > 1 else None
        except (TypeError, ValueError):
            year = month = None
    elif requested_year:
        try:
            year = int(requested_year)
            month = int(requested_month) if requested_month else None
        except (TypeError, ValueError):
            year = month = None

    allowed = {(p["year"], p["month"]) for p in periods}
    if (year, month) not in allowed:
        year, month = periods[0]["year"], periods[0]["month"]

    label = f"{MONTH_LABELS.get(month, month)} {year}" if month else str(year or "")
    return year, month, label


def _corporate_items(year):
    if not year:
        return ProfilRisikoKorporatItem.objects.none()

    return (
        ProfilRisikoKorporatItem.objects.filter(summary__tahun=year)
        .select_related(
            "summary",
            "matrix_cell_residual__level_risiko",
            "kategori_risiko",
        )
        .prefetch_related(
            "sumber_risiko__reassessment_item__summary__unit_bisnis",
            "sumber_risiko__reassessment_item__summary__kontrak_manajemen",
        )
        .order_by("summary__judul", "no_item", "no_risiko", "pk")
    )


def _base_relationships(corporate_items):
    relationships = []
    summary_ids = set()
    unit_map = {}

    for corporate in corporate_items:
        supports = {}
        for source in corporate.sumber_risiko.all():
            reassessment_item = getattr(source, "reassessment_item", None)
            if not reassessment_item or not reassessment_item.summary_id:
                continue

            summary = reassessment_item.summary
            unit = getattr(summary, "unit_bisnis", None)
            if unit is None:
                continue

            support = supports.setdefault(
                summary.pk,
                {
                    "summary": summary,
                    "unit_id": unit.pk,
                    "unit": str(unit),
                    "profile": summary.judul,
                    "risk_event_ids": set(),
                    "source_count": 0,
                },
            )
            support["risk_event_ids"].add(reassessment_item.pk)
            support["source_count"] += 1
            summary_ids.add(summary.pk)
            unit_map[unit.pk] = str(unit)

        corporate_level = corporate.get_level_name("residual")
        relationships.append(
            {
                "corporate": corporate,
                "risk_no": corporate.no_risiko or corporate.no_item or corporate.pk,
                "event": corporate.peristiwa_risiko or "Peristiwa risiko belum diisi",
                "summary": str(corporate.summary),
                "category": str(corporate.kategori_risiko) if corporate.kategori_risiko_id else "-",
                "corporate_level": corporate_level or "-",
                "corporate_status": _risk_status_from_level(corporate_level),
                "supports": list(supports.values()),
            }
        )

    units = [
        {"id": pk, "name": name}
        for pk, name in sorted(unit_map.items(), key=lambda item: item[1].casefold())
    ]
    return relationships, summary_ids, units


def _latest_reports(summary_ids, year, month):
    if not summary_ids or not year or not month:
        return {}

    reports = (
        MonthlyRiskReport.objects.filter(
            reassessment_id__in=summary_ids,
            periode__tanggal_mulai__year=year,
            periode__tanggal_mulai__month=month,
        )
        .select_related("periode", "reassessment")
        .prefetch_related("items")
        .order_by("reassessment_id", "-versi", "-pk")
    )
    latest = {}
    for report in reports:
        latest.setdefault(report.reassessment_id, report)
    return latest


def _worst_actual_for_support(report, risk_event_ids):
    if report is None:
        return None
    levels = []
    for item in report.items.all():
        if item.risk_event_id not in risk_event_ids:
            continue
        level = (
            getattr(item, "realisasi_level_risiko", None)
            or getattr(item, "realisasi_level_risiko_bumn", None)
            or getattr(item, "realisasi_level_risiko_kbumn", None)
        )
        if level:
            levels.append(level)
    if not levels:
        return None
    return max(levels, key=_level_rank)


def _kpmr_by_unit(year, month, unit_ids):
    if not year or not month or not unit_ids:
        return {}

    quarter = ((int(month) - 1) // 3) + 1
    rows = (
        KPMRPeriode.objects.filter(
            tahun=year,
            triwulan=quarter,
            unit_bisnis_id__in=unit_ids,
        )
        .order_by("unit_bisnis_id", "-pk")
    )

    grouped = defaultdict(list)
    for row in rows:
        grouped[row.unit_bisnis_id].append(row)

    result = {}
    for unit_id, candidates in grouped.items():
        chosen = sorted(
            candidates,
            key=lambda row: (
                1 if str(getattr(row, "status", "") or "").strip().casefold() in FINAL_KPMR_STATUSES else 0,
                row.pk,
            ),
            reverse=True,
        )[0]

        status = str(getattr(chosen, "status", "") or "").strip()
        note = str(getattr(chosen, "catatan", "") or "")
        result[unit_id] = {
            "score": chosen.skor_total,
            "score_display": _format_decimal(chosen.skor_total),
            "rating": chosen.rating or "-",
            "record_status": status or "-",
            "is_provisional": "provisional" in note.casefold() or status.casefold() == "draft",
            "quarter": quarter,
        }

    return result


def _nko_for_summary(summary, year, month, cache):
    if not month or not getattr(summary, "kontrak_manajemen_id", None):
        return {
            "value": None,
            "display": "-",
            "status": _nko_status(None),
            "rkm_status": "-",
        }

    key = (summary.kontrak_manajemen_id, year, month)
    if key in cache:
        return cache[key]

    rkm = (
        RKMSummary.objects.filter(
            kontrak_manajemen_id=summary.kontrak_manajemen_id,
            tahun=year,
            bulan=month,
        )
        .order_by("-pk")
        .first()
    )
    if rkm is None:
        result = {
            "value": None,
            "display": "-",
            "status": _nko_status(None),
            "rkm_status": "-",
        }
        cache[key] = result
        return result

    # Pakai engine KM/NKO existing agar formula tidak diduplikasi.
    from .views import _kontrak_manajemen_detail

    detail = _kontrak_manajemen_detail(summary.kontrak_manajemen, year, month)
    value = _decimal(detail.get("total_nilai"))
    result = {
        "value": value,
        "display": f"{_format_decimal(value)}%" if value is not None else "-",
        "status": _nko_status(value),
        "rkm_status": rkm.status or "-",
    }
    cache[key] = result
    return result


def _enrich_relationships(relationships, reports, kpmr_map, year, month):
    nko_cache = {}
    for relation in relationships:
        enriched = []
        for support in relation["supports"]:
            summary = support["summary"]
            report = reports.get(summary.pk)
            actual_level = _worst_actual_for_support(report, support["risk_event_ids"])
            risk_status = _risk_status_from_level(actual_level)

            enriched.append(
                {
                    **support,
                    "report": report,
                    "report_code": report.kode if report else "-",
                    "actual_level": actual_level or "-",
                    "risk_status": risk_status,
                    "kpmr": kpmr_map.get(
                        support["unit_id"],
                        {
                            "score": None,
                            "score_display": "-",
                            "rating": "-",
                            "record_status": "-",
                            "is_provisional": False,
                            "quarter": ((month - 1) // 3 + 1) if month else None,
                        },
                    ),
                    "nko": _nko_for_summary(summary, year, month, nko_cache),
                }
            )

        relation["supports"] = sorted(
            enriched,
            key=lambda row: (row["unit"].casefold(), row["profile"].casefold()),
        )
    return relationships


def _filter_relationships(relationships, selected_unit_id):
    if not selected_unit_id:
        return relationships

    filtered = []
    for relation in relationships:
        supports = [
            row for row in relation["supports"]
            if str(row["unit_id"]) == str(selected_unit_id)
        ]
        if supports:
            filtered.append({**relation, "supports": supports})
    return filtered


def _summary_cards(relationships):
    support_rows = [
        support
        for relation in relationships
        for support in relation["supports"]
    ]
    unique_units = {row["unit_id"] for row in support_rows}
    return {
        "corporate": len(relationships),
        "units": len(unique_units),
        "green": sum(1 for row in support_rows if row["risk_status"]["key"] == "green"),
        "attention": sum(
            1 for row in support_rows
            if row["risk_status"]["key"] in {"amber", "red"}
        ),
        "nodata": sum(1 for row in support_rows if row["risk_status"]["key"] == "nodata"),
    }


@login_required
def strategy_risk_map(request):
    periods = _period_options()
    year, month, period_label = _selected_period(request, periods)

    relationships, summary_ids, units = _base_relationships(
        list(_corporate_items(year))
    )

    selected_unit = str(request.GET.get("unit") or "").strip()
    valid_unit_ids = {str(row["id"]) for row in units}
    if selected_unit not in valid_unit_ids:
        selected_unit = ""

    reports = _latest_reports(summary_ids, year, month)
    unit_ids = {
        support["unit_id"]
        for relation in relationships
        for support in relation["supports"]
    }
    kpmr_map = _kpmr_by_unit(year, month, unit_ids)

    relationships = _enrich_relationships(
        relationships, reports, kpmr_map, year, month
    )
    relationships = _filter_relationships(relationships, selected_unit)

    return render(
        request,
        "strategy_risk_map.html",
        {
            "page_title": "Executive Risk Relationship Map",
            "page_subtitle": (
                "Relasi Profil Risiko Korporat dengan Profil Risiko Bidang/Unit Bisnis, "
                "KPMR, dan KM (NKO)"
            ),
            "periods": periods,
            "selected_year": year,
            "selected_month": month,
            "selected_period": f"{year}-{month:02d}" if year and month else str(year or ""),
            "selected_period_label": period_label,
            "units": units,
            "selected_unit": selected_unit,
            "relationships": relationships,
            "summary": _summary_cards(relationships),
        },
    )
