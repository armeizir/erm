"""PDF PI/IK dengan susunan dokumen SMT; lampiran sumber tetap terpisah."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate, Frame, NextPageTemplate, PageBreak, PageTemplate,
    Image, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents
from .richtext import pdf_flowables


COMPANY = 'PT. PELAYANAN LISTRIK NASIONAL BATAM'


def _roman(number):
    result = ''
    for value, digit in [(1000, 'm'), (900, 'cm'), (500, 'd'), (400, 'cd'),
                         (100, 'c'), (90, 'xc'), (50, 'l'), (40, 'xl'),
                         (10, 'x'), (9, 'ix'), (5, 'v'), (4, 'iv'), (1, 'i')]:
        count, number = divmod(number, value)
        result += digit * count
    return result


class _SMTDocTemplate(BaseDocTemplate):
    def beforeDocument(self):
        # multiBuild runs this again while resolving the table of contents.
        self.body_start = None
        self.front_start = None

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name == 'SMTHeading':
            page = (self.page - self.body_start + 1 if self.body_start is not None
                    else -(self.page - self.front_start + 1))
            self.notify('TOCEntry', (0, flowable.getPlainText(), page))


def build_document_pdf(document):
    output = BytesIO()
    styles = getSampleStyleSheet()
    for name, size, leading, alignment, font in [
        ('SMTTitle', 18, 25, TA_CENTER, 'Helvetica-Bold'),
        ('SMTBody', 11, 16, TA_LEFT, 'Helvetica'),
        ('SMTCenter', 11, 16, TA_CENTER, 'Helvetica'),
        ('SMTHeading', 12, 18, TA_LEFT, 'Helvetica-Bold'),
        ('SMTPageTitle', 13, 19, TA_CENTER, 'Helvetica-Bold'),
        ('SMTSmall', 9, 12, TA_LEFT, 'Helvetica'),
    ]:
        styles.add(ParagraphStyle(name=name, fontName=font, fontSize=size,
                                  leading=leading, alignment=alignment,
                                  spaceAfter=8, splitLongWords=True,
                                  keepWithNext=name == 'SMTHeading'))

    def p(value, style='SMTBody'):
        return Paragraph(escape(str(value or '-')).replace('\n', '<br/>'), styles[style])

    logo = Path(__file__).resolve().parent.parent / 'static/risk/brand/pln-batam.jpg'

    def brand(width):
        if logo.is_file():
            image = Image(str(logo))
            image.drawHeight *= width / image.drawWidth
            image.drawWidth = width
            return image
        return p('PLN BATAM', 'SMTCenter')

    width, height = A4
    margin = 1.8 * cm
    usable = width - 2 * margin

    def table(rows, widths, heights=None):
        result = Table(rows, colWidths=widths, rowHeights=heights, hAlign='LEFT',
                       repeatRows=1, splitByRow=1)
        result.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), .6, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        return result

    kind = 'PROSEDUR INTEGRASI' if document.jenis == 'PI' else 'INSTRUKSI KERJA'
    date_text = (document.tanggal_berlaku.strftime('%d.%m.%Y')
                 if document.tanggal_berlaku else 'Belum ditetapkan')

    def cover(canvas):
        # Reproduce the orange/grey header artwork from the Word cover's VML.
        def polygon(left, top, box_width, box_height, points, color):
            path = canvas.beginPath()
            for index, (x, y) in enumerate(points):
                px = -31.8 + (left + x * box_width) * 225.95 / 34076
                py = height - (-9.35 + (top + y * box_height) * 196.5 / 29639)
                (path.moveTo if index == 0 else path.lineTo)(px, py)
            path.close()
            canvas.setFillColor(colors.HexColor(color))
            canvas.drawPath(path, fill=1, stroke=0)

        for left, top, w, h, xmax, xleft, xright, color in [
            (0, 8382, 23980, 21257, 12544, 5905, 6697, '#d9d9d9'),
            (10096, 0, 23980, 21257, 12544, 5905, 6697, '#f79646'),
            (10858, 3429, 11751, 10633, 11367, 5513, 5991, '#7f7f7f'),
        ]:
            polygon(left, top, w, h,
                    [(0, 1), (xleft/xmax, 0), (1, 0), (xright/xmax, 1)], color)

        assets = Path(__file__).resolve().parent.parent / 'static/smt/cover'
        image = brand(4.8*cm)
        image.wrap(4.8*cm, 3*cm)
        image.drawOn(canvas, width - 6.2*cm, height - 3.1*cm)

        assets = Path(__file__).resolve().parent.parent / 'static/smt/cover'
        names = ['smk3.png', 'smp.png', 'iso45001.jpg', 'iso14001.jpeg',
                 'iso9001.png', 'iso37001.png']
        cell_width = usable / len(names)
        for index, name in enumerate(names):
            image = Image(str(assets / name))
            scale = min((cell_width-.3*cm)/image.drawWidth, 1.9*cm/image.drawHeight)
            image.drawWidth *= scale
            image.drawHeight *= scale
            image.drawOn(canvas, margin + index*cell_width +
                         (cell_width-image.drawWidth)/2, height - 8.5*cm +
                         (1.9*cm-image.drawHeight)/2)

        def text(value, top, style, x=margin, available=usable):
            paragraph = Paragraph(escape(str(value)).replace('\n', '<br/>'), style)
            _, h = paragraph.wrap(available, height)
            paragraph.drawOn(canvas, x, height - top - h)
            return h

        title_style = ParagraphStyle('CoverTitle', fontName='Helvetica-Bold',
                                     fontSize=18, leading=23, alignment=TA_CENTER)
        text('SISTEM MANAJEMEN TERINTEGRASI', 9.2*cm, title_style)
        standard_style = ParagraphStyle('CoverStandards', fontName='Helvetica',
                                        fontSize=8.5, leading=13, alignment=TA_CENTER)
        text('SMK3 (PP No. 50 Tahun 2012 & ISO 45001:2018); '
             'SMP (PERKAPOLRI No. 24 Tahun 2007);\n'
             'SML (ISO 14001:2015); SMM (ISO 9001:2015); SMAP (ISO 37001:2016)',
             10.2*cm, standard_style)
        kind_style = ParagraphStyle('CoverKind', fontName='Helvetica-Bold',
                                    fontSize=72, leading=80,
                                    textColor=colors.HexColor('#ff9900'))
        text(document.jenis, 12.0*cm, kind_style, margin+1.5*cm, 4.2*cm)
        label_style = ParagraphStyle('CoverKindLabel', fontName='Helvetica-Bold',
                                     fontSize=18, leading=25)
        text('Prosedur\nIntegrasi' if document.jenis == 'PI' else 'Instruksi\nKerja',
             12.5*cm, label_style, margin+6*cm, usable-6*cm)
        # Long document names must remain inside the fixed cover title area.
        for size in (18, 17, 16, 15, 14, 13):
            title_style.fontSize, title_style.leading = size, size*1.3
            paragraph = Paragraph(escape(document.judul.upper()), title_style)
            if paragraph.wrap(usable, height)[1] <= 3.1*cm:
                break
        text(document.judul.upper(), 16.2*cm, title_style)
        metadata_style = ParagraphStyle('CoverMetadata', fontName='Helvetica',
                                        fontSize=11, leading=16)
        metadata = Table([[Paragraph(label, metadata_style),
                           Paragraph(':', metadata_style),
                           Paragraph(escape(str(value)), metadata_style)]
                          for label, value in [('Nomor Dokumen', document.nomor),
                                               ('Revisi', document.revisi),
                                               ('Tanggal', date_text)]],
                         colWidths=[3.7*cm, .4*cm, 8.2*cm])
        metadata.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                      ('LEFTPADDING', (0, 0), (-1, -1), 0),
                                      ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
        _, h = metadata.wrap(usable, height)
        metadata.drawOn(canvas, margin+2.2*cm, height-20.3*cm-h)
        company_style = ParagraphStyle('CoverCompany', fontName='Helvetica-Bold',
                                       fontSize=14, leading=19, alignment=TA_CENTER)
        text(COMPANY, 26.3*cm, company_style)

    def page_header(canvas, doc):
        canvas.saveState()
        if doc.pageTemplate.id == 'body' and doc.body_start is None:
            doc.body_start = doc.page
        if doc.pageTemplate.id == 'front' and doc.front_start is None:
            doc.front_start = doc.page
        if doc.pageTemplate.id == 'cover':
            cover(canvas)
        else:
            grey = colors.HexColor('#808080')
            metadata_style = ParagraphStyle('HeaderMetadata', fontName='Helvetica',
                                            fontSize=11, leading=14, textColor=grey)
            metadata_text = (escape(str(document.nomor)) + '<br/>Rev : '
                             + escape(str(document.revisi)))
            for size in (11, 10, 9, 8, 7):
                metadata_style.fontSize = size
                metadata_style.leading = size * 1.25
                metadata = Paragraph(metadata_text, metadata_style)
                _, metadata_height = metadata.wrap(usable - 4.5*cm, height)
                if metadata_height <= 1.6*cm:
                    break
            metadata.drawOn(canvas, margin, height - .65*cm - metadata_height)
            image = brand(3.7*cm)
            image.wrap(3.7*cm, 2*cm)
            image.drawOn(canvas, width - margin - 3.7*cm, height - .4*cm - image.drawHeight)
            title_style = ParagraphStyle('HeaderTitle', fontName='Helvetica-Bold',
                                         fontSize=14, leading=17, alignment=TA_CENTER,
                                         textColor=grey)
            for size in (14, 13, 12, 11, 10, 9):
                title_style.fontSize = size
                title_style.leading = size * 1.2
                title = Paragraph(escape(document.judul.upper()), title_style)
                _, title_height = title.wrap(usable, height)
                if title_height <= 1.1*cm:
                    break
            title.drawOn(canvas, margin, height - 3.35*cm + (.1*cm))
            canvas.setStrokeColor(grey)
            canvas.setLineWidth(2)
            canvas.line(margin, height - 3.5*cm, width - margin, height - 3.5*cm)
            label = (str(doc.page - doc.body_start + 1)
                     if doc.body_start is not None
                     else _roman(doc.page - doc.front_start + 1))
            canvas.setFont('Helvetica', 9)
            canvas.drawCentredString(width/2, .9*cm, label)
        if doc.pageTemplate.id != 'cover':
            canvas.setFont('Helvetica', 8)
            canvas.drawString(margin, .9*cm, document.get_status_display())
        canvas.restoreState()

    pdf = _SMTDocTemplate(output, pagesize=A4, leftMargin=margin,
                          rightMargin=margin, topMargin=4.2*cm,
                          bottomMargin=1.6*cm, title=document.judul,
                          author='PRISMA - PT PLN Batam')
    frame = Frame(margin, 1.6*cm, usable, height - 5.8*cm,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    pdf.addPageTemplates([
        PageTemplate(id=name, frames=[frame], onPage=page_header)
        for name in ('cover', 'front', 'body')
    ])

    story = [Spacer(1, 1), NextPageTemplate('front'), PageBreak(),
              p('LEMBAR PENGESAHAN', 'SMTHeading')]
    for role in ('PENYUSUN', 'VERIFIKASI', 'DISAHKAN OLEH'):
        story += [p(role, 'SMTPageTitle'),
                  table([[p('JABATAN', 'SMTCenter'), p('TANDA TANGAN', 'SMTCenter')],
                         ['', '']], [usable*.6, usable*.4], [None, 2.3*cm]),
                  Spacer(1, .4*cm)]
    story += [p('Kolom pengesahan diisi oleh pejabat berwenang. Status dokumen: '
                + document.get_status_display() + '.', 'SMTSmall'), PageBreak(),
              p('DAFTAR ISI', 'SMTPageTitle')]
    toc = TableOfContents()
    toc.formatter = lambda page: _roman(-page) if page < 0 else str(page)
    toc.levelStyles = [ParagraphStyle('SMTContents', fontName='Helvetica',
                                      fontSize=10, leading=16, spaceBefore=8)]
    story += [toc, PageBreak(), p('DAFTAR PERUBAHAN DOKUMEN', 'SMTHeading')]
    # The model stores a current revision note, not a structured revision history.
    # Do not turn the sample document's history into this document's history.
    story.append(table([
        [p('REVISI', 'SMTSmall'), p('TANGGAL BERLAKU', 'SMTSmall'),
         p('URAIAN PERUBAHAN', 'SMTSmall')],
        [p(document.revisi), p(date_text),
         p('Catatan revisi disajikan di bawah tabel.', 'SMTSmall')],
    ], [2*cm, 4*cm, usable-6*cm]))
    story.extend(pdf_flowables(document.catatan_revisi or 'Belum ada catatan revisi.', styles['SMTBody']))
    story += [NextPageTemplate('body'), PageBreak()]
    sections = [('TUJUAN', document.tujuan), ('LINGKUP', document.ruang_lingkup),
                ('REFERENSI', document.referensi),
                ('TANGGUNG JAWAB', document.tanggung_jawab),
                ('PROSEDUR DAN LANGKAH KERJA', document.langkah_kerja)]
    for index, (title, value) in enumerate(sections, 1):
        story.append(p(f'{index}. {title}', 'SMTHeading'))
        story.extend(pdf_flowables(value, styles['SMTBody']))
    attachments = list(document.lampiran.all())
    attachment_intro = [p('6. LAMPIRAN', 'SMTHeading'),
                        p('Berkas lampiran, termasuk lembar pengesahan dan bagan alir '
                          'yang diunggah, diunduh terpisah melalui halaman dokumen SMT '
                          'di PRISMA.', 'SMTSmall')]
    items = [p(f'6.{index}. {attachment.nama} ({attachment.get_jenis_display()})')
             for index, attachment in enumerate(attachments, 1)]
    if not items:
        items = [p('Belum ada lampiran.')]
    attachment_intro[1].keepWithNext = True
    story.extend(attachment_intro + items)
    pdf.multiBuild(story)
    return output.getvalue()
