from collections import defaultdict
from io import BytesIO
import json

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .models import (
    KPMRItem,
    KPMRSummary,
    ProfilRisikoKorporatItem,
    ProfilRisikoKorporatSummary,
    RiskMatrix,
)


LEVEL_FALLBACKS = [
    {"name": "Low", "codes": ["LOW"], "default_color": "#5b8f3a"},
    {"name": "Low to Moderate", "codes": ["LOW_TO_MODERATE", "LOW-MODERATE", "LTM"], "default_color": "#b8d4a2"},
    {"name": "Moderate", "codes": ["MODERATE", "MEDIUM"], "default_color": "#f3ef19"},
    {"name": "Moderate to High", "codes": ["MODERATE_TO_HIGH", "MODERATE-HIGH", "MTH"], "default_color": "#f2b01e"},
    {"name": "High", "codes": ["HIGH"], "default_color": "#d50f0f"},
]

MODE_CHOICES = [
    ("inheren", "Inheren"),
    ("residual", "Residual"),
]


def _normalize(text):
    return (text or "").strip().lower()


def _get_mode_label(mode):
    return dict(MODE_CHOICES).get(mode, "Inheren")


def _resolve_level_bucket(level_name):
    normalized = _normalize(level_name)
    for bucket in LEVEL_FALLBACKS:
        if _normalize(bucket["name"]) == normalized:
            return bucket["name"]
    if "high" in normalized and "moderate" in normalized:
        return "Moderate to High"
    if "high" in normalized:
        return "High"
    if "moderate" in normalized and "low" in normalized:
        return "Low to Moderate"
    if "moderate" in normalized:
        return "Moderate"
    if "low" in normalized:
        return "Low"
    return level_name or "Tidak Terkategori"


def _fallback_level_from_score(score):
    if score >= 15:
        return "High", "#d00000"  # merah
    elif score >= 12:
        return "Moderate to High", "#f4a300"  # orange
    elif score >= 8:
        return "Moderate", "#fff200"  # kuning
    elif score >= 5:
        return "Low to Moderate", "#a9c98f"  # hijau muda
    else:
        return "Low", "#5a8f3a"  # hijau tua
    

def _default_matrix():
    return RiskMatrix.objects.filter(is_default=True, aktif=True).prefetch_related(
        "cells__skala_dampak", "cells__skala_probabilitas", "cells__level_risiko"
    ).first() or RiskMatrix.objects.filter(aktif=True).prefetch_related(
        "cells__skala_dampak", "cells__skala_probabilitas", "cells__level_risiko"
    ).first()


def _matrix_lookup(matrix):
    lookup = {}
    dampak_labels = {}
    kemungkinan_labels = {}
    legend_map = {}

    if not matrix:
        return lookup, dampak_labels, kemungkinan_labels, legend_map

    for cell in matrix.cells.all():
        impact = getattr(cell.skala_dampak, "urutan", None)
        likelihood = getattr(cell.skala_probabilitas, "urutan", None)
        if impact is None or likelihood is None:
            continue
        level_name = cell.level_risiko.nama if cell.level_risiko_id else None
        color = cell.warna_hex or getattr(cell.level_risiko, "warna_hex", None)
        lookup[(impact, likelihood)] = {
            "score": cell.skor,
            "level": level_name,
            "color": color,
            "cell_id": cell.id,
        }
        dampak_labels[impact] = cell.skala_dampak.nama
        kemungkinan_labels[likelihood] = cell.skala_probabilitas.nama
        if level_name:
            legend_map.setdefault(_resolve_level_bucket(level_name), color or "#d9d9d9")

    return lookup, dampak_labels, kemungkinan_labels, legend_map


def _selected_risk_fields(mode):
    if mode == "residual":
        return "residual_dampak", "residual_kemungkinan", "residual_level_risiko", "matrix_cell_residual"
    return "dampak", "kemungkinan", "level_risiko", "matrix_cell_inheren"


