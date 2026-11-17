from datetime import date
from io import BytesIO
from unittest.mock import Mock
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, RequestFactory
from django.forms.models import inlineformset_factory
from masterdata.models import OrganizationUnit
from .models import Document, ProsedurIntegrasi, DocumentRevisionEntry
from .revision_history import revision_rows, save_revision_formset
from .revision import create_revision
from .admin import RevisionEntryInline
from riskproject.admin_site import risk_admin_site


class RevisionHistoryTests(TestCase):
    def setUp(self):
        self.unit = OrganizationUnit.objects.create(code='SMT-HISTORY', name='Unit Uji')
        self.doc = Document.objects.create(jenis='PI', nomor='PI-HISTORY', judul='Uji',
            unit_pemilik=self.unit, revisi='06', catatan_revisi='Catatan lama tetap disimpan')

    def entry(self, rev='06', **kwargs):
        return DocumentRevisionEntry.objects.create(document=self.doc, revisi=rev,
            uraian='Uraian revisi '+rev, **kwargs)

    def test_legacy_note_fallback(self):
        self.assertEqual(revision_rows(self.doc), [('06', None, self.doc.catatan_revisi)])

    def test_two_separate_rows_and_current_date(self):
        self.entry('05', urutan=1, tanggal_berlaku=date(2023, 8, 23))
        self.entry('06', urutan=2, tanggal_berlaku=date(2020, 1, 1))
        rows=revision_rows(self.doc)
        self.assertEqual([r[0] for r in rows], ['05', '06'])
        self.assertEqual(rows[0][1], date(2023, 8, 23))
        self.assertIsNone(rows[1][1])
        self.doc.tanggal_berlaku=date(2026, 1, 1)
        self.assertEqual(revision_rows(self.doc)[1][1], date(2026, 1, 1))

    def test_duplicate_revision_validation(self):
        self.entry()
        duplicate=DocumentRevisionEntry(document=self.doc, revisi='06', uraian='Duplikat')
        with self.assertRaises(ValidationError): duplicate.full_clean()

    def test_active_retired_history_readonly_for_pi_and_ik(self):
        request=RequestFactory().get('/')
        request.user=get_user_model().objects.create_superuser(username='history_admin', password='test')
        inline=RevisionEntryInline(ProsedurIntegrasi, risk_admin_site)
        for kind in ('PI', 'IK'):
            self.doc.jenis=kind
            for status in ('active', 'retired'):
                self.doc.status=status
                self.assertFalse(inline.has_change_permission(request, self.doc))
                self.assertFalse(inline.has_add_permission(request, self.doc))
                self.assertFalse(inline.has_delete_permission(request, self.doc))
                with self.assertRaises(ValidationError):
                    DocumentRevisionEntry(document=self.doc, revisi='05', uraian='test').clean()

    def test_inline_edit_invalidates_approval(self):
        Document.objects.filter(pk=self.doc.pk).update(status='review', verifikator_tanggal=date.today(), pengesah_tanggal=date.today())
        entry=self.entry()
        fs=Mock(instance=self.doc, forms=[Mock()])
        fs.forms[0].has_changed.return_value=True
        save_revision_formset(fs)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, 'draft')
        self.assertIsNone(self.doc.verifikator_tanggal)
        self.assertIsNone(self.doc.pengesah_tanggal)
        fs.save.assert_called_once()

    def test_racing_activation_rejects_formset_save(self):
        Document.objects.filter(pk=self.doc.pk).update(status='active')
        fs=Mock(instance=self.doc)
        with self.assertRaises(ValidationError): save_revision_formset(fs)
        fs.save.assert_not_called()

    def test_new_revision_copies_structured_history(self):
        self.entry('05', urutan=1, tanggal_berlaku=date(2023,8,23))
        self.entry('06', urutan=2)
        Document.objects.filter(pk=self.doc.pk).update(status='active', tanggal_berlaku=date(2026,1,1))
        target, created=create_revision(self.doc.pk)
        self.assertTrue(created)
        self.assertEqual(target.revisi,'07')
        self.assertEqual([r[0] for r in revision_rows(target)], ['05','06'])
        self.assertEqual(revision_rows(target)[1][1], date(2026,1,1))
        self.assertEqual(self.doc.daftar_perubahan.count(),2)

    def test_new_revision_copies_legacy_without_parsing(self):
        Document.objects.filter(pk=self.doc.pk).update(status='active', tanggal_berlaku=date(2026,1,1))
        target, _=create_revision(self.doc.pk)
        self.assertEqual(revision_rows(target)[0][2], self.doc.catatan_revisi)

    def test_history_requires_current_revision_row(self):
        from .revision_history import RevisionEntryFormSet
        factory=inlineformset_factory(Document, DocumentRevisionEntry, formset=RevisionEntryFormSet,
            fields=('revisi','uraian','urutan','tanggal_berlaku'), extra=0)
        data={'h-TOTAL_FORMS':'1','h-INITIAL_FORMS':'0', 'h-0-revisi':'05',
              'h-0-uraian':'Uraian lama','h-0-urutan':'1'}
        fs=factory(data,instance=self.doc,prefix='h')
        self.assertFalse(fs.is_valid())
        self.assertIn('06', str(fs.non_form_errors()))

    def test_pdf_two_rows_and_long_note(self):
        from .pdf import build_document_pdf
        self.entry('05', urutan=1, tanggal_berlaku=date(2023,8,23))
        self.entry('06', urutan=2)
        original=self.doc.catatan_revisi
        data=build_document_pdf(self.doc)
        self.assertTrue(data.startswith(b'%PDF-'))
        self.doc.daftar_perubahan.filter(revisi='06').update(uraian='Uraian panjang. '*2500+' AKHIRCATATAN')
        self.assertTrue(build_document_pdf(self.doc).startswith(b'%PDF-'))
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.catatan_revisi,original)
