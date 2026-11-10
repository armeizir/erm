import json
from datetime import date
from unittest.mock import patch, MagicMock
from django.test import TestCase, RequestFactory, override_settings, Client
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from masterdata.models import OrganizationUnit
from .models import Document
from .ai_admin import SALT
from .ai_service import (AIReviewError, fingerprint, segments_for, validate_suggestions,
                         corrected_value, review)

class AIReviewTests(TestCase):
    def setUp(self):
        # Only the test process uses this disposable key; never persist/rotate
        # the encryption key of the running PRISMA application.
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode('ascii')
        environment = patch.dict('os.environ', {'APP_ENCRYPTION_KEY': key})
        environment.start()
        self.addCleanup(environment.stop)
        encryption_settings = override_settings(APP_ENCRYPTION_KEY=key)
        encryption_settings.enable()
        self.addCleanup(encryption_settings.disable)
        from risk.crypto import _fernet
        clear_crypto_cache = getattr(_fernet, 'cache_clear', None)
        if clear_crypto_cache:
            clear_crypto_cache()
            self.addCleanup(clear_crypto_cache)
        cache.clear()
        from risk.models import AppSetting
        self.ai_setting, _ = AppSetting.objects.update_or_create(pk=1, defaults={
            'ai_aktif': True, 'ai_provider': 'openai', 'ai_api_key': 'encrypted-test-key',
            'ai_model': 'test-model', 'ai_base_url': 'https://api.openai.com/v1'})
        self.unit = OrganizationUnit.objects.create(code='SMT-AI', name='Unit AI')
        self.user = get_user_model().objects.create_superuser('aiadmin', 'ai@example.test', 'test')
        self.client.force_login(self.user)
        self.doc = Document.objects.create(jenis='PI', nomor='PI-AI-01', judul='Test',
            unit_pemilik=self.unit, tujuan='<p>pengelolan risiko 2026</p>')
        self.item = {'field':'tujuan', 'node':0, 'before':'pengelolan', 'after':'pengelolaan', 'reason':'Typo'}

    def url(self, kind='prosedurintegrasi', doc=None):
        return reverse('risk_admin:smt_'+kind+'_ai_review', args=[(doc or self.doc).pk])

    def token(self):
        return signing.dumps({'document':self.doc.pk, 'user':self.user.pk,
            'fingerprint':fingerprint(self.doc), 'suggestions':[self.item]}, salt=SALT)

    def test_get_never_calls_api_or_writes(self):
        original = fingerprint(self.doc)
        with patch('smt.ai_admin.review') as api:
            response=self.client.get(self.url())
        self.assertEqual(response.status_code,200)
        api.assert_not_called()
        self.doc.refresh_from_db();self.assertEqual(fingerprint(self.doc),original)

    def test_review_only_sends_selected_fields_and_never_writes(self):
        with patch('smt.ai_admin.review',return_value=[self.item]) as api:
            response=self.client.post(self.url(),{'action':'review','fields':['tujuan']})
        self.assertEqual(response.status_code,200)
        self.assertEqual(api.call_args.args[1],['tujuan'])
        self.doc.refresh_from_db();self.assertIn('pengelolan',self.doc.tujuan)
        self.assertContains(response,'pengelolaan')

    def test_selected_suggestion_applies_and_logs(self):
        response=self.client.post(self.url(),{'action':'apply','token':self.token(),'selected':['0']})
        self.assertEqual(response.status_code,302)
        self.doc.refresh_from_db();self.assertEqual(self.doc.tujuan,'<p>pengelolaan risiko 2026</p>')
        from django.contrib.admin.models import LogEntry
        self.assertTrue(LogEntry.objects.filter(user=self.user,object_id=str(self.doc.pk)).exists())

    def test_stale_result_rejected(self):
        token=self.token();self.doc.tujuan='Teks lain';self.doc.save()
        response=self.client.post(self.url(),{'action':'apply','token':token,'selected':['0']})
        self.assertContains(response,'Dokumen berubah')
        self.doc.refresh_from_db();self.assertEqual(self.doc.tujuan,'Teks lain')

    def test_final_document_cannot_apply(self):
        self.doc.status='active';self.doc.tanggal_berlaku=date(2026,1,1);self.doc.save()
        response=self.client.post(self.url(),{'action':'apply','token':self.token(),'selected':['0']})
        self.assertEqual(response.status_code,403)
        self.doc.refresh_from_db();self.assertIn('pengelolan',self.doc.tujuan)

    def test_token_tampering_rejected(self):
        response=self.client.post(self.url(),{'action':'apply','token':self.token()+'x','selected':['0']})
        self.assertContains(response,'tidak valid')

    def test_other_user_cannot_reuse_token(self):
        token=self.token()
        other=get_user_model().objects.create_superuser('otherai','other@example.test','test')
        self.client.force_login(other)
        self.assertEqual(self.client.post(self.url(),{'action':'apply','token':token,'selected':['0']}).status_code,403)

    def test_csrf_protects_review(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.user)
        self.assertEqual(client.post(self.url(),{'action':'review','fields':['tujuan']}).status_code,403)

    def test_invalid_fields_and_no_selection_rejected(self):
        with patch('smt.ai_admin.review') as api:
            self.client.post(self.url(),{'action':'review','fields':['nomor']})
        api.assert_not_called()
        self.assertContains(self.client.post(self.url(),{'action':'apply','token':self.token()}),'Pilih minimal')

    def test_ik_route_and_wrong_kind(self):
        self.assertEqual(self.client.get(self.url('instruksikerja')).status_code,404)
        ik=Document.objects.create(jenis='IK',nomor='IK-AI',judul='Instruksi',unit_pemilik=self.unit)
        self.assertEqual(self.client.get(self.url('instruksikerja',ik)).status_code,200)

    def test_api_failure_has_no_database_effect(self):
        with patch('smt.ai_admin.review',side_effect=AIReviewError('API tidak tersedia')):
            self.assertContains(self.client.post(self.url(),{'action':'review','fields':['tujuan']}),'API tidak tersedia')
        self.doc.refresh_from_db();self.assertIn('pengelolan',self.doc.tujuan)

    def test_filter_rejects_codes_numbers_names_and_unknown_text(self):
        segments=segments_for(self.doc,['tujuan'])
        items=[self.item]+[{**self.item,'before':a,'after':b} for a,b in [
            ('2026','2027'),('MRK','PRM'),('yusuf','yusup'),('tidak ada','tidak adalah')]]
        self.assertEqual(validate_suggestions(items,segments),[self.item])

    def test_markup_and_list_markers_preserved(self):
        value='<ol data-section="4.5"><li data-marker="4.5.1"><strong>pengelolan</strong> risiko</li></ol>'
        _, nodes=__import__('smt.ai_service',fromlist=['text_nodes']).text_nodes(value)
        index=next(i for i,(_,_,t) in enumerate(nodes) if t=='pengelolan')
        result=corrected_value(value,[{**self.item,'node':index}])
        self.assertIn('data-section="4.5"',result)
        self.assertIn('<strong>pengelolaan</strong>',result)

    def test_plain_text_stays_plain_and_overlap_rejected(self):
        self.assertEqual(corrected_value('pengelolan risiko',[self.item]),'pengelolaan risiko')
        with self.assertRaises(AIReviewError):corrected_value('pengelolan',[self.item,self.item])

    def test_outbound_payload_and_response_validation(self):
        body={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'suggestions':[self.item]})}]}]}
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps(body).encode()
        opener=MagicMock();opener.open.return_value=response
        with patch('smt.ai_service.request.build_opener',return_value=opener):
            self.assertEqual(review(self.doc,['tujuan']),[self.item])
        req=opener.open.call_args.args[0];payload=json.loads(req.data)
        self.assertFalse(payload['store'])
        self.assertEqual(req.full_url,'https://api.openai.com/v1/responses')
        self.assertNotIn(self.doc.nomor,payload['input'])
        self.assertEqual(payload['text']['format']['type'],'json_schema')

    def test_missing_configuration_never_calls_network(self):
        self.ai_setting.ai_aktif=False;self.ai_setting.save()
        with patch('smt.ai_service.request.build_opener') as opener:
            with self.assertRaises(AIReviewError):review(self.doc,['tujuan'])
        opener.assert_not_called()

    def test_timeout_and_invalid_json_are_readable_errors(self):
        opener=MagicMock();opener.open.side_effect=TimeoutError()
        with patch('smt.ai_service.request.build_opener',return_value=opener):
            with self.assertRaises(AIReviewError):review(self.doc,['tujuan'])
        response=MagicMock();response.__enter__.return_value.read.return_value=b'[]'
        opener.open.side_effect=None;opener.open.return_value=response
        with patch('smt.ai_service.request.build_opener',return_value=opener):
            with self.assertRaises(AIReviewError):review(self.doc,['tujuan'])

    def test_reviewed_document_returns_to_draft_on_apply(self):
        self.doc.status='review';self.doc.verifikator_tanggal=timezone.localdate()
        self.doc.save(update_fields=['status','verifikator_tanggal'])
        response=self.client.post(self.url(),{'action':'apply','token':self.token(),'selected':['0']})
        self.assertEqual(response.status_code,302)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status,'draft')
        self.assertIsNone(self.doc.verifikator_tanggal)

    def test_user_without_document_permission_cannot_send_text(self):
        user=get_user_model().objects.create_user('noperm',is_staff=True)
        self.client.force_login(user)
        with patch('smt.ai_admin.review') as api:
            response=self.client.post(self.url(),{'action':'review','fields':['tujuan']})
        self.assertEqual(response.status_code,403)
        api.assert_not_called()

    def test_configuration_reads_runtime_secret_and_does_not_write_settings(self):
        from risk.models import AppSetting
        from .ai_service import prisma_ai_settings
        stored = self.ai_setting.ai_api_key
        with patch.object(AppSetting, 'runtime_ai_api_key', new_callable=__import__('unittest.mock',fromlist=['PropertyMock']).PropertyMock, return_value='decrypted-key'):
            options=prisma_ai_settings()
        self.assertEqual(options['key'],'decrypted-key')
        self.ai_setting.refresh_from_db()
        self.assertEqual(self.ai_setting.ai_api_key,stored)

    def test_missing_setting_never_creates_database_record(self):
        from risk.models import AppSetting
        from .ai_service import prisma_ai_settings
        AppSetting.objects.all().delete()
        with self.assertRaises(AIReviewError):prisma_ai_settings()
        self.assertFalse(AppSetting.objects.exists())

    def test_invalid_base_and_provider_are_rejected_before_network(self):
        from .ai_service import prisma_ai_settings
        for provider,base in [('gemini','https://api.openai.com/v1'),('openai','http://api.openai.com/v1'),('openai','https://key@api.openai.com/v1'),('unsupported','https://example.test')]:
            self.ai_setting.ai_provider=provider;self.ai_setting.ai_base_url=base;self.ai_setting.save()
            with self.assertRaises(AIReviewError):prisma_ai_settings()

    def test_gemini_uses_configured_model_and_header_without_key_in_url(self):
        self.ai_setting.ai_provider='gemini'
        self.ai_setting.ai_base_url='https://generativelanguage.googleapis.com/v1beta'
        self.ai_setting.ai_model='gemini-test';self.ai_setting.save()
        body={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps({'suggestions':[self.item]})}]}}]}
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps(body).encode()
        opener=MagicMock();opener.open.return_value=response
        with patch('smt.ai_service.request.build_opener',return_value=opener):
            self.assertEqual(review(self.doc,['tujuan']),[self.item])
        req=opener.open.call_args.args[0]
        self.assertEqual(req.full_url,'https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent')
        self.assertTrue(any(k.lower()=='x-goog-api-key' for k in req.headers))
        self.assertNotIn('key=',req.full_url)

    def test_other_provider_uses_configured_responses_base(self):
        self.ai_setting.ai_provider='other';self.ai_setting.ai_base_url='https://provider.example/v1';self.ai_setting.save()
        body={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'suggestions':[]})}]}]}
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps(body).encode()
        opener=MagicMock();opener.open.return_value=response
        with patch('smt.ai_service.request.build_opener',return_value=opener):review(self.doc,['tujuan'])
        self.assertEqual(opener.open.call_args.args[0].full_url,'https://provider.example/v1/responses')
