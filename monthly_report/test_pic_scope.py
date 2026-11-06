from datetime import date
from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import TestCase
from django.utils import timezone
from masterdata.models import OrganizationUnit, OrganizationUnitAccessGroup, TahunBuku, PeriodeLaporan
from monthly_report.admin import MonthlyRiskReportItemForm
from monthly_report.models import MonthlyRiskReportItem
from monthly_report.pic_scope import organization_choices


class PICScopeTests(TestCase):
    def setUp(self):
        from monthly_report.tests import MonthlyRiskReportAdminTests
        self.prepared_by = get_user_model().objects.create_user(username='pic_scope_test')
        self.tahun_buku = TahunBuku.objects.create(tahun=2026)
        self.periode = PeriodeLaporan.objects.create(
            tahun_buku=self.tahun_buku, kode_periode='2026-10', nama_periode='Oktober 2026',
            jenis_periode='bulanan', tanggal_mulai=date(2026,10,1), tanggal_selesai=date(2026,10,31),
        )
        self.report = MonthlyRiskReportAdminTests._report(self, 'BID STRADA')
        self.risk = MonthlyRiskReportAdminTests._risk_item(self, self.report)
        type(self.risk).objects.filter(pk=self.risk.pk).update(jenis_risiko='kualitatif')
        self.risk.refresh_from_db()
        self.item = MonthlyRiskReportItem.objects.create(report=self.report, risk_event=self.risk)
        self.root = OrganizationUnit.objects.create(code='PIC-100', name='BID STRADA')
        self.child = OrganizationUnit.objects.create(code='PIC-101', name='SBID LAKDA', parent=self.root)
        self.grandchild = OrganizationUnit.objects.create(code='PIC-102', name='SEKSI PENGADAAN', parent=self.child)
        self.other = OrganizationUnit.objects.create(code='PIC-200', name='BID OPS')
        self.inactive = OrganizationUnit.objects.create(code='PIC-103', name='SUB LAMA', parent=self.root, aktif=False)
        OrganizationUnitAccessGroup.objects.create(organization_unit=self.root,
                                                   group=self.report.reassessment.unit_bisnis)

    def unbound(self):
        return MonthlyRiskReportItemForm(instance=MonthlyRiskReportItem.objects.get(pk=self.item.pk), prefix='items-0')

    def post(self, browser, selected, touched='0'):
        data = QueryDict('', mutable=True)
        for name in browser.fields:
            value = browser[name].value()
            key = browser.add_prefix(name)
            if isinstance(value,(tuple,list)):
                data.setlist(key,[str(getattr(v,'pk',v)) for v in value])
            elif isinstance(value,bool):
                if value:data[key]='on'
            elif value is not None:data[key]=str(getattr(value,'pk',value))
        data[browser.add_prefix('realisasi_pic_organization_unit')] = str(selected or '')
        data[browser.add_prefix('_row_version')] = browser.concurrency_token
        data[browser.add_prefix('_row_pic_baseline')] = browser.pic_scope_baseline
        data[browser.add_prefix('_row_touched')] = touched
        return data

    def bound(self, data):
        return MonthlyRiskReportItemForm(data=data,
            instance=MonthlyRiskReportItem.objects.get(pk=self.item.pk), prefix='items-0')

    def test_choices_only_include_report_branch(self):
        qs=self.unbound().fields['realisasi_pic_organization_unit'].queryset
        self.assertEqual(set(qs.values_list('pk',flat=True)),{self.root.pk,self.child.pk,self.grandchild.pk})

    def test_widget_uses_scoped_local_search_not_global_ajax(self):
        widget=self.unbound().fields['realisasi_pic_organization_unit'].widget
        self.assertEqual(widget.attrs['data-pic-scope'],'1')
        self.assertNotIn('admin-autocomplete',widget.attrs.get('class',''))
        self.assertFalse(hasattr(widget,'get_url'))

    def test_missing_mapping_uses_exact_unit_name_only(self):
        OrganizationUnitAccessGroup.objects.all().delete()
        self.assertEqual(set(organization_choices(self.report).values_list('pk',flat=True)),
                         {self.root.pk,self.child.pk,self.grandchild.pk})

    def test_no_mapping_and_no_exact_name_gives_no_global_choices(self):
        OrganizationUnitAccessGroup.objects.all().delete()
        OrganizationUnit.objects.filter(pk=self.root.pk).update(name='NAMA BERBEDA')
        self.assertFalse(organization_choices(self.report).exists())

    def test_outside_scope_post_is_rejected(self):
        browser=self.unbound();form=self.bound(self.post(browser,self.other.pk))
        self.assertFalse(form.is_valid())
        self.assertIn('realisasi_pic_organization_unit',form.errors)
        self.item.refresh_from_db();self.assertIsNone(self.item.realisasi_pic_organization_unit_id)

    def test_save_persists_selection_even_when_js_touch_marker_stays_zero(self):
        browser=self.unbound();form=self.bound(self.post(browser,self.child.pk))
        self.assertTrue(form.row_was_touched)
        self.assertTrue(form.has_changed())
        self.assertTrue(form.is_valid(),form.errors.as_json())
        form.save()
        self.item.refresh_from_db()
        self.assertEqual(self.item.realisasi_pic_organization_unit_id,self.child.pk)
        self.assertEqual(self.item.realisasi_pic,str(self.child))

    def test_existing_legacy_outside_scope_value_is_preserved(self):
        MonthlyRiskReportItem.objects.filter(pk=self.item.pk).update(
            realisasi_pic_organization_unit=self.other,realisasi_pic=str(self.other))
        form=self.unbound()
        self.assertIn(self.other.pk,form.fields['realisasi_pic_organization_unit'].queryset.values_list('pk',flat=True))
        self.assertEqual(
            form.initial['realisasi_pic_organization_unit'],
            self.other.pk,
        )
        submitted = self.bound(self.post(form, self.other.pk))
        self.assertFalse(submitted.row_was_touched)
        self.assertFalse(submitted.has_changed())
        self.assertTrue(submitted.is_valid(), submitted.errors.as_json())
        self.item.refresh_from_db()
        self.assertEqual(
            self.item.realisasi_pic_organization_unit_id,
            self.other.pk,
        )

    def test_untouched_stale_row_does_not_overwrite_new_pic(self):
        browser=self.unbound();data=self.post(browser,None)
        MonthlyRiskReportItem.objects.filter(pk=self.item.pk).update(
            realisasi_pic_organization_unit=self.root,realisasi_pic=str(self.root),updated_at=timezone.now())
        form=self.bound(data)
        self.assertFalse(form.has_changed())
        self.assertTrue(form.is_valid())
        self.item.refresh_from_db();self.assertEqual(self.item.realisasi_pic_organization_unit_id,self.root.pk)

    def test_changed_pic_on_stale_page_is_rejected(self):
        browser=self.unbound();data=self.post(browser,self.child.pk)
        MonthlyRiskReportItem.objects.filter(pk=self.item.pk).update(updated_at=timezone.now())
        form=self.bound(data)
        self.assertTrue(form.row_was_touched)
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())

    def test_clear_selection_clears_derived_text(self):
        MonthlyRiskReportItem.objects.filter(pk=self.item.pk).update(
            realisasi_pic_organization_unit=self.root,realisasi_pic=str(self.root))
        browser=self.unbound();form=self.bound(self.post(browser,None))
        self.assertTrue(form.is_valid(),form.errors.as_json());form.save()
        self.item.refresh_from_db()
        self.assertIsNone(self.item.realisasi_pic_organization_unit_id)
        self.assertFalse(self.item.realisasi_pic)

    def test_token_from_other_row_does_not_mark_this_row_changed(self):
        from django.core import signing
        from monthly_report.pic_scope import SALT
        browser=self.unbound();data=self.post(browser,self.child.pk)
        data[browser.add_prefix('_row_pic_baseline')]=signing.dumps(
            {'item':self.item.pk+999,'version':browser.concurrency_token,'selected':''},salt=SALT)
        form=self.bound(data)
        self.assertFalse(form.row_was_touched)