def _build_risk_entry(item, mode, matrix_lookup):
    dampak_field, kemungkinan_field, level_field, cell_field = _selected_risk_fields(mode)
    impact = getattr(item, dampak_field)
    likelihood = getattr(item, kemungkinan_field)
    stored_score = getattr(item, level_field)
    stored_cell = getattr(item, cell_field, None)

    if impact is None or likelihood is None:
        return None

    score = stored_score
    level_name = None
    color = None
    matrix_source = "fallback"

    cell_meta = matrix_lookup.get((impact, likelihood))
    if cell_meta:
        score = cell_meta["score"]
        level_name = cell_meta["level"]
        color = cell_meta["color"]
        matrix_source = "default_matrix"
    elif stored_cell:
        level_name = getattr(getattr(stored_cell, "level_risiko", None), "nama", None)
        color = stored_cell.warna_hex or getattr(getattr(stored_cell, "level_risiko", None), "warna_hex", None)
        score = stored_cell.skor or score
        matrix_source = "stored_cell"

    if not level_name:
        level_name, fallback_color = _fallback_level_from_score(score or (impact * likelihood))
        color = color or fallback_color
        matrix_source = "fallback"

    return {
        "id": item.id,
        "no_risiko": item.no_risiko,
        "peristiwa_risiko": item.peristiwa_risiko,
        "kategori_risiko": str(item.kategori_risiko) if item.kategori_risiko_id else "-",
        "pemilik_risiko": item.pemilik_risiko or "-",
        "status": item.status or "-",
        "summary": str(item.summary),
        "dampak": impact,
        "kemungkinan": likelihood,
        "level": level_name,
        "level_bucket": _resolve_level_bucket(level_name),
        "score": score or (impact * likelihood),
        "color": color or "#d9d9d9",
        "mode": mode,
        "matrix_source": matrix_source,
    }


def _get_filtered_items(request):
    summary_id = request.GET.get("summary")
    year = request.GET.get("tahun")
    status = request.GET.get("status")
    owner = request.GET.get("pemilik")
    category_id = request.GET.get("kategori")
    mode = request.GET.get("mode", "inheren")
    if mode not in dict(MODE_CHOICES):
        mode = "inheren"

    items = ProfilRisikoKorporatItem.objects.all().select_related(
        "summary", "kategori_risiko", "taksonomi_t3", "bumn", "sasaran_kbumn",
        "matrix_cell_inheren__level_risiko", "matrix_cell_residual__level_risiko"
    )
    selected_summary = None

    if summary_id:
        items = items.filter(summary_id=summary_id)
        selected_summary = ProfilRisikoKorporatSummary.objects.filter(pk=summary_id).first()
    if year:
        items = items.filter(summary__tahun=year)
    if status:
        items = items.filter(status=status)
    if owner:
        items = items.filter(pemilik_risiko=owner)
    if category_id:
        items = items.filter(kategori_risiko_id=category_id)

    return items.order_by("summary", "no_item"), selected_summary, mode


def _risk_matrix_context(items_qs, mode="inheren", selected_summary=None):
    matrix = _default_matrix()
    matrix_lookup, dampak_labels, kemungkinan_labels, legend_map = _matrix_lookup(matrix)
    items = list(items_qs)

    max_impact = max(dampak_labels.keys(), default=5)
    max_likelihood = max(kemungkinan_labels.keys(), default=5)
    size = max(getattr(matrix, "ukuran", 5), max_impact, max_likelihood)
    size = min(max(size, 5), 5)

    level_counts = defaultdict(int)
    cell_items = defaultdict(list)
    drilldown_items = []

    for item in items:
        entry = _build_risk_entry(item, mode, matrix_lookup)
        if not entry:
            continue
        level_counts[entry["level_bucket"]] += 1
        legend_map.setdefault(entry["level_bucket"], entry["color"])
        cell_items[(entry["dampak"], entry["kemungkinan"])].append(entry)
        drilldown_items.append(entry)

    grid = []
    for likelihood in range(size, 0, -1):
        row = {
            "value": likelihood,
            "label": kemungkinan_labels.get(likelihood, f"Skala {likelihood}"),
            "cells": [],
        }
        for impact in range(1, size + 1):
            cell_meta = matrix_lookup.get((impact, likelihood))
            cell_risks = sorted(
                cell_items.get((impact, likelihood), []),
                key=lambda risk: (risk["no_risiko"] or 0, risk["peristiwa_risiko"]),
            )
            score = impact * likelihood
            level_name, color = _fallback_level_from_score(score)

            row["cells"].append(
                {
                    "impact": impact,
                    "likelihood": likelihood,
                    "score": score,
                    "level": level_name,
                    "color": color,
                    "count": len(cell_risks),
                    "risks": cell_risks,
                }
            )
        grid.append(row)

    impact_axis = [
        {"value": impact, "label": dampak_labels.get(impact, f"Skala {impact}")}
        for impact in range(1, size + 1)
    ]

    summaries = ProfilRisikoKorporatSummary.objects.order_by("-tahun", "judul")
    years = list(
        ProfilRisikoKorporatSummary.objects.order_by("-tahun").values_list("tahun", flat=True).distinct()
    )
    statuses = list(
        ProfilRisikoKorporatItem.objects.exclude(status__isnull=True).exclude(status__exact="").order_by("status").values_list("status", flat=True).distinct()
    )
    owners = list(
        ProfilRisikoKorporatItem.objects.exclude(pemilik_risiko__isnull=True).exclude(pemilik_risiko__exact="").order_by("pemilik_risiko").values_list("pemilik_risiko", flat=True).distinct()
    )
    categories = list(
        ProfilRisikoKorporatItem.objects.filter(kategori_risiko__isnull=False).select_related("kategori_risiko").order_by("kategori_risiko__nama").values_list("kategori_risiko__id", "kategori_risiko__nama").distinct()
    )

    total_risks = len(drilldown_items)
    defaults = {bucket["name"]: bucket["default_color"] for bucket in LEVEL_FALLBACKS}
    legend = [
        {"name": "Low", "color": "#5a8f3a"},
        {"name": "Low to Moderate", "color": "#a9c98f"},
        {"name": "Moderate", "color": "#fff200"},
        {"name": "Moderate to High", "color": "#f4a300"},
        {"name": "High", "color": "#d00000"},
    ]

    return {
        "matrix": matrix,
        "grid": grid,
        "impact_axis": impact_axis,
        "legend": legend,
        "total_risks": total_risks,
        "level_counts": {
            "high": level_counts.get("High", 0),
            "moderate_to_high": level_counts.get("Moderate to High", 0),
            "moderate": level_counts.get("Moderate", 0),
            "low_to_moderate": level_counts.get("Low to Moderate", 0),
            "low": level_counts.get("Low", 0),
        },
        "mode": mode,
        "mode_label": _get_mode_label(mode),
        "matrix_source_label": "RiskMatrixCell default" if matrix else "Fallback skor standar",
        "drilldown_rows": sorted(drilldown_items, key=lambda row: (row["score"] * -1, row["no_risiko"] or 0)),
        "filters": {
            "summaries": summaries,
            "years": years,
            "statuses": statuses,
            "owners": owners,
            "categories": categories,
            "selected_summary": selected_summary,
            "modes": MODE_CHOICES,
        },
    }


