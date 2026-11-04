"""Database integration checks; run inside the complete PRISMA project."""
from datetime import date
from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.test import TestCase
from masterdata.models import TahunBuku, PeriodeLaporan
from monthly_report.models import MonthlyRiskReport, MonthlyRiskReportItem
from monthly_report.services import initialize_monthly_report_structure_from_profile
from risk.management.commands.revise_hcga_title_2026 import OLD, NEW, apply_revision
from risk.models import ReAssessmentItem
from risk.services.title_period import risk_for_report


class HCGATitlePeriodTests(TestCase):
    def setUp(self):
        # Reuse the application's established fixture builders, without inheriting its tests.
        from monthly_report.tests import MonthlyRiskReportAdminTests
        self.prepared_by = get_user_model().objects.create_user(username="hcga_test", is_staff=True)
        self.tahun_buku = TahunBuku.objects.create(tahun=2026)
        self.periode = self.period(9, 30)
        self.september = MonthlyRiskReportAdminTests._report(self, "BID HCGA")
        self.old = MonthlyRiskReportAdminTests._risk_item(
            self, self.september, no_item=10, no_risiko=10, peristiwa_risiko=OLD,
        )
        self.october = MonthlyRiskReport.objects.create(
            tahun_buku=self.tahun_buku, periode=self.period(10, 31),
            reassessment=self.september.reassessment, prepared_by=self.prepared_by,
        )
        for report in (self.september, self.october):
            MonthlyRiskReportItem.objects.bulk_create([
                MonthlyRiskReportItem(report=report, risk_event=self.old, km_item=self.old.km_item,
                                      issue_summary="Snapshot tetap", progress_pelaksanaan_percent=75)
            ])

    def period(self, month, last):
        return PeriodeLaporan.objects.create(
            tahun_buku=self.tahun_buku, kode_periode=f"2026-{month:02d}",
            nama_periode=f"{month}/2026", jenis_periode="bulanan",
            tanggal_mulai=date(2026, month, 1), tanggal_selesai=date(2026, month, last),
        )

    def apply(self):
        return apply_revision(self.old.pk, self.prepared_by)

    def test_september_keeps_title_and_october_uses_new_version(self):
        result = self.apply()
        self.assertEqual(self.september.items.get().risk_event.peristiwa_risiko, OLD)
        self.assertEqual(self.october.items.get().risk_event.peristiwa_risiko, NEW)
        self.assertEqual(self.october.items.get().risk_event_id, result["new_id"])
        for report in (self.september, self.october):
            self.assertEqual(report.profile_items_queryset().filter(no_item=10).count(), 1)

    def test_snapshot_and_planning_values_preserved(self):
        row = self.october.items.get()
        before = {f.attname: getattr(row, f.attname) for f in row._meta.concrete_fields if f.name != "risk_event"}
        planning = {f.attname: getattr(self.old, f.attname) for f in self.old._meta.concrete_fields
                    if f.name not in {"id", "peristiwa_risiko", "valid_from", "valid_to", "is_active"}}
        result = self.apply()
        row.refresh_from_db()
        self.assertEqual(before, {key: getattr(row, key) for key in before})
        new = ReAssessmentItem.objects.get(pk=result["new_id"])
        self.assertEqual(planning, {key: getattr(new, key) for key in planning})
        for field in self.old._meta.many_to_many:
            self.assertEqual(set(getattr(self.old, field.name).values_list("pk", flat=True)),
                             set(getattr(new, field.name).values_list("pk", flat=True)))

    def test_retry_does_not_duplicate(self):
        first = self.apply()
        second = self.apply()
        self.assertEqual(first["new_id"], second["new_id"])
        self.assertEqual(second["monthly_item_ids"], [])

    def test_locked_report_blocks_all_changes(self):
        MonthlyRiskReport.objects.filter(pk=self.october.pk).update(status="approved", is_locked=True)
        with self.assertRaises(CommandError):
            self.apply()
        self.old.refresh_from_db()
        self.assertTrue(self.old.is_active)
        self.assertIsNone(self.old.valid_to)
        self.assertFalse(ReAssessmentItem.objects.filter(peristiwa_risiko=NEW).exists())

    def test_copy_resolves_source_to_correct_period(self):
        self.apply()
        self.assertEqual(risk_for_report(self.old, self.october).peristiwa_risiko, NEW)
        self.assertEqual(risk_for_report(self.old, self.september).pk, self.old.pk)
        self.october.periode = self.period(11, 30)
        self.assertEqual(risk_for_report(self.old, self.october).peristiwa_risiko, NEW)
        self.october.periode = self.period(12, 31)
        self.assertEqual(risk_for_report(self.old, self.october).peristiwa_risiko, NEW)

    def test_empty_report_initialization_has_one_version(self):
        self.apply()
        self.october.items.all().delete()
        initialize_monthly_report_structure_from_profile(self.october)
        self.assertEqual(self.october.items.count(), 1)
        self.assertEqual(self.october.items.get().risk_event.peristiwa_risiko, NEW)
