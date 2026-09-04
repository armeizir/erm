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
    RKMItem,
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



def _support_risk_status(report, actual_level):
    """
    Status khusus relationship Risiko Unit.

    Bedakan:
    - laporan periode belum tersedia;
    - laporan tersedia tetapi penilaian risiko aktual belum diisi;
    - level aktual tersedia dan dapat diringkas.
    """
    if report is None:
        return {
            "key": "nodata",
            "label": "Belum Ada Laporan",
            "level": "-",
            "severity": 0,
        }

    if not actual_level:
        return {
            "key": "nodata",
            "label": "Penilaian Belum Diisi",
            "level": "-",
            "severity": 0,
        }

    return _risk_status_from_level(actual_level)



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
            "relasi_unit__unit_bisnis",
            "sumber_risiko__reassessment_item__summary__unit_bisnis",
            "sumber_risiko__reassessment_item__summary__kontrak_manajemen",
            "kinerja_terkait__item_kinerja__kontrak__unit_bisnis",
        )
        .order_by("summary__judul", "no_item", "no_risiko", "pk")
    )




MONTH_FIELD_SUFFIXES = {
    1: "januari",
    2: "februari",
    3: "maret",
    4: "april",
    5: "mei",
    6: "juni",
    7: "juli",
    8: "agustus",
    9: "september",
    10: "oktober",
    11: "november",
    12: "desember",
}


def _format_number_id(value, digits=2):
    """
    Format angka untuk tampilan Indonesia.
    4430.99 -> 4.430,99
    """
    value = _decimal(value)

    if value is None:
        return "-"

    formatted = f"{value:,.{digits}f}"
    return (
        formatted
        .replace(",", "__THOUSAND__")
        .replace(".", ",")
        .replace("__THOUSAND__", ".")
    )


def _display_kpi_value(value):
    if value in (None, ""):
        return "-"

    numeric = _decimal(value)

    if numeric is not None:
        return _format_number_id(numeric)

    return str(value).strip() or "-"


def _kpi_performance_status(percentage, is_deduction=False):
    if is_deduction:
        return {
            "key": "neutral",
            "label": "Nilai Pengurang",
        }

    percentage = _decimal(percentage)

    if percentage is None:
        return {
            "key": "nodata",
            "label": "Belum Ada Data",
        }

    if percentage >= Decimal("100"):
        return {
            "key": "green",
            "label": "Tercapai",
        }

    if percentage >= Decimal("95"):
        return {
            "key": "amber",
            "label": "Hampir Tercapai",
        }

    return {
        "key": "red",
        "label": "Perlu Peningkatan",
    }


def _next_month_label(year, month):
    if month == 12:
        next_year = year + 1
        next_month = 1
    else:
        next_year = year
        next_month = month + 1

    return f"{MONTH_LABELS[next_month]} {next_year}"


