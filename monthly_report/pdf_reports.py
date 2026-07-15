from decimal import Decimal
from io import BytesIO
import string

from django.utils.html import strip_tags
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


HEADER_GRAY = colors.HexColor("#808080")
DATA_YELLOW = colors.HexColor("#fff2cc")
TITLE_BLUE = colors.HexColor("#1f4e78")


def _alpha_index(value):
    text = str(value or "").strip().lower()
    result = 0
    for char in text:
        if char in string.ascii_lowercase:
            result = result * 26 + (ord(char) - 96)
    return result


def _clean(value):
    if value is None:
        return ""
    text = strip_tags(str(value))
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _money(value):
    if value in (None, ""):
        return ""
    try:
        number = Decimal(value)
    except Exception:
        return _clean(value)
    return f"{number:,.0f}".replace(",", ".")


def _percent(value):
    if value in (None, ""):
        return ""
    try:
        number = Decimal(value)
    except Exception:
        return _clean(value)
    return f"{number.normalize()}%"


def _label(value):
    if value in (None, ""):
        return ""
    return _clean(value)


def _unit_code(report):
    name = report.reassessment.unit_bisnis.name if report.reassessment.unit_bisnis_id else ""
    return "".join(str(name).split())


def _ordered_items(report):
    return list(
        report.items.select_related(
            "risk_event",
            "risk_event__summary__unit_bisnis",
            "risk_event__km_item",
            "risk_event__skala_dampak_q1",
            "risk_event__skala_probabilitas_q1",
            "risk_event__skala_dampak_q2",
            "risk_event__skala_probabilitas_q2",
            "realisasi_skala_dampak",
            "realisasi_skala_probabilitas",
        ).order_by(
            "risk_event__no_penyebab_risiko",
            "risk_event__no_item",
            "risk_event__no_risiko",
            "id",
        )
    )


def _display_number_map(items):
    result = {}
    previous = 0
    previous_source = None
    for item in sorted(
        items,
        key=lambda row: (
            _alpha_index(row.risk_event.no_penyebab_risiko),
            row.risk_event.no_item or 0,
            row.risk_event.no_risiko or 0,
            row.pk or 0,
        ),
    ):
        source = item.risk_event.no_item or item.risk_event.no_risiko or previous + 1
        if previous == 0:
            display = source
        elif source == previous_source:
            display = previous
        elif source == previous + 1:
            display = source
        else:
            display = previous + 1
        result[item.risk_event_id] = display
        previous = display
        previous_source = source
    return result


def _p(styles, text, style="Cell"):
    return Paragraph(_clean(text).replace("\n", "<br/>") or "&nbsp;", styles[style])


def _table(data, widths, repeat_rows=1):
    table = Table(data, colWidths=widths, repeatRows=repeat_rows, splitByRow=True)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.45, colors.black),
                ("BACKGROUND", (0, 0), (-1, repeat_rows - 1), HEADER_GRAY),
                ("TEXTCOLOR", (0, 0), (-1, repeat_rows - 1), colors.white),
                ("BACKGROUND", (0, repeat_rows), (-1, -1), DATA_YELLOW),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, repeat_rows - 1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _section_title(styles, text):
    return [
        Paragraph(text, styles["Section"]),
        Spacer(1, 0.25 * cm),
    ]


def _cover(styles, report):
    return [
        Spacer(1, 4 * cm),
        Paragraph("LAPORAN REALISASI MANAJEMEN RISIKO", styles["CoverTitle"]),
        Spacer(1, 0.4 * cm),
        Paragraph(report.reassessment.judul, styles["CoverSub"]),
        Paragraph(report.periode.nama_periode, styles["CoverSub"]),
        Spacer(1, 1 * cm),
        Paragraph(f"Status: {report.get_status_display()}", styles["CoverSub"]),
        PageBreak(),
    ]


def _summary(styles, report, items):
    rows = [
        [_p(styles, "Profil Risiko", "Header"), _p(styles, report.reassessment.judul)],
        [_p(styles, "Bidang / Unit", "Header"), _p(styles, report.reassessment.unit_bisnis.name)],
        [_p(styles, "Bulan Laporan", "Header"), _p(styles, report.periode.nama_periode)],
        [_p(styles, "Total Risiko", "Header"), _p(styles, len(items), "Center")],
        [_p(styles, "Total High", "Header"), _p(styles, report.total_high, "Center")],
        [_p(styles, "Catatan Manajemen", "Header"), _p(styles, report.catatan_manajemen or "-")],
    ]
    table = Table(rows, colWidths=[5 * cm, 31 * cm])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.45, colors.black),
                ("BACKGROUND", (0, 0), (0, -1), HEADER_GRAY),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return _section_title(styles, "RINGKASAN LAPORAN") + [table, PageBreak()]


