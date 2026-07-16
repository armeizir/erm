from decimal import Decimal
from io import BytesIO

from django.utils.html import strip_tags
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A2, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


HEADER_GRAY = colors.HexColor("#808080")
DATA_YELLOW = colors.HexColor("#fff2cc")
NOTE_YELLOW = colors.HexColor("#ffff00")
TITLE_BLUE = colors.HexColor("#1f4e78")
SECTION_BLUE = colors.HexColor("#2f75b5")
GOOD_GREEN = colors.HexColor("#c6efce")
WARN_YELLOW = colors.HexColor("#fff2cc")
DANGER_RED = colors.HexColor("#f4cccc")
ORANGE = colors.HexColor("#fce4d6")


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
            "risk_event__no_risiko",
            "risk_event__no_penyebab_risiko",
            "risk_event__no_item",
            "id",
        )
    )


def _display_number_map(items):
    return {
        item.risk_event_id: item.risk_event.no_risiko or item.risk_event.no_item or index
        for index, item in enumerate(items, start=1)
    }


def _p(styles, text, style="Cell"):
    return Paragraph(_clean(text).replace("\n", "<br/>") or "&nbsp;", styles[style])


def _table(data, widths, repeat_rows=1, extra_style=None):
    table = Table(data, colWidths=widths, repeatRows=repeat_rows, splitByRow=True)
    commands = [
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
    if extra_style:
        commands.extend(extra_style)
    table.setStyle(TableStyle(commands))
    return table


def _section_title(styles, text):
    return [
        Paragraph(text, styles["Section"]),
        Spacer(1, 0.18 * cm),
    ]


def _month_number(report):
    if not report.periode_id or not report.periode.tanggal_mulai:
        return 1
    return report.periode.tanggal_mulai.month


def _quarter_number(report):
    return ((_month_number(report) - 1) // 3) + 1


def _scale_value(value):
    if value in (None, ""):
        return ""
    return getattr(value, "urutan", None) or _clean(value)


def _risk_quarter_value(risk, prefix, quarter, formatter=_label):
    return formatter(getattr(risk, f"{prefix}_q{quarter}", None))


def _risk_level_text(score, level):
    score_text = _clean(score)
    level_text = _clean(level)
    if score_text and level_text:
        return f"{level_text} ({score_text})"
    return level_text or score_text


def _level_color(value):
    text = _clean(value).lower()
    if "sangat tinggi" in text or "very high" in text or "ekstr" in text:
        return DANGER_RED
    if "tinggi" in text or "high" in text:
        return ORANGE
    if "moderat" in text or "moderate" in text or "sedang" in text:
        return NOTE_YELLOW
    if "rendah" in text or "low" in text:
        return GOOD_GREEN
    return DATA_YELLOW


def _progress_color(value):
    try:
        number = Decimal(value or 0)
    except Exception:
        return DATA_YELLOW
    if number >= 100:
        return GOOD_GREEN
    if number >= 50:
        return WARN_YELLOW
    return DANGER_RED


def _timeline_mark(value):
    try:
        return "1" if int(value or 0) else ""
    except Exception:
        return ""


def _cover(styles, report):
    return [
        Spacer(1, 5 * cm),
        Paragraph("LAPORAN REALISASI MANAJEMEN RISIKO", styles["CoverTitle"]),
        Spacer(1, 0.45 * cm),
        Paragraph(report.reassessment.judul, styles["CoverSub"]),
        Paragraph(report.periode.nama_periode, styles["CoverSub"]),
        Spacer(1, 1.2 * cm),
        Paragraph(f"Unit/Bidang: {report.reassessment.unit_bisnis.name}", styles["CoverSub"]),
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
    quarter = _quarter_number(report)
    month_label = report.periode.nama_periode
    rows = [
        [
            _p(styles, "Petunjuk", "NoteHeader"),
            _p(styles, "Diisi dengan nomor urutan risiko", "Note"),
            _p(styles, "Nama peristiwa risiko harus sama persis dengan profil risiko", "Note"),
            _p(styles, "Diisi penjelasan asumsi/pendekatan dampak", "Note"),
            _p(styles, "Target nilai dampak, probabilitas, eksposur, skor dan level per triwulan", "Note"),
            "",
            "",
            "",
            "",
            "",
            "",
            _p(styles, f"Realisasi bulan {month_label}", "Note"),
            "",
            "",
            "",
            "",
            "",
            "",
        ],
        [
            _p(styles, "No. Risiko", "Header"),
            _p(styles, "Peristiwa Risiko", "Header"),
            _p(styles, "Jenis Risiko", "Header"),
            _p(styles, "Asumsi Perhitungan Dampak", "Header"),
            _p(styles, f"Target TW {quarter}", "Header"),
            "",
            "",
            "",
            "",
            "",
            "",
            _p(styles, "Realisasi", "Header"),
            "",
            "",
            "",
            "",
            "",
            _p(styles, "Efektivitas Perlakuan", "Header"),
        ],
        [
            "",
            "",
            "",
            "",
            _p(styles, "Nilai Dampak", "Header"),
            _p(styles, "Skala Dampak", "Header"),
            _p(styles, "Nilai Probabilitas", "Header"),
            _p(styles, "Skala Probabilitas", "Header"),
            _p(styles, "Eksposur Risiko", "Header"),
            _p(styles, "Skor", "Header"),
            _p(styles, "Level", "Header"),
            _p(styles, "Nilai Dampak", "Header"),
            _p(styles, "Skala Dampak", "Header"),
            _p(styles, "Nilai Probabilitas", "Header"),
            _p(styles, "Skala Probabilitas", "Header"),
            _p(styles, "Eksposur Risiko", "Header"),
            _p(styles, "Skor", "Header"),
            _p(styles, "Level", "Header"),
            "",
        ],
    ]
    for item in items:
        risk = item.risk_event
        target_level = _risk_level_text(
            getattr(risk, f"skala_risiko_q{quarter}", ""),
            getattr(risk, f"level_nilai_risiko_q{quarter}", ""),
        )
        rows.append(
            [
                _p(styles, number_by_risk.get(risk.id, risk.no_item), "Center"),
                _p(styles, risk.peristiwa_risiko),
                _p(styles, "Kualitatif"),
                _p(styles, item.realisasi_asumsi_dampak or risk.asumsi_perhitungan_dampak),
                _p(styles, _risk_quarter_value(risk, "nilai_dampak", quarter, _money), "Right"),
                _p(styles, _scale_value(getattr(risk, f"skala_dampak_q{quarter}", None)), "Center"),
                _p(styles, _risk_quarter_value(risk, "nilai_probabilitas", quarter, _percent), "Center"),
                _p(styles, _scale_value(getattr(risk, f"skala_probabilitas_q{quarter}", None)), "Center"),
                _p(styles, _risk_quarter_value(risk, "eksposur_risiko", quarter, _money), "Right"),
                _p(styles, getattr(risk, f"skala_risiko_q{quarter}", "") or "", "Center"),
                _p(styles, target_level, "Center"),
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
    widths = [1.2, 4.8, 1.7, 5.4, 2.1, 1.3, 1.7, 1.4, 2.2, 1, 1.9, 2.1, 1.3, 1.7, 1.4, 2.2, 1, 1.9, 2.2]
    style = [
        ("SPAN", (4, 0), (10, 0)),
        ("SPAN", (11, 0), (17, 0)),
        ("SPAN", (4, 1), (10, 1)),
        ("SPAN", (11, 1), (17, 1)),
        ("SPAN", (0, 1), (0, 2)),
        ("SPAN", (1, 1), (1, 2)),
        ("SPAN", (2, 1), (2, 2)),
        ("SPAN", (3, 1), (3, 2)),
        ("SPAN", (18, 1), (18, 2)),
        ("BACKGROUND", (0, 0), (0, 0), NOTE_YELLOW),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("BACKGROUND", (1, 0), (-1, 0), colors.white),
        ("BACKGROUND", (4, 1), (10, 2), SECTION_BLUE),
        ("BACKGROUND", (11, 1), (17, 2), SECTION_BLUE),
    ]
    for index, item in enumerate(items, start=3):
        risk = item.risk_event
        style.append(("BACKGROUND", (10, index), (10, index), _level_color(getattr(risk, f"level_nilai_risiko_q{quarter}", ""))))
        style.append(("BACKGROUND", (17, index), (17, index), _level_color(item.realisasi_level_risiko)))
    return _section_title(styles, "III.A. FORMAT TABEL REALISASI RISIKO RESIDUAL BULANAN") + [
        _table(rows, [w * cm for w in widths], repeat_rows=3, extra_style=style),
        PageBreak(),
    ]


def _iiib(styles, report, items, number_by_risk):
    unit = _unit_code(report)
    rows = [
        [
            _p(styles, "Notes", "NoteHeader"),
            _p(styles, "Nomor risiko harus konsisten pada saat pelaporan", "Note"),
            _p(styles, "Risiko harus diidentifikasi dengan tepat dan sesuai profil risiko", "Note"),
            "",
            _p(styles, "Setiap penyebab kejadian diberikan unique ID", "Note"),
            "",
            _p(styles, "Rencana perlakuan dan realisasi diisi per penyebab risiko", "Note"),
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ],
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
            _p(styles, "Timeline RKAP", "Header"),
            "",
            "",
            "",
            "",
            "",
        ],
        [
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            _p(styles, "Jan", "Header"),
            _p(styles, "Feb", "Header"),
            _p(styles, "Mar", "Header"),
            _p(styles, "Apr", "Header"),
            _p(styles, "Mei", "Header"),
            _p(styles, "Jun", "Header"),
        ],
    ]
    for item in items:
        risk = item.risk_event
        risk_no = number_by_risk.get(risk.id, risk.no_risiko or risk.no_item)
        cause = (risk.no_penyebab_risiko or "").lower()
        code = risk.kode_penyebab_risiko or (f"{unit}-{risk_no}-{cause}" if cause else f"{unit}-{risk_no}")
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
                _p(styles, _timeline_mark(risk.timeline_1), "Center"),
                _p(styles, _timeline_mark(risk.timeline_2), "Center"),
                _p(styles, _timeline_mark(risk.timeline_3), "Center"),
                _p(styles, _timeline_mark(risk.timeline_4), "Center"),
                _p(styles, _timeline_mark(risk.timeline_5), "Center"),
                _p(styles, _timeline_mark(risk.timeline_6), "Center"),
            ]
        )
    widths = [1.1, 4, 4.4, 1.3, 2.2, 3.8, 4, 3.4, 1.9, 3.8, 3.2, 1.4, 1.8, 1.5, 1.4, 2.6, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8]
    style = [
        ("SPAN", (1, 0), (2, 0)),
        ("SPAN", (4, 0), (5, 0)),
        ("SPAN", (6, 0), (15, 0)),
        ("SPAN", (16, 1), (21, 1)),
        ("SPAN", (0, 1), (0, 2)),
        ("SPAN", (1, 1), (1, 2)),
        ("SPAN", (2, 1), (2, 2)),
        ("SPAN", (3, 1), (3, 2)),
        ("SPAN", (4, 1), (4, 2)),
        ("SPAN", (5, 1), (5, 2)),
        ("SPAN", (6, 1), (6, 2)),
        ("SPAN", (7, 1), (7, 2)),
        ("SPAN", (8, 1), (8, 2)),
        ("SPAN", (9, 1), (9, 2)),
        ("SPAN", (10, 1), (10, 2)),
        ("SPAN", (11, 1), (11, 2)),
        ("SPAN", (12, 1), (12, 2)),
        ("SPAN", (13, 1), (13, 2)),
        ("SPAN", (14, 1), (14, 2)),
        ("SPAN", (15, 1), (15, 2)),
        ("BACKGROUND", (0, 0), (0, 0), NOTE_YELLOW),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("BACKGROUND", (1, 0), (-1, 0), colors.white),
        ("BACKGROUND", (16, 1), (21, 2), SECTION_BLUE),
    ]
    for index, item in enumerate(items, start=3):
        style.append(("BACKGROUND", (14, index), (14, index), _progress_color(item.progress_pelaksanaan_percent)))
    return _section_title(styles, "III.B. FORMAT TABEL REALISASI PELAKSANAAN PERLAKUAN RISIKO DAN BIAYA") + [
        _table(rows, [w * cm for w in widths], repeat_rows=3, extra_style=style),
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
    styles.add(ParagraphStyle(name="CoverTitle", parent=styles["Title"], fontSize=24, leading=30, alignment=TA_CENTER, textColor=TITLE_BLUE, spaceAfter=12, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="CoverSub", parent=styles["Normal"], fontSize=14, leading=18, alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], fontSize=12, leading=15, textColor=colors.white, backColor=TITLE_BLUE, alignment=TA_LEFT, leftIndent=4, spaceBefore=4, spaceAfter=4))
    styles.add(ParagraphStyle(name="Header", parent=styles["Normal"], fontSize=5.3, leading=6.1, alignment=TA_CENTER, textColor=colors.white, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="NoteHeader", parent=styles["Header"], textColor=colors.black, fontName="Helvetica-BoldOblique"))
    styles.add(ParagraphStyle(name="Note", parent=styles["Normal"], fontSize=4.7, leading=5.4, alignment=TA_LEFT, textColor=colors.blue, fontName="Helvetica-Oblique"))
    styles.add(ParagraphStyle(name="Cell", parent=styles["Normal"], fontSize=4.9, leading=5.7, alignment=TA_LEFT))
    styles.add(ParagraphStyle(name="Center", parent=styles["Cell"], alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="Right", parent=styles["Cell"], alignment=2))
    return styles


def render_monthly_risk_report_pdf(report):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A2),
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