def _corporate_kpi_performance_map(year, month):
    """
    Ambil RKM Korporat EXACT pada bulan yang dipilih.
    Tidak fallback ke periode sebelumnya.
    """
    if not year or not month:
        return {}

    suffix = MONTH_FIELD_SUFFIXES.get(month)

    if not suffix:
        return {}

    rkm = (
        RKMSummary.objects
        .filter(
            tahun=year,
            bulan=month,
            kontrak_manajemen__unit_bisnis__name__iexact="KORPORAT",
        )
        .select_related("kontrak_manajemen")
        .order_by("-pk")
        .first()
    )

    if not rkm:
        return {}

    target_field = f"target_{suffix}"
    realisasi_field = f"realisasi_{suffix}"

    result = {}

    rows = (
        RKMItem.objects
        .filter(summary=rkm)
        .select_related("km_item")
        .order_by("km_item__no_urut", "pk")
    )

    for row in rows:
        km_item = row.km_item

        if not km_item:
            continue

        target_raw = getattr(row, target_field, None)

        # Compliance / deduction bisa tidak mempunyai target bulanan
        # numerik; gunakan KPI target resmi sebagai fallback.
        if target_raw in (None, ""):
            target_raw = row.kpi_target

        realisasi_raw = getattr(
            row,
            realisasi_field,
            None,
        )

        if realisasi_raw in (None, ""):
            realisasi_raw = row.realisasi

        unit = (
            row.kpi_satuan
            or row.target_akumulasi_satuan
            or getattr(km_item, "satuan", "")
            or ""
        )

        is_deduction = (
            str(unit).strip().casefold() == "nilai pengurang"
            or km_item.no_urut == 10
        )

        status = _kpi_performance_status(
            row.persen_capaian,
            is_deduction=is_deduction,
        )

        if is_deduction:
            achievement_label = "Nilai Pengurang"
            achievement_display = _display_kpi_value(
                realisasi_raw
            )
        else:
            achievement_label = "Capaian"
            achievement_display = (
                f"{_format_number_id(row.persen_capaian)}%"
                if row.persen_capaian is not None
                else "-"
            )

        result[km_item.pk] = {
            "available": True,
            "rkm_id": rkm.pk,
            "rkm_status": rkm.status or "-",
            "month_label": (
                f"{MONTH_LABELS.get(month, month)} {year}"
            ),
            "target": target_raw,
            "target_display": _display_kpi_value(target_raw),
            "realisasi": realisasi_raw,
            "realisasi_display": _display_kpi_value(
                realisasi_raw
            ),
            "unit": unit,
            "percentage": row.persen_capaian,
            "achievement_label": achievement_label,
            "achievement_display": achievement_display,
            "status": status,
            "forecast_month_label": _next_month_label(
                year,
                month,
            ),
            "forecast_display": "Belum tersedia",
        }

    return result


def _enrich_kpi_rows(kpis, performance_map, year, month):
    result = []

    for kpi in kpis:
        performance = performance_map.get(kpi["id"])

        if performance is None:
            performance = {
                "available": False,
                "rkm_id": None,
                "rkm_status": "-",
                "month_label": (
                    f"{MONTH_LABELS.get(month, month)} {year}"
                ),
                "target_display": "-",
                "realisasi_display": "-",
                "unit": "",
                "percentage": None,
                "achievement_label": "Capaian",
                "achievement_display": "-",
                "status": {
                    "key": "nodata",
                    "label": "Belum Ada Data",
                },
                "forecast_month_label": _next_month_label(
                    year,
                    month,
                ),
                "forecast_display": "Belum tersedia",
            }

        result.append(
            {
                **kpi,
                "performance": performance,
            }
        )

    return result



def _linked_kpis(corporate):
    """
    Daftar IKK Korporat yang terkait dengan satu Risiko Korporat.

    Bila object belum memiliki relasi kinerja_terkait
    (misalnya fixture/test legacy), kembalikan list kosong.
    Hanya relationship; nilai NKO tetap berasal dari RKM.
    """
    rows = []
    seen = set()

    relation_manager = getattr(
        corporate,
        "kinerja_terkait",
        None,
    )

    if relation_manager is None:
        return rows

    relations = (
        relation_manager.all()
        if hasattr(relation_manager, "all")
        else relation_manager
    )

    for relation in relations:
        item = getattr(relation, "item_kinerja", None)

        if item is None:
            continue

        if item.pk in seen:
            continue

        seen.add(item.pk)

        rows.append(
            {
                "id": item.pk,
                "no": item.no_urut,
                "name": (
                    item.indikator_kinerja_kunci
                    or "IKK belum diisi"
                ),
                "esg": item.esg_kategori or "-",
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row["no"],
            str(row["name"]).casefold(),
        ),
    )