def _iiia(styles, report, items, number_by_risk):
    rows = [
        [
            _p(styles, "No. Risiko", "Header"),
            _p(styles, "Peristiwa Risiko", "Header"),
            _p(styles, "Jenis Risiko", "Header"),
            _p(styles, "Asumsi Perhitungan Dampak", "Header"),
            _p(styles, "Nilai Dampak", "Header"),
            _p(styles, "Skala Dampak", "Header"),
            _p(styles, "Nilai Probabilitas", "Header"),
            _p(styles, "Skala Probabilitas", "Header"),
            _p(styles, "Eksposur Risiko", "Header"),
            _p(styles, "Skor", "Header"),
            _p(styles, "Level", "Header"),
            _p(styles, "Efektivitas Perlakuan", "Header"),
        ]
    ]
    for item in items:
        risk = item.risk_event
        rows.append(
            [
                _p(styles, number_by_risk.get(risk.id, risk.no_item), "Center"),
                _p(styles, risk.peristiwa_risiko),
                _p(styles, "Kualitatif"),
                _p(styles, item.realisasi_asumsi_dampak or risk.asumsi_perhitungan_dampak),
                _p(styles, _money(item.realisasi_nilai_dampak), "Right"),
                _p(styles, item.realisasi_skala_dampak or "", "Center"),
                _p(styles, _percent(item.realisasi_nilai_probabilitas), "Center"),
                _p(styles, item.realisasi_skala_probabilitas or "", "Center"),
                _p(styles, _money(item.realisasi_eksposur), "Right"),
                _p(styles, item.realisasi_skor_risiko or "", "Center"),
                _p(styles, item.realisasi_level_risiko or "", "Center"),
                _p(styles, item.get_efektivitas_perlakuan_risiko_display() or "", "Center"),
            ]
        )
    widths = [1.5, 5.2, 2, 7.2, 2.8, 2, 2.4, 2.2, 2.8, 1.3, 1.8, 3]
    return _section_title(styles, "III.A. FORMAT TABEL REALISASI RISIKO RESIDUAL BULANAN") + [
        _table(rows, [w * cm for w in widths]),
        PageBreak(),
    ]


def _iiib(styles, report, items, number_by_risk):
    unit = _unit_code(report)
    rows = [
        [
            _p(styles, "No. Risiko", "Header"),
            _p(styles, "Peristiwa Risiko", "Header"),
            _p(styles, "Deskripsi Peristiwa Risiko", "Header"),
            _p(styles, "No. Penyebab Risiko", "Header"),
            _p(styles, "Kode Penyebab Risiko", "Header"),
            _p(styles, "Penyebab Risiko", "Header"),
            _p(styles, "Rencana Perlakuan Risiko", "Header"),
            _p(styles, "Output Perlakuan Risiko", "Header"),
            _p(styles, "Biaya Perlakuan Risiko", "Header"),
            _p(styles, "Realisasi Rencana Perlakuan Risiko", "Header"),
            _p(styles, "Realisasi Output", "Header"),
            _p(styles, "Serapan Biaya", "Header"),
            _p(styles, "PIC", "Header"),
            _p(styles, "Status", "Header"),
            _p(styles, "Progress", "Header"),
            _p(styles, "Realisasi Threshold KRI", "Header"),
        ]
    ]
    for item in items:
        risk = item.risk_event
        risk_no = number_by_risk.get(risk.id, risk.no_item)
        cause = (risk.no_penyebab_risiko or "").lower()
        code = f"{unit}-{risk_no}-{cause}" if cause else f"{unit}-{risk_no}"
        rows.append(
            [
                _p(styles, risk_no, "Center"),
                _p(styles, risk.peristiwa_risiko),
                _p(styles, risk.deskripsi_peristiwa_risiko),
                _p(styles, cause, "Center"),
                _p(styles, code, "Center"),
                _p(styles, risk.penyebab_risiko),
                _p(styles, risk.rencana_perlakuan_risiko),
                _p(styles, risk.output_perlakuan_risiko),
                _p(styles, _money(risk.biaya_perlakuan_risiko), "Right"),
                _p(styles, item.realisasi_rencana_perlakuan),
                _p(styles, item.realisasi_output_perlakuan),
                _p(styles, _percent(item.persentase_serapan_biaya), "Center"),
                _p(styles, item.realisasi_pic),
                _p(styles, item.get_status_rencana_perlakuan_display() or "", "Center"),
                _p(styles, _percent(item.progress_pelaksanaan_percent), "Center"),
                _p(styles, item.realisasi_threshold_kri),
            ]
        )
    widths = [1.2, 4.2, 4.6, 1.5, 2.3, 4.2, 4.3, 3.8, 2.2, 4.1, 3.5, 1.7, 2.1, 1.8, 1.6, 3.2]
    return _section_title(styles, "III.B. FORMAT TABEL REALISASI PELAKSANAAN PERLAKUAN RISIKO DAN BIAYA") + [
        _table(rows, [w * cm for w in widths]),
        PageBreak(),
    ]


