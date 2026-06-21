from __future__ import annotations

import io
from decimal import Decimal, InvalidOperation
from statistics import mean

from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
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

from .models import MonteCarloMetricHistory, RiskMetric


PRIMARY = colors.HexColor("#12345B")
SECONDARY = colors.HexColor("#3B5976")
LIGHT_BG = colors.HexColor("#F3F6FA")
GRID = colors.HexColor("#D9E1EC")
TEXT = colors.HexColor("#1F2937")


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


def _header_footer(canvas, doc, printed_at):
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(PRIMARY)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(doc.leftMargin, height - 1.0 * cm, "ERM PLN Batam | Multi Metric Monte Carlo Result")
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
