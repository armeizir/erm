from __future__ import annotations

import io
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean

from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image as ReportLabImage,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .models import MonteCarloMetricHistory, MultiMetricMonteCarloResult, RiskMetric


PRIMARY = colors.HexColor("#12345B")
SECONDARY = colors.HexColor("#3B5976")
LIGHT_BG = colors.HexColor("#F3F6FA")
GRID = colors.HexColor("#D9E1EC")
TEXT = colors.HexColor("#1F2937")
PLN_TEAL = colors.HexColor("#00A6B4")
PLN_DARK_TEAL = colors.HexColor("#075D73")
LMR_LOGO_PATH = Path(__file__).resolve().parent.parent / "media" / "system" / "logo" / "pln_batam_logo_1.png"


def _safe_float(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError, InvalidOperation, AttributeError):
        return default


def _fmt_num(value, digits=2, dash="-"):
    if value in (None, ""):
        return dash
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_int(value, dash="-"):
    if value in (None, ""):
        return dash
    try:
        return f"{int(float(value)):,}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_pct(value, dash="-"):
    if value in (None, ""):
        return dash
    try:
        return f"{float(value):,.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _distribution_label(value):
    labels = {
        "normal": "Distribusi Normal",
        "lognormal": "Lognormal",
        "triangular": "Triangular",
        "uniform": "Uniform",
        "beta": "Beta",
        "gamma": "Gamma",
        "weibull": "Weibull",
        "empirical": "Empirical Distribution",
    }
    return labels.get(value or "", value or "-")


