import json
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch,MagicMock
from django.test import TestCase,Client
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.storage import FileSystemStorage
from django.urls import reverse
from django.utils import timezone
from masterdata.models import OrganizationUnit
from .models import Document,Attachment
from .ai_service import AIReviewError
from .flow_service import generate_flow,validate_flow
from .flow_transport import request_flow
from .flow_pdf import build_flow_pdf

GRAPH={'nodes':[
 {'id':'A','kind':'start','actor':'Pemrakarsa','text':'Mulai'},
 {'id':'B','kind':'decision','actor':'MAN RIS','text':'Dokumen lengkap?'},
 {'id':'C','kind':'process','actor':'Pemrakarsa','text':'Perbaiki dokumen'},
 {'id':'D','kind':'end','actor':'VP MRK','text':'Selesai'}],
 'edges':[{'source':a,'target':b,'label':l} for a,b,l in [('A','B',''),('B','D','Ya'),('B','C','Tidak'),('C','B','')]],'warnings':[]}

class AIFlowTests(TestCase):
 def setUp(self):
  cache.clear();self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  field=Attachment._meta.get_field('berkas')
  storage=patch.object(field,'storage',FileSystemStorage(location=self.temp.name));storage.start();self.addCleanup(storage.stop)
  unit=OrganizationUnit.objects.create(code='FLOW-TEST',name='Unit Flow')
  self.user=get_user_model().objects.create_superuser('flow-admin','flow@example.test','test')
  self.client.force_login(self.user)
  self.doc=Document.objects.create(jenis='PI',nomor='PI-FLOW',revisi='06',judul='Prosedur',unit_pemilik=unit,
   tanggung_jawab='MAN RIS memeriksa dokumen.',langkah_kerja='Mulai. Periksa kelengkapan. Jika tidak lengkap, perbaiki lalu periksa ulang. Selesai.')
 def url(self,kind='prosedurintegrasi',doc=None):return reverse('risk_admin:smt_'+kind+'_ai_flow',args=[(doc or self.doc).pk])
 def ticket(self):
  with patch('smt.flow_admin.generate_flow',return_value=deepcopy(GRAPH)):
   response=self.client.post(self.url(),{'action':'generate'})
  self.assertEqual(response.status_code,200)
  return response.context_data['ticket']
 def save(self,ticket,**extra):return self.client.post(self.url(),{'action':'save','ticket':ticket,'reviewed':'on',**extra})
 def test_get_is_readonly_and_does_not_call_ai(self):
  with patch('smt.flow_admin.generate_flow') as ai:self.assertEqual(self.client.get(self.url()).status_code,200)
  ai.assert_not_called();self.assertEqual(Attachment.objects.count(),0)
 def test_generation_only_creates_preview(self):
  self.assertTrue(self.ticket());self.assertEqual(Attachment.objects.count(),0)
 def test_preview_pdf_does_not_save_attachment(self):
  response=self.client.post(self.url(),{'action':'preview','ticket':self.ticket()})
  self.assertEqual(response['Content-Type'],'application/pdf');self.assertTrue(response.content.startswith(b'%PDF-'))
  self.assertEqual(Attachment.objects.count(),0)
 def test_save_creates_private_attachment_and_audit(self):
  self.assertEqual(self.save(self.ticket()).status_code,302)
  attachment=Attachment.objects.get();self.assertEqual(attachment.jenis,'alur')
  self.assertIn('DRAFT',attachment.nama);self.assertTrue(attachment.berkas.storage.exists(attachment.berkas.name))
  from django.contrib.admin.models import LogEntry
  self.assertEqual(LogEntry.objects.filter(user=self.user).count(),2)
 def test_double_save_does_not_duplicate(self):
  ticket=self.ticket();self.save(ticket);self.save(ticket);self.assertEqual(Attachment.objects.count(),1)
 def test_stale_preview_rejected(self):
  ticket=self.ticket();self.doc.langkah_kerja='Prosedur berubah';self.doc.save()
  self.assertContains(self.save(ticket),'Isi PI berubah');self.assertFalse(Attachment.objects.exists())
 def test_confirm_required(self):
  response=self.client.post(self.url(),{'action':'save','ticket':self.ticket()})
  self.assertContains(response,'Centang konfirmasi');self.assertFalse(Attachment.objects.exists())
 def test_final_pi_preview_only(self):
  self.doc.status='active';self.doc.tanggal_berlaku=timezone.localdate();self.doc.save()
  ticket=self.ticket();self.assertEqual(self.client.post(self.url(),{'action':'preview','ticket':ticket}).status_code,200)
  self.assertEqual(self.save(ticket).status_code,403)
 def test_ik_route_is_not_available(self):
  doc=Document.objects.create(jenis='IK',nomor='IK-FLOW',judul='IK',unit_pemilik=self.doc.unit_pemilik)
  self.assertEqual(self.client.get(self.url('instruksikerja',doc)).status_code,404)
 def test_permission_and_csrf(self):
  viewer=get_user_model().objects.create_user('flow-viewer',is_staff=True)
  self.client.force_login(viewer);self.assertEqual(self.client.get(self.url()).status_code,403)
  client=Client(enforce_csrf_checks=True);client.force_login(self.user)
  self.assertEqual(client.post(self.url(),{'action':'generate'}).status_code,403)
 def test_cross_user_ticket_rejected(self):
  ticket=self.ticket();other=get_user_model().objects.create_superuser('flow-other','other@example.test','test')
  self.client.force_login(other);self.assertEqual(self.save(ticket).status_code,403)
 def test_tampered_ticket_rejected(self):
  self.assertContains(self.save(self.ticket()+'x'),'tidak valid');self.assertFalse(Attachment.objects.exists())
 def test_attachment_change_invalidates_verification(self):
  self.doc.status='review';self.doc.verifikator_tanggal=timezone.localdate();self.doc.save(update_fields=['status','verifikator_tanggal'])
  self.save(self.ticket());self.doc.refresh_from_db()
  self.assertEqual(self.doc.status,'draft');self.assertIsNone(self.doc.verifikator_tanggal)
 def test_storage_cleanup_on_database_failure(self):
  ticket=self.ticket()
  with patch.object(Attachment,'save',side_effect=RuntimeError('test rollback')):
   with self.assertRaises(RuntimeError):self.save(ticket)
  self.assertFalse(Attachment.objects.exists())
  self.assertFalse(any(p.is_file() for p in Path(self.temp.name).rglob('*')))
 def test_graph_validation_accepts_explicit_loop_rejects_broken_branches(self):
  self.assertEqual(validate_flow(deepcopy(GRAPH)),GRAPH)
  bad=deepcopy(GRAPH);bad['edges'][2]['label']='Lanjut'
  with self.assertRaises(AIReviewError):validate_flow(bad)
  bad=deepcopy(GRAPH);bad['nodes'][2]['id']='A'
  with self.assertRaises(AIReviewError):validate_flow(bad)
 def test_generation_sends_only_saved_responsibility_and_steps(self):
  with patch('smt.flow_service.request_flow',return_value=GRAPH) as ai:generate_flow(self.doc)
  self.assertEqual(set(ai.call_args.args[0]),{'tanggung_jawab','langkah_kerja'})
  self.doc.langkah_kerja=''
  with self.assertRaises(AIReviewError):generate_flow(self.doc)
 def test_transport_uses_existing_gemini_configuration(self):
  options={'provider':'gemini','key':'test-secret','model':'gemini-test','base':'https://generativelanguage.googleapis.com/v1beta','temperature':.2}
  response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(GRAPH)}]}}]}).encode()
  opener=MagicMock();opener.open.return_value=response
  with patch('smt.flow_transport.prisma_ai_settings',return_value=options),patch('smt.flow_transport.request.build_opener',return_value=opener):
   self.assertEqual(request_flow({'langkah_kerja':'test'},{},'test'),GRAPH)
  self.assertNotIn('key=',opener.open.call_args.args[0].full_url)
