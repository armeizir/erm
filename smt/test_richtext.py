from django.test import SimpleTestCase
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.enums import TA_JUSTIFY
from .forms import DocumentForm, RichTextWidget
from .richtext import clean_value, editor_html, pdf_flowables


class RichTextTests(SimpleTestCase):
    def test_legacy_text_keeps_literal_characters_and_newlines(self):
        self.assertEqual(editor_html('Lingkup <PDF> & Data\n2.1. Penilaian'),
                         '<p>Lingkup &lt;PDF&gt; &amp; Data<br>2.1. Penilaian</p>')
        self.assertEqual(clean_value('Data <PDF>'), 'Data <PDF>')

    def test_sanitizes_active_content_and_keeps_supported_formats(self):
        raw = ('<p onclick="alert(1)" style="text-align:justify;color:red">'
               '<strong>Aman</strong><script>alert(1)</script>'
               '<img src="https://example.test/private" onerror="alert(2)">'
               '<a href="javascript:alert(3)">Tautan</a></p>')
        self.assertEqual(clean_value(raw),
                         '<p style="text-align:justify"><strong>Aman</strong>Tautan</p>')
        self.assertEqual(clean_value(clean_value(raw)), clean_value(raw))

    def test_widget_preserves_fallback_and_escapes_html_attribute(self):
        html = RichTextWidget().render('tujuan', '<p><b>Tujuan</b></p>')
        self.assertIn('data-editor-html=', html)
        self.assertIn('&lt;p&gt;&lt;b&gt;Tujuan&lt;/b&gt;&lt;/p&gt;', html)
        self.assertNotIn('<script', html)

    def test_form_cleans_rich_fields(self):
        form = DocumentForm(data={'tujuan': '<p>Tujuan<script>bad()</script></p>'})
        form.is_valid()
        self.assertEqual(form.cleaned_data['tujuan'], '<p>Tujuan</p>')

    def test_pdf_preserves_alignment_inline_format_and_nested_lists(self):
        flow = pdf_flowables('<p style="text-align:justify"><b>Lingkup</b> &amp; tujuan</p>'
                             '<ol start="3"><li>Pertama<ul><li>Detail</li></ul></li>'
                             '<li>Kedua</li></ol>', getSampleStyleSheet()['BodyText'])
        self.assertEqual(flow[0].style.alignment, TA_JUSTIFY)
        self.assertIn('<b>Lingkup</b>', flow[0].text)
        self.assertEqual([p.bulletText for p in flow[1:]], ['3.', '\u2022', '4.'])
        self.assertGreater(flow[2].style.leftIndent, flow[1].style.leftIndent)
        self.assertEqual(flow[3].getPlainText(), 'Kedua')