def _history_stats(rows):
    values = [_safe_float(row.get("actual")) for row in rows if row.get("actual") not in (None, "")]
    dates = [row.get("tanggal") for row in rows if row.get("tanggal")]
    return {
        "count": len(values),
        "start": min(dates) if dates else "-",
        "end": max(dates) if dates else "-",
        "mean": mean(values) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def _summarize_warnings(warnings, max_items=2):
    if not warnings:
        return "Tidak ada warning kualitas data yang tersimpan."
    selected = [str(item) for item in warnings[:max_items]]
    remaining = len(warnings) - len(selected)
    text = "; ".join(selected)
    if remaining > 0:
        text = f"{text}; +{remaining} warning lain pada bagian Analisis Distribusi."
    return text


def _live_history_rows(metric, forecast_periode=None):
    histories = MonteCarloMetricHistory.objects.filter(metric=metric).select_related("periode")
    if forecast_periode and getattr(forecast_periode, "tanggal_selesai", None):
        histories = histories.filter(tanggal_data__lte=forecast_periode.tanggal_selesai)
    rows = []
    for history in histories.order_by("tanggal_data", "id"):
        rows.append({
            "periode": str(history.periode) if history.periode_id else "-",
            "tanggal": history.tanggal_data.isoformat() if history.tanggal_data else "",
            "actual": _safe_float(history.metric_value),
        })
    return rows


def _metric_context(result):
    snapshot = result.metric_snapshot or {}
    metric_rows = snapshot.get("metrics") or []
    analyses = {
        item.get("metric_id"): item
        for item in (snapshot.get("distribution_analyses") or [])
    }

    if not metric_rows and result.corporate_risk_item_id:
        live_metrics = RiskMetric.objects.filter(
            corporate_risk_item=result.corporate_risk_item,
            is_active=True,
        ).order_by("name")
        metric_rows = [
            {
                "metric_id": metric.pk,
                "metric_name": metric.name,
                "unit": metric.unit,
                "direction": metric.get_direction_display(),
                "weight": _safe_float(metric.weight),
                "history_rows": _live_history_rows(metric, result.forecast_periode),
            }
            for metric in live_metrics
        ]

    rows = []
    for row in metric_rows:
        metric_id = row.get("metric_id")
        recommendation = row.get("distribution_recommendation") or {}
        analysis = analyses.get(metric_id) or {}
        history_rows = row.get("history_rows") or []
        stats = _history_stats(history_rows)
        warnings = (
            analysis.get("warnings")
            or recommendation.get("data_quality_warnings")
            or []
        )
        if stats["count"] and stats["count"] < 24:
            warnings = list(warnings) + [
                "Data histori kurang dari 24 bulan sehingga hasil perlu dikombinasikan dengan expert judgement."
            ]

        rows.append({
            "name": row.get("metric_name") or "-",
            "unit": row.get("unit") or "-",
            "direction": row.get("direction") or "-",
            "weight": row.get("weight"),
            "history": stats,
            "recommended_distribution": (
                analysis.get("recommended_label")
                or recommendation.get("recommended_label")
                or _distribution_label(analysis.get("recommended_distribution") or recommendation.get("recommended"))
            ),
            "confidence": analysis.get("confidence") or recommendation.get("confidence") or "-",
            "reason_summary": analysis.get("reason_summary") or recommendation.get("reason_summary") or "-",
            "reason_detail": analysis.get("reason_detail") or recommendation.get("reason_detail") or "-",
            "limitations": analysis.get("limitations") or recommendation.get("limitations") or "-",
            "alternatives": analysis.get("alternative_distributions") or recommendation.get("alternative_distributions") or [],
            "warnings": warnings or ["Tidak ada warning kualitas data yang tersimpan."],
        })
    return rows


def build_multi_metric_pdf_context(result):
    snapshot = result.simulation_snapshot or {}
    target_analysis = snapshot.get("target_analysis") or {}
    metrics = _metric_context(result)
    printed_at = timezone.localtime(timezone.now())
    item = result.corporate_risk_item
    summary = getattr(item, "summary", None)
    trials = (
        target_analysis.get("total_simulation")
        or snapshot.get("n_simulations")
        or result.n_simulations
        or 0
    )

    return {
        "result": result,
        "item": item,
        "summary": summary,
        "printed_at": printed_at,
        "target_analysis": target_analysis,
        "metrics": metrics,
        "trials": trials,
        "prediction_interval": result.get_prediction_interval_display() if result.prediction_interval else "-",
        "forecasting_method": result.get_forecasting_method_display() if result.forecasting_method else "-",
        "distribution_selected": _distribution_label(result.distribution_type),
        "distribution_recommended": _distribution_label(result.recommended_distribution),
        "chart_values": target_analysis.get("distribution_sample") or [],
        "target_value": target_analysis.get("target_value") or result.target_value,
    }


def generate_distribution_chart(result, width=1100, height=520):
    context = build_multi_metric_pdf_context(result)
    values = [_safe_float(value) for value in context["chart_values"] if value not in (None, "")]
    values = [value for value in values if value == value]
    if not values:
        return None

    target = _safe_float(context["target_value"], None)
    trials = int(_safe_float(context["trials"], len(values)) or len(values))

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("Arial.ttf", 18)
        small = ImageFont.truetype("Arial.ttf", 14)
        title_font = ImageFont.truetype("Arial.ttf", 26)
    except OSError:
        font = small = title_font = ImageFont.load_default()

    left, right, top, bottom = 90, width - 40, 78, height - 70
    draw.text((left, 22), f"Forecast DMP - {trials:,} Trials", fill=(18, 52, 91), font=title_font)

    minimum, maximum = min(values), max(values)
    if minimum == maximum:
        minimum -= 1
        maximum += 1
    bin_count = min(44, max(18, round(len(values) ** 0.5)))
    bin_width = (maximum - minimum) / bin_count
    bins = [0 for _ in range(bin_count)]
    for value in values:
        index = int((value - minimum) / bin_width)
        index = max(0, min(bin_count - 1, index))
        bins[index] += 1

    max_count = max(bins) or 1
    plot_width = right - left
    plot_height = bottom - top
    draw.rectangle((left, top, right, bottom), outline=(217, 225, 236), width=2)

    for idx, count in enumerate(bins):
        x0 = left + (idx * plot_width / bin_count)
        x1 = left + ((idx + 1) * plot_width / bin_count) - 2
        y1 = bottom
        y0 = bottom - (count / max_count * plot_height)
        center_value = minimum + ((idx + 0.5) * bin_width)
        color = (220, 38, 38) if target is not None and center_value < target else (37, 99, 235)
        draw.rectangle((x0, y0, x1, y1), fill=color, outline=(255, 255, 255))

    points = []
    for idx, count in enumerate(bins):
        x = left + ((idx + 0.5) * plot_width / bin_count)
        y = bottom - (count / max_count * plot_height)
        points.append((x, y))
    if len(points) > 1:
        draw.line(points, fill=(245, 158, 11), width=4)

    if target is not None and minimum <= target <= maximum:
        target_x = left + ((target - minimum) / (maximum - minimum) * plot_width)
        draw.line((target_x, top, target_x, bottom), fill=(18, 52, 91), width=3)
        draw.text((min(target_x + 8, right - 145), top + 8), f"Target {_fmt_int(target)}", fill=(18, 52, 91), font=small)

    for step in range(6):
        value = max_count * step / 5
        y = bottom - (value / max_count * plot_height)
        draw.line((left - 5, y, left, y), fill=(100, 116, 139), width=1)
        draw.text((18, y - 8), _fmt_int(value), fill=(71, 85, 105), font=small)

    for step in range(5):
        value = minimum + ((maximum - minimum) * step / 4)
        x = left + (plot_width * step / 4)
        draw.line((x, bottom, x, bottom + 5), fill=(100, 116, 139), width=1)
        draw.text((x - 35, bottom + 12), _fmt_int(value), fill=(71, 85, 105), font=small)

    draw.text((width // 2 - 55, height - 28), "Forecast Total", fill=(31, 41, 55), font=font)
    draw.text((12, top + 10), "Frequency", fill=(31, 41, 55), font=font)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _header_footer(canvas, doc, printed_at, document_title="Multi Metric Monte Carlo Result"):
    canvas.saveState()
    width, height = canvas._pagesize
    canvas.setFillColor(PRIMARY)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(doc.leftMargin, height - 1.0 * cm, f"ERM PLN Batam | {document_title}")
    canvas.setStrokeColor(GRID)
    canvas.line(doc.leftMargin, height - 1.18 * cm, width - doc.rightMargin, height - 1.18 * cm)
    canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.setFont("Helvetica", 8)
    canvas.drawString(doc.leftMargin, 0.8 * cm, f"Tanggal cetak: {printed_at:%d %B %Y %H:%M}")
    canvas.drawRightString(width - doc.rightMargin, 0.8 * cm, f"Halaman {doc.page}")
    canvas.restoreState()


def _styles():
    base = getSampleStyleSheet()
    base.add(ParagraphStyle(
        name="ReportTitle",
        parent=base["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=28,
        alignment=TA_CENTER,
        textColor=PRIMARY,
        spaceAfter=18,
    ))
    base.add(ParagraphStyle(
        name="Section",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=PRIMARY,
        spaceBefore=12,
        spaceAfter=8,
    ))
    base.add(ParagraphStyle(
        name="Body",
        parent=base["BodyText"],
        fontSize=9,
        leading=13,
        textColor=TEXT,
        alignment=TA_LEFT,
    ))
    base.add(ParagraphStyle(
        name="Small",
        parent=base["BodyText"],
        fontSize=8,
        leading=11,
        textColor=TEXT,
    ))
    return base


def _table(data, widths=None, repeat_rows=0):
    table = Table(data, colWidths=widths, repeatRows=repeat_rows, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _lmr_header_footer(canvas, doc, printed_at):
    canvas.saveState()
    width, height = canvas._pagesize

    if doc.page == 1:
        canvas.setFillColor(colors.HexColor("#F2F2F2"))
        canvas.rect(width - 4.1 * cm, 2.0 * cm, 3.5 * cm, height - 4.0 * cm, fill=1, stroke=0)
    else:
        canvas.setFillColor(PRIMARY)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(doc.leftMargin, height - 0.85 * cm, "Laporan Manajemen Risiko Korporat")
        canvas.setStrokeColor(GRID)
        canvas.line(doc.leftMargin, height - 1.02 * cm, width - doc.rightMargin, height - 1.02 * cm)

    canvas.setFillColor(colors.HexColor("#F97316"))
    canvas.setFont("Helvetica-Oblique", 7)
    canvas.drawString(doc.leftMargin, 0.68 * cm, "Dokumen Rahasia")
    canvas.setFillColor(PLN_TEAL)
    canvas.rect(width - 12.2 * cm, 0.45 * cm, 8.8 * cm, 0.45 * cm, fill=1, stroke=0)
    canvas.setFillColor(PLN_DARK_TEAL)
    canvas.rect(width - 3.4 * cm, 0.45 * cm, 2.6 * cm, 0.45 * cm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica", 5.5)
    canvas.drawCentredString(width - 7.8 * cm, 0.58 * cm, "Dokumen ini milik PT PLN Batam, dilarang menyalin atau memperbanyak dokumen tanpa izin")
    canvas.setFont("Helvetica", 6.5)
    canvas.drawCentredString(width - 2.1 * cm, 0.58 * cm, "PT PLN Batam")
    canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(width - doc.rightMargin, 0.23 * cm, f"Halaman {doc.page}")
    canvas.restoreState()


def _lmr_logo(width=3.4 * cm, height=1.7 * cm):
    if LMR_LOGO_PATH.exists():
        return ReportLabImage(str(LMR_LOGO_PATH), width=width, height=height)
    return Paragraph("PLN Batam", _styles()["Section"])


def _p(styles, text, style="Body"):
    return Paragraph(str(text or "-").replace("\n", "<br/>"), styles[style])


def _recommendations(item_name):
    is_cyber = "cyber" in (item_name or "").lower() or "it/ot" in (item_name or "").lower()
    if is_cyber:
        rows = [
            ("Penguatan monitoring IT/OT melalui SOC/SIEM dan korelasi alert prioritas.", "Tinggi", "Divisi IT/OT Security", "0-3 bulan", "Alert kritikal terpantau dan ditindaklanjuti sesuai SLA."),
            ("Vulnerability assessment dan penetration test pada sistem kritikal.", "Tinggi", "IT Security", "0-3 bulan", "Temuan high/critical memiliki rencana remedi."),
            ("Hardening, patch management, dan baseline konfigurasi sistem kritikal.", "Tinggi", "Infrastructure & OT", "0-6 bulan", "Patch compliance dan konfigurasi baseline meningkat."),
            ("Segmentasi jaringan IT/OT dan review akses privileged.", "Tinggi", "Network & OT", "0-6 bulan", "Akses lintas zona terdokumentasi dan dibatasi."),
            ("Incident response drill untuk skenario serangan cyber terhadap operasi.", "Sedang", "BCM/IT Security", "3-6 bulan", "Drill selesai dan lesson learned ditindaklanjuti."),
            ("Penguatan backup, recovery test, dan proteksi data kritikal.", "Sedang", "Infrastructure", "3-6 bulan", "Recovery test memenuhi RTO/RPO yang disepakati."),
            ("Awareness dan access control untuk akun pengguna berisiko tinggi.", "Sedang", "HC & IT", "Berjalan", "MFA dan pelatihan pengguna prioritas terlaksana."),
        ]
    else:
        rows = [
            ("Perkuat monitoring indikator utama risiko dan tetapkan trigger eskalasi.", "Tinggi", "Risk Owner", "0-3 bulan", "Dashboard bulanan dan threshold eskalasi aktif."),
            ("Review asumsi target, appetite, dan driver utama risiko.", "Tinggi", "Risk Owner/Risk Management", "0-3 bulan", "Asumsi dan appetite terdokumentasi ulang."),
            ("Perbarui data histori dan lakukan generate ulang simulasi secara berkala.", "Sedang", "Risk Management", "Bulanan", "Data aktual terbaru tersedia setiap periode."),
            ("Susun rencana mitigasi tambahan untuk skenario P80/P95.", "Sedang", "Risk Owner", "3-6 bulan", "Rencana aksi dan owner disetujui."),
            ("Lakukan review manajemen bila probabilitas tidak tercapai melewati appetite.", "Tinggi", "Manajemen", "Saat trigger", "Keputusan eskalasi terdokumentasi."),
        ]
    return rows


def render_multi_metric_pdf(result):
    context = build_multi_metric_pdf_context(result)
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.35 * cm,
        leftMargin=1.35 * cm,
        topMargin=1.55 * cm,
        bottomMargin=1.35 * cm,
        title=f"Multi Metric Monte Carlo Result {result.pk}",
    )
    story = []
    target = context["target_analysis"]
    item_label = getattr(context["item"], "get_display_label", lambda: str(context["item"]))()
    summary = context["summary"]

    story.append(Spacer(1, 0.6 * cm))
    story.append(_p(styles, "Laporan Multi Metric Monte Carlo Risk Forecast", "ReportTitle"))
    cover_rows = [
        ["Item Risiko Korporat", item_label],
        ["Profil Risiko Korporat", str(summary) if summary else "-"],
        ["Periode Forecast", str(result.forecast_periode) if result.forecast_periode_id else "-"],
        ["Tanggal Cetak", f"{context['printed_at']:%d %B %Y %H:%M}"],
        ["Aplikasi / Perusahaan", "ERM PLN Batam"],
    ]
    story.append(_table([["Informasi", "Keterangan"]] + cover_rows, widths=[4.5 * cm, 12 * cm], repeat_rows=1))
    story.append(PageBreak())

    story.append(_p(styles, "Executive Summary", "Section"))
    status = target.get("target_status") or result.target_status or "-"
    certainty = _fmt_pct(target.get("probability_achieve_target") or result.probability_achieve_target)
    forecast_dmp = _fmt_num(target.get("forecast_total") or result.baseline_value, 0)
    var_95 = _fmt_num(target.get("var_95") or result.var_95, 0)
    cut_off = _fmt_num(target.get("target_value") or result.target_value, 0)
    summary_paragraphs = [
        f"Laporan ini menyajikan hasil simulasi Multi Metric Monte Carlo untuk {item_label}. Simulasi digunakan untuk memperkirakan distribusi kemungkinan hasil risiko berdasarkan data historis, bobot metric, serta parameter forecast yang dipilih oleh user.",
        f"Model dijalankan dengan { _fmt_int(context['trials']) } trials, periode forecast {result.forecast_periode}, metode {context['forecasting_method']}, dan prediction interval {context['prediction_interval']}. Pendekatan ini memberi gambaran rentang hasil yang mungkin terjadi, bukan satu angka deterministik.",
        f"Hasil utama menunjukkan Forecast DMP sebesar {forecast_dmp}, certainty target tercapai {certainty}, VaR/P95 sebesar {var_95}, dan cut-off target {cut_off}. Status target saat laporan dicetak adalah {status}.",
        "Untuk manajemen, hasil ini perlu dibaca bersama kualitas data histori, confidence rekomendasi distribusi, serta expert judgement risk owner. Bila probabilitas tidak tercapai berada di atas risk appetite, mitigasi tambahan perlu diprioritaskan.",
    ]
    for paragraph in summary_paragraphs:
        story.append(_p(styles, paragraph))
        story.append(Spacer(1, 4))

    story.append(_p(styles, "Informasi Utama Simulasi", "Section"))
    main_rows = [
        ["Item Risiko Korporat", item_label],
        ["Periode Forecast", str(result.forecast_periode) if result.forecast_periode_id else "-"],
        ["Forecasting Method", context["forecasting_method"]],
        ["Periods to Forecast", _fmt_int(result.forecast_periods)],
        ["Prediction Interval", context["prediction_interval"]],
        ["Monte Carlo Trials", _fmt_int(context["trials"])],
        ["Model Distribusi Terpilih", context["distribution_selected"]],
        ["Model Distribusi Rekomendasi Sistem", context["distribution_recommended"]],
        ["Justifikasi User", result.selected_distribution_justification or "-"],
        ["Scenario Percentile", f"P{result.scenario_percentile}" if result.scenario_percentile else "-"],
        ["Baseline / P50", _fmt_num(result.baseline_value, 0)],
        ["VaR 95% / P95", _fmt_num(result.var_95, 0)],
        ["Certainty Target Tercapai", certainty],
        ["Cut-off Target", cut_off],
    ]
    story.append(_table([["Parameter", "Nilai"]] + main_rows, widths=[5.2 * cm, 11.3 * cm], repeat_rows=1))

    story.append(_p(styles, "Ringkasan Metric", "Section"))
    metric_table = [[
        "Risk Metric", "Unit", "Direction", "Weight", "Histori", "Periode Histori", "Avg", "Min", "Max"
    ]]
    for metric in context["metrics"]:
        hist = metric["history"]
        metric_table.append([
            _p(styles, metric["name"], "Small"),
            metric["unit"],
            metric["direction"],
            _fmt_num(metric["weight"], 2),
            _fmt_int(hist["count"]),
            _p(styles, f"{hist['start']} s.d. {hist['end']}", "Small"),
            _fmt_num(hist["mean"], 2),
            _fmt_num(hist["min"], 2),
            _fmt_num(hist["max"], 2),
        ])
    if len(metric_table) == 1:
        metric_table.append(["-", "-", "-", "-", "0", "-", "-", "-", "-"])
    story.append(_table(
        metric_table,
        widths=[4.2*cm, 1.6*cm, 2.0*cm, 1.3*cm, 1.2*cm, 3.2*cm, 1.3*cm, 1.3*cm, 1.3*cm],
        repeat_rows=1,
    ))
    story.append(Spacer(1, 8))

    metric_quality_table = [["Risk Metric", "Rekomendasi Distribusi", "Confidence", "Warning Kualitas Data"]]
    for metric in context["metrics"]:
        metric_quality_table.append([
            _p(styles, metric["name"], "Small"),
            _p(styles, metric["recommended_distribution"], "Small"),
            metric["confidence"],
            _p(styles, _summarize_warnings(metric["warnings"]), "Small"),
        ])
    if len(metric_quality_table) == 1:
        metric_quality_table.append(["-", "-", "-", "Metric history belum tersedia."])
    story.append(_table(
        metric_quality_table,
        widths=[4.4*cm, 3.8*cm, 2.0*cm, 6.3*cm],
        repeat_rows=1,
    ))

    story.append(_p(styles, "Analisis Distribusi", "Section"))
    for metric in context["metrics"]:
        alternatives = metric["alternatives"]
        if alternatives and isinstance(alternatives[0], dict):
            alternatives = [item.get("distribution") or item.get("label") or str(item) for item in alternatives]
        block = [
            _p(styles, metric["name"], "Section"),
            _table([
                ["Aspek", "Analisis"],
                ["Rekomendasi distribusi", metric["recommended_distribution"]],
                ["Alasan ringkas", _p(styles, metric["reason_summary"], "Small")],
                ["Alasan detail", _p(styles, metric["reason_detail"], "Small")],
                ["Limitasi", _p(styles, metric["limitations"], "Small")],
                ["Alternatif", ", ".join(map(str, alternatives)) if alternatives else "-"],
                ["Warning kualitas data", _p(styles, "; ".join(metric["warnings"]), "Small")],
            ], widths=[4.0 * cm, 12.5 * cm], repeat_rows=1),
        ]
        story.append(KeepTogether(block))

    story.append(PageBreak())
    story.append(_p(styles, "Grafik Distribusi Output", "Section"))
    chart = generate_distribution_chart(result)
    if chart:
        story.append(ReportLabImage(chart, width=16.2 * cm, height=7.65 * cm))
    else:
        story.append(_p(styles, "Grafik tidak tersedia karena data distribusi output belum lengkap. Generate ulang hasil simulasi setelah data histori dan target tersedia."))

    story.append(_p(styles, "Interpretasi Hasil", "Section"))
    interpretations = [
        f"Forecast DMP adalah estimasi nilai tengah distribusi output Monte Carlo. Nilai ini membantu manajemen memahami skenario dasar yang paling representatif dari hasil simulasi.",
        f"Certainty Target Tercapai sebesar {certainty} menunjukkan proporsi skenario simulasi yang mencapai atau melewati target/cut-off. Semakin rendah nilai ini, semakin besar kebutuhan review target, appetite, atau mitigasi.",
        f"VaR/P95 sebesar {var_95} menggambarkan besaran risiko pada skenario ekstrem yang perlu dipantau. Nilai ini sebaiknya digunakan untuk menetapkan trigger eskalasi dan kesiapan respons.",
        "Jika target berada jauh di kanan distribusi, target relatif sulit dicapai berdasarkan pola histori. Jika target berada jauh di kiri distribusi, peluang pencapaian lebih tinggi namun tetap perlu monitoring terhadap perubahan driver risiko.",
        f"Dengan status {status}, keputusan manajemen yang disarankan adalah {'mitigasi tambahan dan eskalasi berkala' if result.requires_mitigation else 'monitor berkala dengan penguatan data histori dan trigger eskalasi'}."
    ]
    for item in interpretations:
        story.append(_p(styles, item))
        story.append(Spacer(1, 4))

    story.append(_p(styles, "Rekomendasi Mitigasi Manajemen", "Section"))
    rec_rows = [["No", "Rekomendasi", "Prioritas", "PIC", "Timeline", "Indikator Keberhasilan"]]
    for idx, row in enumerate(_recommendations(item_label), start=1):
        rec_rows.append([str(idx), _p(styles, row[0], "Small"), row[1], row[2], row[3], _p(styles, row[4], "Small")])
    story.append(_table(rec_rows, widths=[0.8*cm, 6.0*cm, 1.8*cm, 3.0*cm, 2.0*cm, 3.2*cm], repeat_rows=1))

    story.append(_p(styles, "Kesimpulan", "Section"))
    decision = "monitor berkala"
    if result.requires_mitigation:
        decision = "mitigasi tambahan dan eskalasi kepada manajemen"
    story.append(_p(
        styles,
        f"Secara keseluruhan, simulasi menunjukkan status target {status} dengan certainty {certainty}. "
        f"Keputusan yang disarankan untuk Direksi/Manajemen adalah {decision}. Hasil ini perlu diperbarui secara berkala "
        "setiap kali data aktual baru tersedia agar gambaran risiko tetap relevan."
    ))

    story.append(_p(styles, "Disclaimer Model", "Section"))
    disclaimers = [
        "Monte Carlo adalah model probabilistik, bukan kepastian hasil masa depan.",
        "Akurasi sangat tergantung pada kualitas, konsistensi, dan panjang data histori.",
        "Untuk data terbatas, hasil perlu dikombinasikan dengan expert judgement risk owner dan manajemen.",
        "Output laporan digunakan sebagai alat bantu pengambilan keputusan risiko, bukan satu-satunya dasar keputusan.",
    ]
    for item in disclaimers:
        story.append(_p(styles, f"- {item}"))

    doc.build(story, onFirstPage=lambda c, d: _header_footer(c, d, context["printed_at"]), onLaterPages=lambda c, d: _header_footer(c, d, context["printed_at"]))
    pdf = buffer.getvalue()
    buffer.close()
    return pdf


def _latest_result_by_item(summary, period):
    queryset = (
        MultiMetricMonteCarloResult.objects
        .filter(corporate_risk_item__summary=summary)
        .select_related("corporate_risk_item", "forecast_periode")
        .order_by("corporate_risk_item_id", "-created_at", "-id")
    )
    if period:
        queryset = queryset.filter(forecast_periode=period)

    results = {}
    for result in queryset:
        results.setdefault(result.corporate_risk_item_id, result)
    return results


def render_quarterly_lmr_pdf(summary, period=None):
    items = list(
        summary.item
        .select_related(
            "bumn",
            "kategori_risiko",
            "taksonomi_t3",
            "matrix_cell_inheren__level_risiko",
            "matrix_cell_residual__level_risiko",
        )
        .prefetch_related(
            "risk_metrics__metric_histories",
            "rencana_perlakuan_items__opsi_perlakuan_risiko",
            "daftar_penyebab__pemilik_risiko",
            "sumber_risiko__reassessment_item__summary__unit_bisnis",
        )
        .order_by("no_item", "no_risiko")
    )
    results_by_item = _latest_result_by_item(summary, period)
    printed_at = timezone.localtime(timezone.now())

    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.9 * cm,
        leftMargin=0.9 * cm,
        topMargin=1.25 * cm,
        bottomMargin=1.2 * cm,
        title=f"LMR {summary.tahun}",
    )
    report_period = str(period) if period else "Semua periode"
    report_title = "LAPORAN MANAJEMEN RISIKO TRIWULANAN"
    cover_title = _p(styles, "LAPORAN<br/>MANAJEMEN RISIKO<br/>KORPORAT", "ReportTitle")
    cover_period = _p(styles, f"{report_period.upper()} TAHUN {summary.tahun}", "Section")
    cover_table = Table(
        [[_lmr_logo(), cover_title], ["", cover_period]],
        colWidths=[4.0 * cm, 10.8 * cm],
        rowHeights=[3.2 * cm, 1.2 * cm],
        hAlign="LEFT",
    )
    cover_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBEFORE", (1, 0), (1, 1), 0.6, colors.HexColor("#8DB4E2")),
        ("LINEABOVE", (0, 1), (1, 1), 0.6, colors.HexColor("#8DB4E2")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story = [
        Spacer(1, 5.2 * cm),
        cover_table,
        Spacer(1, 7.0 * cm),
        _p(styles, f"{printed_at:%B %Y}", "Small"),
        _p(styles, "Direktorat Keuangan, Manajemen Risiko, dan Human Capital", "Small"),
        PageBreak(),
        _p(styles, "LEMBAR PENGESAHAN", "ReportTitle"),
        _table([
            ["Uraian", "Keterangan"],
            ["Judul Dokumen", report_title],
            ["Profil Risiko", str(summary)],
            ["Periode", report_period],
            ["Perusahaan", f"{summary.nama_perusahaan} ({summary.kode_perusahaan})"],
            ["Tahun", summary.tahun],
            ["Tanggal Cetak", f"{printed_at:%d %B %Y %H:%M}"],
        ], widths=[4.2 * cm, 14.6 * cm], repeat_rows=1),
        Spacer(1, 18),
        _table([
            ["Disusun Oleh", "Diperiksa Oleh", "Disahkan Oleh"],
            ["", "", ""],
            ["Risk Management", "Manajemen Terkait", "Direksi / Pejabat Berwenang"],
        ], widths=[6.25 * cm, 6.25 * cm, 6.25 * cm], repeat_rows=1),
        PageBreak(),
        _p(styles, "DAFTAR ISI", "ReportTitle"),
        _table([
            ["Bagian", "Hal."],
            ["LEMBAR PENGESAHAN", "i"],
            ["DAFTAR ISI", "ii"],
            ["DAFTAR TABEL", "iii"],
            ["DAFTAR GAMBAR", "iv"],
            ["BAB I STRATEGI RISIKO", "1"],
            ["1.1 Konteks Strategi Risiko", "1"],
            ["1.2 Arah dan Fokus Pengelolaan Risiko", "1"],
            ["BAB II PEMANTAUAN PROFIL RISIKO", "2"],
            ["2.1 Ringkasan Pemantauan Profil Risiko", "2"],
            ["2.2 Daftar Profil Risiko Korporat", "2"],
            ["2.3 Pemantauan Hasil Monte Carlo", "3"],
            ["BAB III PEMANTAUAN RENCANA PERLAKUAN RISIKO", "4"],
            ["3.1 Ringkasan Rencana Perlakuan Risiko", "4"],
            ["3.2 Status dan Tindak Lanjut Perlakuan Risiko", "4"],
            ["BAB IV PEMANTAUAN KRI DAN KEJADIAN RISIKO", "5"],
            ["4.1 Pemantauan Key Risk Indicator", "5"],
            ["4.2 Sumber Risiko dan Kejadian yang Perlu Dipantau", "5"],
            ["BAB V PENUTUP", "6"],
        ], widths=[16.0 * cm, 2.8 * cm], repeat_rows=1),
        PageBreak(),
        _p(styles, "DAFTAR TABEL", "ReportTitle"),
        _table([
            ["No", "Nama Tabel", "Hal."],
            ["Tabel 1", "Informasi Laporan Manajemen Risiko", "1"],
            ["Tabel 2", "Ringkasan Pemantauan Profil Risiko", "2"],
            ["Tabel 3", "Daftar Profil Risiko Korporat", "2"],
            ["Tabel 4", "Ringkasan Hasil Monte Carlo", "3"],
            ["Tabel 5", "Rencana Perlakuan Risiko Korporat", "4"],
            ["Tabel 6", "Pemantauan KRI dan Sumber Risiko", "5"],
            ["Tabel 7", "Ringkasan Tindak Lanjut Manajemen", "6"],
        ], widths=[2.5 * cm, 13.5 * cm, 2.8 * cm], repeat_rows=1),
        PageBreak(),
        _p(styles, "DAFTAR GAMBAR", "ReportTitle"),
        _table([
            ["No", "Nama Gambar", "Hal."],
            ["Gambar 1", "Kerangka Strategi Risiko dan Monitoring LMR", "1"],
        ], widths=[2.5 * cm, 13.5 * cm, 2.8 * cm], repeat_rows=1),
        PageBreak(),
        _p(styles, "BAB I STRATEGI RISIKO", "ReportTitle"),
        _p(styles, "1.1 Konteks Strategi Risiko", "Section"),
        _p(
            styles,
            "Strategi risiko disusun untuk memastikan pencapaian sasaran perusahaan tetap berada dalam batas risk appetite "
            "yang dapat diterima. LMR triwulanan digunakan sebagai sarana pemantauan profil risiko, efektivitas mitigasi, "
            "dan proyeksi eksposur risiko berdasarkan data historis serta simulasi Monte Carlo.",
        ),
        Spacer(1, 6),
        _p(styles, "Tabel 1. Informasi Laporan Manajemen Risiko", "Small"),
        _table([
            ["Informasi", "Keterangan", "Informasi", "Keterangan"],
            ["Profil Risiko", str(summary), "Periode LMR", report_period],
            ["Perusahaan", f"{summary.nama_perusahaan} ({summary.kode_perusahaan})", "Tahun", summary.tahun],
            ["Status Profil", summary.status, "Tanggal Cetak", f"{printed_at:%d %B %Y %H:%M}"],
        ], widths=[2.6 * cm, 6.8 * cm, 2.6 * cm, 6.8 * cm], repeat_rows=1),
        Spacer(1, 8),
        _p(styles, "Gambar 1. Kerangka Strategi Risiko dan Monitoring LMR", "Small"),
        _table([
            ["Sasaran Korporat", "Profil Risiko", "Monte Carlo", "Mitigasi & Monitoring"],
            [
                _p(styles, "Menjaga sasaran dan target perusahaan.", "Small"),
                _p(styles, "Mengidentifikasi risiko utama dan level residual.", "Small"),
                _p(styles, "Memproyeksikan distribusi output dan probabilitas target.", "Small"),
                _p(styles, "Menetapkan fokus mitigasi dan tindak lanjut manajemen.", "Small"),
            ],
        ], widths=[4.7 * cm, 4.7 * cm, 4.7 * cm, 4.7 * cm], repeat_rows=1),
        Spacer(1, 8),
        _p(styles, "1.2 Arah dan Fokus Pengelolaan Risiko", "Section"),
        _p(
            styles,
            "Fokus pengelolaan risiko periode ini diarahkan pada risiko residual tinggi, risiko yang membutuhkan mitigasi "
            "tambahan, serta risiko dengan probabilitas pencapaian target yang perlu dipantau melalui hasil simulasi.",
        ),
        PageBreak(),
        _p(styles, "BAB II PEMANTAUAN PROFIL RISIKO", "ReportTitle"),
        _p(styles, "2.1 Ringkasan Pemantauan Profil Risiko", "Section"),
        _p(
            styles,
            "Pemantauan profil risiko dilakukan untuk melihat posisi risiko inheren dan residual, status risiko, "
            "ketersediaan hasil Monte Carlo, serta kebutuhan mitigasi tambahan pada periode laporan.",
        ),
        Spacer(1, 6),
        _p(styles, "Tabel 2. Ringkasan Pemantauan Profil Risiko", "Small"),
    ]

    high_items = [item for item in items if _safe_float(item.residual_level_risiko) >= 15]
    monte_carlo_results = [result for result in results_by_item.values() if result]
    story.append(_table([
        ["Parameter", "Nilai", "Parameter", "Nilai"],
        ["Jumlah Risiko Korporat", _fmt_int(len(items)), "Risiko Residual Tinggi", _fmt_int(len(high_items))],
        ["Hasil Monte Carlo Tersedia", _fmt_int(len(monte_carlo_results)), "Butuh Mitigasi", _fmt_int(sum(1 for r in monte_carlo_results if r.requires_mitigation))],
    ], widths=[4.0 * cm, 5.4 * cm, 4.0 * cm, 5.4 * cm], repeat_rows=1))
    story.append(Spacer(1, 8))
    story.append(_p(styles, "2.2 Daftar Profil Risiko Korporat", "Section"))
    story.append(_p(styles, "Tabel 3. Daftar Profil Risiko Korporat", "Small"))

    profile_rows = [[
        "No", "Peristiwa Risiko", "Kategori", "T3", "Inheren", "Residual", "Status", "Monte Carlo"
    ]]
    for item in items:
        result = results_by_item.get(item.pk)
        mc_text = "-"
        if result:
            mc_text = (
                f"{result.forecast_periode}; score {_fmt_num(result.composite_score, 2)}; "
                f"P80 {_fmt_num(result.p80_score, 2)}; {result.risk_status or result.status_hasil or '-'}"
            )
        profile_rows.append([
            str(item.no_risiko or item.no_item or "-"),
            _p(styles, item.peristiwa_risiko, "Small"),
            _p(styles, item.kategori_risiko or "-", "Small"),
            _p(styles, item.taksonomi_t3 or "-", "Small"),
            f"D:{_fmt_int(item.dampak)} K:{_fmt_int(item.kemungkinan)} L:{_fmt_int(item.level_risiko)}",
            f"D:{_fmt_int(item.residual_dampak)} K:{_fmt_int(item.residual_kemungkinan)} L:{_fmt_int(item.residual_level_risiko)}",
            item.status or "-",
            _p(styles, mc_text, "Small"),
        ])
    if len(profile_rows) == 1:
        profile_rows.append(["-", "Belum ada item risiko.", "-", "-", "-", "-", "-", "-"])

    story.append(_table(
        profile_rows,
        widths=[0.7*cm, 4.9*cm, 2.1*cm, 2.1*cm, 1.6*cm, 1.6*cm, 1.5*cm, 4.3*cm],
        repeat_rows=1,
    ))

    story.append(PageBreak())
    story.append(_p(styles, "2.3 Pemantauan Hasil Monte Carlo", "Section"))
    story.append(_p(
        styles,
        "Hasil Monte Carlo digunakan sebagai alat bantu pemantauan probabilitas pencapaian target, potensi deviasi, "
        "dan prioritas tindak lanjut terhadap risiko korporat yang dimodelkan.",
    ))
    story.append(Spacer(1, 6))
    story.append(_p(styles, "Tabel 4. Ringkasan Hasil Monte Carlo", "Small"))
    mc_rows = [[
        "No", "Item Risiko", "Periode", "Distribusi", "Forecast", "Target", "Prob. Tercapai", "VaR/P95", "Status"
    ]]
    for item in items:
        result = results_by_item.get(item.pk)
        if not result:
            mc_rows.append([
                str(item.no_risiko or item.no_item or "-"),
                _p(styles, item.peristiwa_risiko, "Small"),
                "-", "-", "-", "-", "-", "-", "Belum ada hasil",
            ])
            continue
        mc_rows.append([
            str(item.no_risiko or item.no_item or "-"),
            _p(styles, item.peristiwa_risiko, "Small"),
            str(result.forecast_periode),
            _distribution_label(result.distribution_type),
            _fmt_num(result.forecast_total or result.baseline_value, 2),
            _fmt_num(result.target_value, 2),
            _fmt_pct(result.probability_achieve_target),
            _fmt_num(result.var_95, 2),
            _p(styles, result.target_status or result.risk_status or result.status_hasil or "-", "Small"),
        ])
    story.append(_table(
        mc_rows,
        widths=[0.7*cm, 4.4*cm, 2.4*cm, 2.3*cm, 1.8*cm, 1.8*cm, 2.0*cm, 1.7*cm, 1.7*cm],
        repeat_rows=1,
    ))

    story.append(PageBreak())
    story.append(_p(styles, "BAB III PEMANTAUAN RENCANA PERLAKUAN RISIKO", "ReportTitle"))
    story.append(_p(styles, "3.1 Ringkasan Rencana Perlakuan Risiko", "Section"))
    story.append(_p(
        styles,
        "Pemantauan rencana perlakuan risiko dilakukan untuk memastikan mitigasi yang telah ditetapkan berjalan sesuai "
        "prioritas, memiliki PIC yang jelas, serta menghasilkan output pengendalian yang dapat ditindaklanjuti.",
    ))
    story.append(Spacer(1, 6))
    story.append(_p(styles, "Tabel 5. Rencana Perlakuan Risiko Korporat", "Small"))
    treatment_rows = [["No", "Risiko", "Rencana Perlakuan", "Output", "PIC", "Status", "Timeline"]]
    for item in items:
        plans = list(item.rencana_perlakuan_items.all())
        if not plans:
            treatment_rows.append([
                str(item.no_risiko or item.no_item or "-"),
                _p(styles, item.peristiwa_risiko, "Small"),
                "-", "-", "-", "Belum ada rencana", "-",
            ])
            continue
        for plan in plans:
            timeline = ", ".join(
                str(month)
                for month in range(1, 13)
                if getattr(plan, f"timeline_{month}", 0)
            )
            treatment_rows.append([
                str(item.no_risiko or item.no_item or "-"),
                _p(styles, item.peristiwa_risiko, "Small"),
                _p(styles, plan.rencana_perlakuan_risiko or "-", "Small"),
                _p(styles, plan.output_perlakuan_risiko or "-", "Small"),
                _p(styles, plan.pic or "-", "Small"),
                plan.status or "-",
                timeline or "-",
            ])
    story.append(_table(
        treatment_rows,
        widths=[0.7*cm, 3.5*cm, 4.5*cm, 3.8*cm, 2.8*cm, 2.0*cm, 1.5*cm],
        repeat_rows=1,
    ))
    story.append(Spacer(1, 8))
    story.append(_p(styles, "3.2 Status dan Tindak Lanjut Perlakuan Risiko", "Section"))
    story.append(_p(
        styles,
        "Rencana perlakuan dengan status belum berjalan, terlambat, atau belum memiliki output perlu menjadi prioritas "
        "pembahasan manajemen pada periode berikutnya. Risiko residual tinggi perlu dikaitkan kembali dengan kecukupan "
        "perlakuan dan efektivitas existing control.",
    ))

    story.append(PageBreak())
    story.append(_p(styles, "BAB IV PEMANTAUAN KRI DAN KEJADIAN RISIKO", "ReportTitle"))
    story.append(_p(styles, "4.1 Pemantauan Key Risk Indicator", "Section"))
    story.append(_p(
        styles,
        "Key Risk Indicator digunakan sebagai indikator peringatan dini untuk membaca perubahan eksposur risiko. "
        "Pemantauan KRI perlu dibandingkan dengan threshold aman, hati-hati, dan bahaya yang telah ditetapkan.",
    ))
    story.append(Spacer(1, 6))
    story.append(_p(styles, "Tabel 6. Pemantauan KRI dan Sumber Risiko", "Small"))
    kri_rows = [["No", "Risiko", "Pemilik / Sumber", "KRI", "Threshold", "Catatan Pemantauan"]]
    for item in items:
        causes = list(item.daftar_penyebab.all())
        sources = list(item.sumber_risiko.all())
        if causes:
            for cause in causes:
                threshold = " / ".join(filter(None, [
                    cause.threshold_aman,
                    cause.threshold_hati_hati,
                    cause.threshold_bahaya,
                ]))
                owner = cause.pemilik_risiko.name if cause.pemilik_risiko_id else "-"
                kri_rows.append([
                    str(item.no_risiko or item.no_item or "-"),
                    _p(styles, item.peristiwa_risiko, "Small"),
                    _p(styles, owner, "Small"),
                    _p(styles, cause.key_risk_indicators or "-", "Small"),
                    _p(styles, threshold or "-", "Small"),
                    _p(styles, cause.penyebab_risiko or "-", "Small"),
                ])
        elif sources:
            for source in sources:
                unit = getattr(getattr(source.reassessment_item, "summary", None), "unit_bisnis", None)
                kri_rows.append([
                    str(item.no_risiko or item.no_item or "-"),
                    _p(styles, item.peristiwa_risiko, "Small"),
                    _p(styles, unit.name if unit else "-", "Small"),
                    "-",
                    "-",
                    _p(styles, source.penyebab_risiko or source.keterangan or "-", "Small"),
                ])
        else:
            kri_rows.append([
                str(item.no_risiko or item.no_item or "-"),
                _p(styles, item.peristiwa_risiko, "Small"),
                "-", "-", "-", "Belum ada KRI/sumber risiko tercatat.",
            ])
    story.append(_table(
        kri_rows,
        widths=[0.7*cm, 4.2*cm, 3.0*cm, 3.6*cm, 3.0*cm, 4.3*cm],
        repeat_rows=1,
    ))
    story.append(Spacer(1, 8))
    story.append(_p(styles, "4.2 Sumber Risiko dan Kejadian yang Perlu Dipantau", "Section"))
    story.append(_p(
        styles,
        "Setiap perubahan pada sumber risiko, KRI yang memasuki threshold hati-hati/bahaya, dan kejadian yang menimbulkan "
        "kerugian perlu didokumentasikan sebagai bahan pembaruan profil risiko dan penyesuaian perlakuan risiko.",
    ))

    story.append(PageBreak())
    story.append(_p(styles, "BAB V PENUTUP", "ReportTitle"))
    story.append(_p(styles, "5.1 Kesimpulan", "Section"))
    conclusion = (
        f"Pada periode {report_period}, terdapat {len(items)} risiko korporat yang dipantau, "
        f"{len(high_items)} risiko residual tinggi, dan {len(monte_carlo_results)} hasil Monte Carlo yang tersedia. "
        f"Sebanyak {sum(1 for r in monte_carlo_results if r.requires_mitigation)} risiko membutuhkan perhatian mitigasi tambahan."
    )
    story.append(_p(styles, conclusion))
    story.append(Spacer(1, 8))
    story.append(_p(styles, "5.2 Rekomendasi dan Tindak Lanjut", "Section"))
    story.append(_p(styles, "Tabel 7. Ringkasan Tindak Lanjut Manajemen", "Small"))
    follow_up_rows = [
        ["No", "Area Tindak Lanjut", "Rekomendasi", "Prioritas"],
        ["1", "Profil Risiko", "Review risiko residual tinggi dan validasi kecukupan mitigasi.", "Tinggi"],
        ["2", "Monte Carlo", "Update histori metric dan generate ulang simulasi setelah data aktual terbaru tersedia.", "Sedang"],
        ["3", "Rencana Perlakuan", "Tindak lanjuti rencana yang belum memiliki output, PIC, atau status yang jelas.", "Tinggi"],
        ["4", "KRI / Loss Event", "Catat perubahan KRI dan kejadian risiko sebagai dasar pembaruan profil risiko.", "Sedang"],
    ]
    story.append(_table(
        follow_up_rows,
        widths=[0.8*cm, 4.0*cm, 11.5*cm, 2.5*cm],
        repeat_rows=1,
    ))
    story.append(Spacer(1, 8))
    story.append(_p(styles, "Catatan", "Section"))
    story.append(_p(
        styles,
        "Laporan LMR triwulanan ini menggabungkan profil risiko korporat dengan hasil Multi Metric Monte Carlo "
        "terakhir pada periode triwulan yang dipilih. Jika suatu item belum memiliki hasil simulasi pada periode "
        "tersebut, item tetap ditampilkan agar gap data terlihat dalam laporan."
    ))

    doc.build(
        story,
        onFirstPage=lambda c, d: _lmr_header_footer(c, d, printed_at),
        onLaterPages=lambda c, d: _lmr_header_footer(c, d, printed_at),
    )
    pdf = buffer.getvalue()
    buffer.close()
    return pdf
