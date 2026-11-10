from datetime import date
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from monthly_report.models import MonthlyRiskReportItem,MonthlyRiskReportImportBatch,MonthlyRiskReportImportRow
from monthly_report import import_services as service

class FlexibleImportTests(TestCase):
 def setUp(self):
  from monthly_report.tests import MonthlyRiskReportAdminTests
  from masterdata.models import TahunBuku,PeriodeLaporan
  self.prepared_by=get_user_model().objects.create_user(username='flexible_import_test')
  self.tahun_buku=TahunBuku.objects.create(tahun=2026)
  self.periode=PeriodeLaporan.objects.create(tahun_buku=self.tahun_buku,kode_periode='2026-10',nama_periode='Oktober 2026',jenis_periode='bulanan',tanggal_mulai=date(2026,10,1),tanggal_selesai=date(2026,10,31))
  self.report=MonthlyRiskReportAdminTests._report(self,'BID TEST IMPORT')
  self.risk=MonthlyRiskReportAdminTests._risk_item(self,self.report)
  self.item=MonthlyRiskReportItem.objects.create(report=self.report,risk_event=self.risk)
  MonthlyRiskReportItem.objects.filter(pk=self.item.pk).update(realisasi_nilai_dampak=Decimal('1000'),realisasi_nilai_probabilitas=Decimal('10'),realisasi_eksposur=Decimal('100'),realisasi_skor_risiko=7)
  self.item.refresh_from_db()
  self.batch=MonthlyRiskReportImportBatch.objects.create(report=self.report,source_file='test/no-read.xlsx',original_filename='test.xlsx',file_sha256='0'*64,uploaded_by=self.prepared_by,status='review',parser_version=service.IMPORT_PARSER_VERSION,target_fingerprint=service.target_item_fingerprint(self.report))
 def row(self,data=None,**kwargs):
  values=dict(batch=self.batch,source_reference='III.B:10',matched_report_item=self.item,match_method='exact_code',confidence=100,validation_level='yellow',issues=[],raw_data={'flexible_v1':True,'source_sheet':'III.B','warnings':[],'errors':[]},proposed_data=data or {'realisasi_rencana_perlakuan':'Mitigasi Oktober'},user_decision='import')
  values.update(kwargs);return MonthlyRiskReportImportRow.objects.create(**values)
 def apply(self):return service.apply_import_batch(self.batch,self.prepared_by)
 def test_parser_version(self):self.assertEqual(service.IMPORT_PARSER_VERSION,7)
 def test_partial_import_preserves_snapshot(self):
  self.row();self.apply();self.item.refresh_from_db()
  self.assertEqual(self.item.realisasi_rencana_perlakuan,'Mitigasi Oktober')
  self.assertEqual(self.item.realisasi_eksposur,Decimal('100'));self.assertEqual(self.item.realisasi_skor_risiko,7)
  self.report.refresh_from_db();self.assertEqual(self.report.status,'draft')
 def test_new_kri_text_clears_previous_numeric(self):
  MonthlyRiskReportItem.objects.filter(pk=self.item.pk).update(realisasi_nilai_kri=50,realisasi_threshold_kri='green')
  self.batch.target_fingerprint=service.target_item_fingerprint(self.report);self.batch.save()
  self.row({'realisasi_kri_text':'Belum diasesmen','realisasi_nilai_kri':None,'realisasi_threshold_kri':None,'realisasi_threshold_kri_skor':None})
  self.apply();self.item.refresh_from_db();self.assertIsNone(self.item.realisasi_nilai_kri);self.assertIsNone(self.item.realisasi_threshold_kri)
 def test_changed_profile_rejects_stale_preview(self):
  self.row();type(self.risk).objects.filter(pk=self.risk.pk).update(threshold_aman='>999')
  with self.assertRaises(ValidationError):self.apply()
 def test_changed_item_rejects_stale_preview(self):
  self.row();MonthlyRiskReportItem.objects.filter(pk=self.item.pk).update(realisasi_pic='Pengguna lain')
  with self.assertRaises(ValidationError):self.apply()
 def test_locked_report_rejects_import(self):
  self.row();type(self.report).objects.filter(pk=self.report.pk).update(is_locked=True)
  with self.assertRaises(ValidationError):self.apply()
 def test_red_row_cannot_be_imported(self):
  self.row(validation_level='red')
  with self.assertRaises(ValidationError):self.apply()
 def test_pending_row_rejects_import(self):
  self.row(user_decision='pending')
  with self.assertRaises(ValidationError):self.apply()
 def test_conflicting_sources_are_atomic(self):
  self.row({'realisasi_kri_text':'Nilai A'});self.row({'realisasi_kri_text':'Nilai B'},source_reference='III.B:11')
  with self.assertRaises(ValidationError):self.apply()
  self.item.refresh_from_db();self.assertNotEqual(self.item.realisasi_kri_text,'Nilai A')
 def test_forbidden_field_is_rejected(self):
  self.row({'risk_event_id':999999})
  with self.assertRaises(ValidationError):self.apply()
 def test_number_alone_does_not_select_a_risk(self):
  matched,method,confidence,candidates=service._match_item(self.report,{'risk_code':'1','risk_event_text':'','raw_data':{}})
  self.assertIsNone(matched)
 def test_outdated_profile_not_matched(self):
  type(self.risk).objects.filter(pk=self.risk.pk).update(valid_to=date(2026,9,30))
  matched,*_=service._match_item(self.report,{'risk_code':'','risk_event_text':self.risk.peristiwa_risiko,'raw_data':{}})
  self.assertIsNone(matched)