def _base_relationships(corporate_items):
    relationships = []
    summary_ids = set()
    unit_map = {}

    for corporate in corporate_items:
        # ----------------------------------------------------
        # EXISTING SOURCE / LINKED RISK RELATIONSHIP
        # Tetap dipertahankan untuk MRR/status aktual.
        # ----------------------------------------------------
        supports = {}

        for source in corporate.sumber_risiko.all():
            reassessment_item = getattr(
                source,
                "reassessment_item",
                None,
            )

            if (
                not reassessment_item
                or not reassessment_item.summary_id
            ):
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
                    "linked_risks": [],
                    "source_count": 0,
                },
            )

            if (
                reassessment_item.pk
                not in support["risk_event_ids"]
            ):
                support["risk_event_ids"].add(
                    reassessment_item.pk
                )

                support["linked_risks"].append(
                    {
                        "id": reassessment_item.pk,
                        "risk_no": (
                            reassessment_item.no_risiko
                            or reassessment_item.no_item
                            or reassessment_item.pk
                        ),
                        "event": (
                            reassessment_item.peristiwa_risiko
                            or "Peristiwa risiko belum diisi"
                        ),
                    }
                )

            support["source_count"] += 1

            summary_ids.add(summary.pk)
            unit_map[unit.pk] = str(unit)

        for support in supports.values():
            support["linked_risks"] = sorted(
                support["linked_risks"],
                key=lambda row: (
                    str(row["risk_no"]).casefold(),
                    str(row["event"]).casefold(),
                ),
            )

        # ----------------------------------------------------
        # OFFICIAL GOVERNANCE RELATIONSHIP
        # Ditentukan Admin.
        # ----------------------------------------------------
        risk_leaders = []
        official_supports = []

        official_manager = getattr(
            corporate,
            "relasi_unit",
            None,
        )

        official_rows = (
            list(official_manager.all())
            if official_manager is not None
            else []
        )

        for official in official_rows:
            unit = getattr(
                official,
                "unit_bisnis",
                None,
            )

            if unit is None:
                continue

            row = {
                "relationship_id": official.pk,
                "unit_id": unit.pk,
                "unit": str(unit),
                "order": official.urutan or 0,
            }

            # Unit resmi masuk pilihan filter.
            unit_map[unit.pk] = str(unit)

            if official.role == "leader":
                risk_leaders.append(row)

            elif official.role == "supporting":
                official_supports.append(row)

        risk_leaders = sorted(
            risk_leaders,
            key=lambda row: (
                row["order"],
                row["unit"].casefold(),
            ),
        )

        official_supports = sorted(
            official_supports,
            key=lambda row: (
                row["order"],
                row["unit"].casefold(),
            ),
        )

        corporate_level = corporate.get_level_name(
            "residual"
        )

        relationships.append(
            {
                "corporate": corporate,
                "risk_no": (
                    corporate.no_risiko
                    or corporate.no_item
                    or corporate.pk
                ),
                "event": (
                    corporate.peristiwa_risiko
                    or "Peristiwa risiko belum diisi"
                ),
                "summary": str(corporate.summary),
                "category": (
                    str(corporate.kategori_risiko)
                    if corporate.kategori_risiko_id
                    else "-"
                ),
                "corporate_level": corporate_level or "-",
                "corporate_status": (
                    _risk_status_from_level(
                        corporate_level
                    )
                ),
                "kpis": _linked_kpis(corporate),

                # Existing linked source/MRR.
                "supports": list(supports.values()),

                # Official admin configuration.
                "risk_leaders": risk_leaders,
                "official_supports": official_supports,
            }
        )

    units = [
        {
            "id": pk,
            "name": name,
        }
        for pk, name in sorted(
            unit_map.items(),
            key=lambda item: item[1].casefold(),
        )
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



def _enrich_relationships(
    relationships,
    reports,
    kpmr_map,
    year,
    month,
):
    nko_cache = {}

    kpi_performance_map = (
        _corporate_kpi_performance_map(
            year,
            month,
        )
    )

    for relation in relationships:
        relation["kpis"] = _enrich_kpi_rows(
            relation.get("kpis") or [],
            kpi_performance_map,
            year,
            month,
        )

        # ----------------------------------------------------
        # Existing linked risk/MRR enrichment.
        # ----------------------------------------------------
        enriched = []

        for support in relation["supports"]:
            summary = support["summary"]

            report = reports.get(summary.pk)

            actual_level = _worst_actual_for_support(
                report,
                support["risk_event_ids"],
            )

            risk_status = _support_risk_status(
                report,
                actual_level,
            )

            enriched.append(
                {
                    **support,
                    "report": report,
                    "report_code": (
                        report.kode
                        if report
                        else "-"
                    ),
                    "has_report": report is not None,
                    "has_actual_level": bool(
                        actual_level
                    ),
                    "actual_level": (
                        actual_level
                        or "-"
                    ),
                    "risk_status": risk_status,
                    "kpmr": kpmr_map.get(
                        support["unit_id"],
                        {
                            "score": None,
                            "score_display": "-",
                            "rating": "-",
                            "record_status": "-",
                            "is_provisional": False,
                            "quarter": (
                                ((month - 1) // 3 + 1)
                                if month
                                else None
                            ),
                        },
                    ),
                    "nko": _nko_for_summary(
                        summary,
                        year,
                        month,
                        nko_cache,
                    ),
                }
            )

        relation["supports"] = sorted(
            enriched,
            key=lambda row: (
                row["unit"].casefold(),
                row["profile"].casefold(),
            ),
        )

        # ----------------------------------------------------
        # Map Official Supporting -> existing linked source.
        #
        # Jika belum ada linked ReAssessmentItem/MRR:
        # tetap tampil sebagai official supporting,
        # status = Belum Dipetakan.
        # ----------------------------------------------------
        source_by_unit = {}

        for source_row in relation["supports"]:
            source_by_unit.setdefault(
                source_row["unit_id"],
                source_row,
            )

        official_enriched = []

        for official in relation.get(
            "official_supports",
            [],
        ):
            mapped = source_by_unit.get(
                official["unit_id"]
            )

            if mapped:
                official_enriched.append(
                    {
                        **official,
                        "is_mapped": True,
                        "profile": mapped["profile"],
                        "report": mapped["report"],
                        "report_code": mapped["report_code"],
                        "linked_risks": mapped["linked_risks"],
                        "actual_level": mapped["actual_level"],
                        "risk_status": mapped["risk_status"],
                    }
                )

            else:
                official_enriched.append(
                    {
                        **official,
                        "is_mapped": False,
                        "profile": "-",
                        "report": None,
                        "report_code": "-",
                        "linked_risks": [],
                        "actual_level": "-",
                        "risk_status": {
                            "key": "nodata",
                            "label": "Belum Dipetakan",
                        },
                    }
                )

        relation["official_supports"] = sorted(
            official_enriched,
            key=lambda row: (
                row["order"],
                row["unit"].casefold(),
            ),
        )

    return relationships


def _filter_relationships(
    relationships,
    selected_unit_id,
):
    if not selected_unit_id:
        return relationships

    filtered = []

    for relation in relationships:
        leader_match = any(
            str(row["unit_id"])
            == str(selected_unit_id)
            for row in relation.get(
                "risk_leaders",
                [],
            )
        )

        official_supports = [
            row
            for row in relation.get(
                "official_supports",
                [],
            )
            if str(row["unit_id"])
            == str(selected_unit_id)
        ]

        source_supports = [
            row
            for row in relation["supports"]
            if str(row["unit_id"])
            == str(selected_unit_id)
        ]

        # Jika unit adalah Risk Leader,
        # tampilkan seluruh relationship agar konteks
        # supporting-nya tetap terlihat.
        if leader_match:
            filtered.append(relation)
            continue

        if official_supports or source_supports:
            filtered.append(
                {
                    **relation,
                    "official_supports": (
                        official_supports
                    ),
                    "supports": source_supports,
                }
            )

    return filtered

def _unit_performance_summary(relationships):
    """
    Ringkasan per Bidang/Unit Bisnis untuk relationship map.

    Jumlah risiko = DISTINCT ReAssessmentItem yang terhubung
    dengan risiko korporat yang sedang tampil.

    KPMR = level unit.
    NKO  = KM dari profil risiko unit pada periode terpilih.
    """
    grouped = {}

    for relation in relationships:
        for support in relation["supports"]:
            unit_id = support["unit_id"]

            row = grouped.setdefault(
                unit_id,
                {
                    "unit_id": unit_id,
                    "unit": support["unit"],
                    "risk_event_ids": set(),
                    "kpmr": None,
                    "nko_by_contract": {},
                },
            )

            row["risk_event_ids"].update(
                support.get("risk_event_ids") or set()
            )

            # KPMR merupakan data level unit sehingga cukup satu
            # record terbaik dari enrichment existing.
            candidate_kpmr = support.get("kpmr") or {}
            current_kpmr = row["kpmr"]

            if (
                current_kpmr is None
                or (
                    current_kpmr.get("score") is None
                    and candidate_kpmr.get("score") is not None
                )
            ):
                row["kpmr"] = candidate_kpmr

            # Biasanya satu Unit/Bidang mempunyai satu KM canonical.
            # Jangan secara diam-diam memilih salah satu jika ternyata
            # terdapat lebih dari satu KM.
            summary = support.get("summary")
            contract_id = getattr(
                summary,
                "kontrak_manajemen_id",
                None,
            )
            candidate_nko = support.get("nko") or {}

            if contract_id and candidate_nko.get("value") is not None:
                row["nko_by_contract"][contract_id] = candidate_nko

    result = []

    for row in grouped.values():
        nko_candidates = list(
            row["nko_by_contract"].values()
        )

        if len(nko_candidates) == 1:
            nko = nko_candidates[0]
        elif len(nko_candidates) > 1:
            nko = {
                "value": None,
                "display": "Multi",
                "status": {
                    "key": "nodata",
                    "label": f"{len(nko_candidates)} KM",
                },
                "rkm_status": "-",
            }
        else:
            nko = {
                "value": None,
                "display": "-",
                "status": _nko_status(None),
                "rkm_status": "-",
            }

        kpmr = row["kpmr"] or {
            "score": None,
            "score_display": "-",
            "rating": "-",
            "record_status": "-",
            "is_provisional": False,
            "quarter": None,
        }

        result.append(
            {
                "unit_id": row["unit_id"],
                "unit": row["unit"],
                "risk_count": len(row["risk_event_ids"]),
                "kpmr": kpmr,
                "nko": nko,
            }
        )

    return sorted(
        result,
        key=lambda row: row["unit"].casefold(),
    )



def _summary_cards(relationships):
    support_rows = [
        support
        for relation in relationships
        for support in relation.get(
            "official_supports",
            [],
        )
    ]

    unique_units = {
        row["unit_id"]
        for row in support_rows
    }

    return {
        "corporate": len(relationships),
        "units": len(unique_units),
        "green": sum(
            1
            for row in support_rows
            if row["risk_status"]["key"] == "green"
        ),
        "attention": sum(
            1
            for row in support_rows
            if row["risk_status"]["key"]
            in {"amber", "red"}
        ),
        "nodata": sum(
            1
            for row in support_rows
            if row["risk_status"]["key"] == "nodata"
        ),
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
                "Relasi Profil Risiko Korporat dengan risiko pendukung "
                "Bidang/Unit Bisnis dan status risiko aktual."
            ),
            "periods": periods,
            "selected_year": year,
            "selected_month": month,
            "selected_period": f"{year}-{month:02d}" if year and month else str(year or ""),
            "selected_period_label": period_label,
            "units": units,
            "selected_unit": selected_unit,
            "relationships": relationships,
            "unit_performance_rows": _unit_performance_summary(relationships),
            "summary": _summary_cards(relationships),
        },
    )