def _export_workbook(context, params):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "RCC Summary"

    dark_fill = PatternFill("solid", fgColor="0D2E5E")
    header_fill = PatternFill("solid", fgColor="D9E5F3")
    white_font = Font(color="FFFFFF", bold=True)
    bold_font = Font(bold=True)

    sheet["A1"] = "Risk Control Center (RCC)"
    sheet["A1"].font = Font(size=16, bold=True)
    sheet["A2"] = f"Mode Monitoring: {context['mode_label']}"
    sheet["A3"] = f"Matriks Aktif: {context['matrix'].nama if context['matrix'] else 'Fallback Standard'}"
    sheet["A4"] = f"Sumber Perhitungan RCC: {context['matrix_source_label']}"

    filter_pairs = [
        ("Profil", params.get("summary") or "Semua"),
        ("Tahun", params.get("tahun") or "Semua"),
        ("Status", params.get("status") or "Semua"),
        ("Pemilik", params.get("pemilik") or "Semua"),
        ("Kategori", params.get("kategori") or "Semua"),
    ]
    start_row = 5
    for idx, (label, value) in enumerate(filter_pairs, start=start_row):
        sheet[f"A{idx}"] = label
        sheet[f"B{idx}"] = value
        sheet[f"A{idx}"].font = bold_font

    stats_row = 12
    stats = [
        ("Total Risiko", context["total_risks"]),
        ("High", context["level_counts"]["high"]),
        ("Moderate to High", context["level_counts"]["moderate_to_high"]),
        ("Moderate", context["level_counts"]["moderate"]),
        ("Low to Moderate", context["level_counts"]["low_to_moderate"]),
        ("Low", context["level_counts"]["low"]),
    ]
    for col_idx, (label, value) in enumerate(stats, start=1):
        cell = sheet.cell(stats_row, col_idx)
        cell.value = label
        cell.fill = dark_fill
        cell.font = white_font
        cell.alignment = Alignment(horizontal="center")
        value_cell = sheet.cell(stats_row + 1, col_idx)
        value_cell.value = value
        value_cell.font = Font(size=14, bold=True)
        value_cell.alignment = Alignment(horizontal="center")

    matrix_sheet = workbook.create_sheet("Heatmap")
    matrix_sheet["A1"] = f"Heatmap RCC - {context['mode_label']}"
    matrix_sheet["A1"].font = Font(size=14, bold=True)
    matrix_sheet["A3"] = "Kemungkinan \\ Dampak"
    matrix_sheet["A3"].fill = dark_fill
    matrix_sheet["A3"].font = white_font

    for col_idx, impact in enumerate(context["impact_axis"], start=2):
        cell = matrix_sheet.cell(3, col_idx)
        cell.value = f"{impact['value']} - {impact['label']}"
        cell.fill = header_fill
        cell.font = bold_font
        cell.alignment = Alignment(horizontal="center", wrap_text=True)

    for row_idx, row in enumerate(context["grid"], start=4):
        label_cell = matrix_sheet.cell(row_idx, 1)
        label_cell.value = f"{row['value']} - {row['label']}"
        label_cell.fill = header_fill
        label_cell.font = bold_font
        label_cell.alignment = Alignment(wrap_text=True)
        for col_idx, cell_data in enumerate(row["cells"], start=2):
            cell = matrix_sheet.cell(row_idx, col_idx)
            cell.value = f"{cell_data['count']} risiko\n{cell_data['level']}\nSkor {cell_data['score']}"
            cell.fill = PatternFill("solid", fgColor=(cell_data["color"] or "#D9D9D9").replace("#", ""))
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    detail_sheet = workbook.create_sheet("Drilldown")
    headers = [
        "No Risiko",
        "Peristiwa Risiko",
        "Kategori Risiko",
        "Pemilik Risiko",
        "Status",
        "Mode",
        "Dampak",
        "Kemungkinan",
        "Level",
        "Skor",
        "Summary",
    ]
    for col_idx, header in enumerate(headers, start=1):
        cell = detail_sheet.cell(1, col_idx)
        cell.value = header
        cell.fill = dark_fill
        cell.font = white_font
        cell.alignment = Alignment(horizontal="center")

    for row_idx, risk in enumerate(context["drilldown_rows"], start=2):
        detail_sheet.cell(row_idx, 1).value = risk["no_risiko"]
        detail_sheet.cell(row_idx, 2).value = risk["peristiwa_risiko"]
        detail_sheet.cell(row_idx, 3).value = risk["kategori_risiko"]
        detail_sheet.cell(row_idx, 4).value = risk["pemilik_risiko"]
        detail_sheet.cell(row_idx, 5).value = risk["status"]
        detail_sheet.cell(row_idx, 6).value = context["mode_label"]
        detail_sheet.cell(row_idx, 7).value = risk["dampak"]
        detail_sheet.cell(row_idx, 8).value = risk["kemungkinan"]
        detail_sheet.cell(row_idx, 9).value = risk["level"]
        detail_sheet.cell(row_idx, 10).value = risk["score"]
        detail_sheet.cell(row_idx, 11).value = risk["summary"]

    widths = {
        "RCC Summary": {"A": 20, "B": 32},
        "Heatmap": {"A": 28, "B": 22, "C": 22, "D": 22, "E": 22, "F": 22},
        "Drilldown": {"A": 12, "B": 50, "C": 26, "D": 26, "E": 18, "F": 14, "G": 12, "H": 14, "I": 22, "J": 10, "K": 30},
    }
    for ws in workbook.worksheets:
        for col, width in widths.get(ws.title, {}).items():
            ws.column_dimensions[col].width = width

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output.getvalue()


