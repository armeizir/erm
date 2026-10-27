from datetime import date
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, RequestFactory
from django.urls import reverse
from masterdata.models import OrganizationUnit
from .models import Document, ProsedurIntegrasi, Attachment
from .admin import ProsedurIntegrasiAdmin, InstruksiKerjaAdmin
from riskproject.admin_site import risk_admin_site

class SMTTests(TestCase):
    def setUp(self):
        # Buat unit dari model asli tanpa bergantung pada nama kolom organisasi.
        self.unit = OrganizationUnit.objects.create(code="SMT-TEST", name="Unit SMT")
        self.user = get_user_model().objects.create_user(username='smt_test', is_staff=True)
        self.request = RequestFactory().get('/')
        self.request.user = self.user
        self.admin = ProsedurIntegrasiAdmin(ProsedurIntegrasi, risk_admin_site)

    def doc(self, **kwargs):
        values=dict(jenis='PI', nomor='PI-TEST', judul='Pengujian', unit_pemilik=self.unit)
        values.update(kwargs)
        return Document.objects.create(**values)

    def test_active_requires_date(self):
        obj=self.doc(status='active')
        with self.assertRaises(ValidationError): obj.full_clean()

    def test_unique_revision_and_active_document(self):
        self.doc(status='active', tanggal_berlaku=date.today())
        duplicate=Document(jenis='PI', nomor='PI-TEST', judul='Duplikat', unit_pemilik=self.unit, revisi='00')
        with self.assertRaises(ValidationError): duplicate.validate_constraints()
        duplicate.revisi='01'; duplicate.status='active'; duplicate.tanggal_berlaku=date.today()
        with self.assertRaises(ValidationError): duplicate.validate_constraints()

    def test_pi_cannot_link_ik_as_parent(self):
        ik=self.doc(jenis='IK', nomor='IK-TEST')
        obj=self.doc(prosedur_induk=ik)
        with self.assertRaises(ValidationError): obj.clean()

    def test_admin_kind_and_filtered_lists(self):
        self.doc(); self.doc(jenis='IK', nomor='IK-TEST')
        self.assertEqual(self.admin.get_queryset(self.request).count(), 1)
        form=self.admin.get_form(self.request)()
        self.assertEqual(form.instance.jenis, 'PI')

    def test_attachment_permission(self):
        doc=self.doc()
        attachment=Attachment.objects.create(document=doc, nama='Dokumen', berkas='not-present.pdf')
        from django.core.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied): self.admin.download(self.request, doc.pk, attachment.pk)

    def test_authenticated_download(self):
        doc=self.doc()
        permission=Permission.objects.get(content_type__app_label='smt', codename='view_prosedurintegrasi')
        self.user.user_permissions.add(permission)
        with TemporaryDirectory() as tmp:
            storage=Attachment._meta.get_field('berkas').storage
            with patch.object(storage, '_location', tmp):
                storage.__dict__.pop('base_location',None); storage.__dict__.pop('location',None)
                attachment=Attachment.objects.create(document=doc,nama='Test',berkas=SimpleUploadedFile('test.pdf',b'%PDF-test'))
                response=self.admin.download(self.request,doc.pk,attachment.pk)
                self.assertEqual(b''.join(response.streaming_content),b'%PDF-test')
                response.close()
                with self.assertRaises(ValueError): storage.url(attachment.berkas.name)

    def test_view_only_document_page(self):
        doc=self.doc(ruang_lingkup='<p><b>Lingkup terformat</b><script>bad()</script></p>')
        Attachment.objects.create(document=doc,nama='Dokumen',berkas='not-present.pdf')
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='smt',codename='view_prosedurintegrasi'))
        self.client.force_login(self.user)
        response=self.client.get(reverse('risk_admin:smt_prosedurintegrasi_change',args=[doc.pk]))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Unduh')
        self.assertContains(response,'<b>Lingkup terformat</b>', html=False)
        self.assertNotContains(response,'bad()')

    def test_edit_page_has_local_editor_for_content_fields(self):
        doc = self.doc()
        self.user.user_permissions.add(Permission.objects.get(
            content_type__app_label='smt', codename='change_prosedurintegrasi'))
        self.client.force_login(self.user)
        response = self.client.get(reverse('risk_admin:smt_prosedurintegrasi_change', args=[doc.pk]))
        self.assertContains(response, 'smt/editor.js')
        self.assertContains(response, 'smt-rich-editor', count=6)

    def test_rich_form_save_preserves_formats_and_removes_scripts(self):
        from .forms import DocumentForm
        doc = self.doc()
        form = DocumentForm(data={
            'jenis': 'PI', 'nomor': doc.nomor, 'judul': doc.judul,
            'unit_pemilik': self.unit.pk, 'revisi': doc.revisi, 'status': 'draft',
            'ruang_lingkup': '<p style="text-align:justify">Lingkup</p>'
                             '<ol><li><b>Penilaian</b></li></ol><script>bad()</script>',
        }, instance=doc)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        doc.refresh_from_db()
        self.assertIn('<ol><li><b>Penilaian</b></li></ol>', doc.ruang_lingkup)
        self.assertNotIn('script', doc.ruang_lingkup)
