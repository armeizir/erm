from datetime import date
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from masterdata.models import OrganizationUnit
from smt.models import Document
from smt.pdf import build_document_pdf

class PDFTests(TestCase):
    def setUp(self):
        unit=OrganizationUnit.objects.create(code='SMT-PDF',name='Unit Uji PDF')
        self.pi=Document.objects.create(jenis='PI',nomor='PI-TEST-01',judul='Prosedur Uji <PDF> & Data',unit_pemilik=unit,revisi='02',tujuan='Tujuan pengujian.',langkah_kerja='Langkah pertama.\n\n'+'Paragraf panjang untuk pengujian. '*300)
        self.ik=Document.objects.create(jenis='IK',nomor='IK-TEST-01',judul='Instruksi Kerja',unit_pemilik=unit,prosedur_induk=self.pi)
        self.user=get_user_model().objects.create_user(username='pdf_user',is_staff=True)
        self.url=reverse('risk_admin:smt_prosedurintegrasi_pdf',args=[self.pi.pk])

    def test_pdf_bytes(self):
        self.assertTrue(build_document_pdf(self.pi).startswith(b'%PDF-'))
        self.assertTrue(build_document_pdf(self.ik).startswith(b'%PDF-'))

    def test_login_required(self):
        self.assertEqual(self.client.get(self.url).status_code,302)

    def test_permission_required(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code,403)

    def test_view_permission_and_kind_isolation(self):
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='smt',codename='view_prosedurintegrasi'))
        self.client.force_login(self.user)
        response=self.client.get(self.url)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['Content-Type'],'application/pdf')
        self.assertIn('inline',response['Content-Disposition'])
        wrong=reverse('risk_admin:smt_prosedurintegrasi_pdf',args=[self.ik.pk])
        self.assertEqual(self.client.get(wrong).status_code,404)
        change=self.client.get(reverse('risk_admin:smt_prosedurintegrasi_change',args=[self.pi.pk]))
        self.assertContains(change,'Lihat PDF')