def _iiid(styles, report):
    rows = [
        [
            _p(styles, "Jenis Perubahan", "Header"),
            _p(styles, "Peristiwa Risiko yang Terdampak", "Header"),
            _p(styles, "Penjelasan", "Header"),
        ]
    ]
    for change in report.changes.all():
        rows.append(
            [
                _p(styles, change.get_jenis_perubahan_display()),
                _p(styles, change.peristiwa_risiko_terdampak),
                _p(styles, change.penjelasan),
            ]
        )
    if len(rows) == 1:
        rows.append([_p(styles, "-"), _p(styles, "-"), _p(styles, "-")])
    return _section_title(styles, "III.D. IKHTISAR PERUBAHAN PROFIL DAN STRATEGI RISIKO") + [
        _table(rows, [6 * cm, 13 * cm, 17 * cm]),
        PageBreak(),
    ]


def _iiie(styles, report):
    rows = [
        [
            _p(styles, "Nama Kejadian", "Header"),
            _p(styles, "Identifikasi Kejadian", "Header"),
            _p(styles, "Kategori", "Header"),
            _p(styles, "Sumber", "Header"),
            _p(styles, "Penyebab", "Header"),
            _p(styles, "Penanganan", "Header"),
            _p(styles, "Deskripsi Risk Event", "Header"),
            _p(styles, "Nilai Kerugian", "Header"),
        ]
    ]
    for event in report.loss_events.all():
        rows.append(
            [
                _p(styles, event.nama_kejadian),
                _p(styles, event.identifikasi_kejadian),
                _p(styles, event.kategori_kejadian),
                _p(styles, event.get_sumber_penyebab_kejadian_display() or ""),
                _p(styles, event.penyebab_kejadian),
                _p(styles, event.penanganan_saat_kejadian),
                _p(styles, event.deskripsi_kejadian_risk_event),
                _p(styles, _money(event.nilai_kerugian), "Right"),
            ]
        )
    if len(rows) == 1:
        rows.append([_p(styles, "-"), _p(styles, "-"), _p(styles, "-"), _p(styles, "-"), _p(styles, "-"), _p(styles, "-"), _p(styles, "-"), _p(styles, "-")])
    return _section_title(styles, "III.E. CATATAN KEJADIAN KERUGIAN (LOSS EVENT DATABASE)") + [
        _table(rows, [4.2 * cm, 4.8 * cm, 3 * cm, 2 * cm, 4.6 * cm, 5 * cm, 7 * cm, 3 * cm]),
    ]


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CoverTitle", parent=styles["Title"], fontSize=22, leading=28, alignment=TA_CENTER, textColor=TITLE_BLUE, spaceAfter=12))
    styles.add(ParagraphStyle(name="CoverSub", parent=styles["Normal"], fontSize=14, leading=18, alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], fontSize=12, leading=15, textColor=colors.white, backColor=TITLE_BLUE, alignment=TA_LEFT, leftIndent=4, spaceBefore=4, spaceAfter=4))
    styles.add(ParagraphStyle(name="Header", parent=styles["Normal"], fontSize=6, leading=7, alignment=TA_CENTER, textColor=colors.white, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="Cell", parent=styles["Normal"], fontSize=5.5, leading=6.5, alignment=TA_LEFT))
    styles.add(ParagraphStyle(name="Center", parent=styles["Cell"], alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="Right", parent=styles["Cell"], alignment=2))
    return styles


def render_monthly_risk_report_pdf(report):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A3),
        leftMargin=0.7 * cm,
        rightMargin=0.7 * cm,
        topMargin=0.7 * cm,
        bottomMargin=0.7 * cm,
        title=f"Laporan Realisasi Risiko {report}",
    )
    styles = _styles()
    items = _ordered_items(report)
    number_by_risk = _display_number_map(items)
    story = []
    story.extend(_cover(styles, report))
    story.extend(_summary(styles, report, items))
    story.extend(_iiia(styles, report, items, number_by_risk))
    story.extend(_iiib(styles, report, items, number_by_risk))
    story.extend(_iiid(styles, report))
    story.extend(_iiie(styles, report))
    doc.build(story)
    return buffer.getvalue()