def dashboard(request):
    items, selected_summary, mode = _get_filtered_items(request)
    context = _risk_matrix_context(items, mode=mode, selected_summary=selected_summary)
    context["page_title"] = "Risk Control Center (RCC)"
    return render(request, "dashboard.html", context)


def export_rcc_excel(request):
    items, selected_summary, mode = _get_filtered_items(request)
    context = _risk_matrix_context(items, mode=mode, selected_summary=selected_summary)
    file_bytes = _export_workbook(context, request.GET)

    response = HttpResponse(
        file_bytes,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="rcc_{mode}.xlsx"'
    return response


def kpmr_review_view(request, summary_id):
    summary = get_object_or_404(KPMRSummary, pk=summary_id)

    items = summary.item.select_related(
        "reassessment_item",
        "reassessment_item__km_item"
    ).order_by("no_item")

    context = {
        "summary": summary,
        "items": items,
    }

    return render(request, "risk/kpmr_review.html", context)


@csrf_exempt
def kpmr_update_item(request):
    if request.method == "POST":
        data = json.loads(request.body)

        item_id = data.get("id")
        field = data.get("field")
        value = data.get("value")

        try:
            item = KPMRItem.objects.get(id=item_id)

            if field == "perlakuan_risiko":
                item.perlakuan_risiko = value
            elif field == "bukti":
                item.bukti = value
            elif field == "nilai_kpmr":
                item.nilai_kpmr = int(value) if value else None
            elif field == "status_kpmr":
                item.status_kpmr = value
            elif field == "catatan":
                item.catatan = value

            item.save()

            return JsonResponse({"status": "success"})

        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)})

    return JsonResponse({"status": "invalid"})
