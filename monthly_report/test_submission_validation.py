from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest import TestCase
from unittest.mock import Mock
from .submission_validation import item_monitoring_issues, report_submission_issues

class SubmissionValidationTests(TestCase):
    def item(self, kind='kualitatif', pk=1):
        risk = NS(pk=pk, no_item=1, no_risiko=1, no_penyebab_risiko=str(pk), jenis_risiko=kind, key_risk_indicators='KRI')
        matrix = NS(get_cell=lambda *args: NS(skor=1))
        return NS(pk=pk, report_id=1, risk_event=risk,
            status_rencana_perlakuan='continue', progress_pelaksanaan_percent=Decimal('0'),
            realisasi_rencana_perlakuan='Belum dilaksanakan', realisasi_output_perlakuan='Belum ada',
            realisasi_biaya_perlakuan=Decimal('0'), realisasi_pic='PIC',
            realisasi_pic_organization_unit_id=None, realisasi_skala_dampak=NS(pk=1),
            realisasi_skala_probabilitas=NS(pk=1), realisasi_nilai_dampak=Decimal('0'),
            realisasi_nilai_probabilitas=Decimal('0'), realisasi_nilai_kri=Decimal('0'),
            realisasi_kri_text='', realisasi_threshold_kri='green',
            _get_active_matrix=lambda: matrix)

    def test_zero_is_complete(self):
        self.assertEqual(item_monitoring_issues(self.item('kuantitatif')), [])

    def test_qualitative_does_not_require_money(self):
        item = self.item(); item.realisasi_nilai_dampak = None
        self.assertEqual(item_monitoring_issues(item), [])

    def test_quantitative_requires_components(self):
        item = self.item('kuantitatif'); item.realisasi_nilai_dampak = None
        self.assertIn('realisasi_nilai_dampak', [x['name'] for x in item_monitoring_issues(item)])

    def test_blank_cost_is_not_zero(self):
        item = self.item(); item.realisasi_biaya_perlakuan = None
        self.assertIn('realisasi_biaya_perlakuan', [x['name'] for x in item_monitoring_issues(item)])

    def test_child_does_not_require_residual_or_kri(self):
        item = self.item(); item.realisasi_skala_dampak = None
        item.realisasi_skala_probabilitas = None; item.realisasi_nilai_kri = None
        self.assertEqual(item_monitoring_issues(item, False), [])

    def test_child_still_requires_progress(self):
        item = self.item(); item.progress_pelaksanaan_percent = None
        self.assertTrue(item_monitoring_issues(item, False))

    def test_whitespace_is_missing(self):
        item = self.item(); item.realisasi_output_perlakuan = '  '
        self.assertTrue(item_monitoring_issues(item))

    def test_matrix_cell_required(self):
        item = self.item(); item._get_active_matrix = lambda: None
        self.assertTrue(item_monitoring_issues(item))

    def test_invalid_numeric_values(self):
        for value in ('NaN', '-1', '101', 'Infinity'):
            with self.subTest(value=value):
                item = self.item(); item.progress_pelaksanaan_percent = Decimal(value)
                self.assertTrue(item_monitoring_issues(item))

    def test_text_kri_valid(self):
        item = self.item(); item.realisasi_nilai_kri = None; item.realisasi_kri_text = 'Selesai'
        self.assertEqual(item_monitoring_issues(item), [])

    def test_empty_report_blocked(self):
        manager = Mock(); manager.select_related.return_value.all.return_value = []
        self.assertTrue(report_submission_issues(NS(items=manager)))

    def test_owner_selection_does_not_depend_on_completeness(self):
        owner = self.item(pk=1); owner.realisasi_skala_dampak = None
        child = self.item(pk=2)
        manager = Mock(); manager.select_related.return_value.all.return_value = [child, owner]
        issues = report_submission_issues(NS(items=manager))
        self.assertEqual(len(issues), 1)
        self.assertIn('item 1', issues[0])
