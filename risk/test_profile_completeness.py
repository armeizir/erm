from io import StringIO
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from risk.models import (
    AppSetting,
    ItemKontrakManajemen,
    KnowledgeBaseArticle,
    KnowledgeBaseCategory,
    KontrakManajemen,
    MasterBagianKM,
    MasterTemplateKM,
    MasterKategoriDampak,
    PenugasanUnitBisnis,
    ProfileCompletenessNotificationLog,
    ProfileCompletenessAssessment,
    ReAssessmentItem,
    ReAssessmentSummary,
)
from risk.services.profile_completeness import (
    check_profile_completeness,
    CompletenessResult,
    latest_profile_revisions,
    resolve_profile_recipients,
    send_profile_completeness_notification,
    should_send_notification,
)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="erm@example.com",
    APP_BASE_URL="https://erm.example.com",
)
class ProfileCompletenessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.unit = Group.objects.create(name="UB TEST")
        cls.other_unit = Group.objects.create(name="UB OTHER")
        template = MasterTemplateKM.objects.create(tahun=2026, nama="KM Test")
        section = MasterBagianKM.objects.create(
            template=template, kode_bagian="A", nama_bagian="Kinerja", urutan=1
        )
        contract = KontrakManajemen.objects.create(
            judul="KM UB TEST", tahun=2026, unit_bisnis=cls.unit, template=template
        )
        cls.km_item = ItemKontrakManajemen.objects.create(
            kontrak=contract, master_bagian=section, no_urut=1,
            indikator_kinerja_kunci="KPI Test",
        )
        cls.profile = ReAssessmentSummary.objects.create(
            judul="Profil Risiko UB TEST", tahun=2026,
            unit_bisnis=cls.unit, kontrak_manajemen=contract,
        )
        cls.item = ReAssessmentItem.objects.create(
            summary=cls.profile, no_item=1, km_item=cls.km_item, no_risiko=1,
            peristiwa_risiko="Gangguan operasi", deskripsi_peristiwa_risiko="Deskripsi",
        )

    def assignment(self, username, email, role, unit=None, active=True, user_active=True):
        user = get_user_model().objects.create_user(
            username=username, email=email, is_active=user_active
        )
        PenugasanUnitBisnis.objects.create(
            user=user, unit_bisnis=unit or self.unit, peran=role, aktif=active
        )
        return user

    def test_missing_header_and_item_data_are_grouped(self):
        result = check_profile_completeness(self.profile)

        self.assertFalse(result.is_complete)
        self.assertGreater(result.error_count, 0)
        self.assertIn("Data Profil", result.grouped())
        self.assertIn("Data Risiko", result.grouped())
        self.assertIn("Risiko Inheren", result.grouped())
        self.assertIn("Risiko Residual", result.grouped())
        self.assertTrue(any("Matriks Risiko" in finding.message for finding in result.findings))
        self.assertTrue(any("Taksonomi" in finding.message for finding in result.findings))

    def test_duplicate_event_and_number_produce_warnings(self):
        ReAssessmentItem.objects.create(
            summary=self.profile, no_item=1, km_item=self.km_item, no_risiko=2,
            peristiwa_risiko="Gangguan operasi", deskripsi_peristiwa_risiko="Lain",
        )

        result = check_profile_completeness(self.profile)

        warnings = [finding.message for finding in result.findings if finding.severity == "warning"]
        self.assertTrue(any("Nomor item 1" in message for message in warnings))
        self.assertTrue(any("Peristiwa risiko yang sama" in message for message in warnings))

    def test_risk_officer_and_same_unit_pairing_are_resolved(self):
        officer = self.assignment("officer", "officer@example.com", PenugasanUnitBisnis.ROLE_RISK_OFFICER)
        pairing = self.assignment("pairing", "pairing@example.com", PenugasanUnitBisnis.ROLE_PAIRING_OFFICER)
        self.assignment("other", "other@example.com", PenugasanUnitBisnis.ROLE_PAIRING_OFFICER, unit=self.other_unit)

        recipients = resolve_profile_recipients(self.profile)

        self.assertEqual(recipients["to"], [officer.email])
        self.assertEqual(recipients["cc"], [pairing.email])
        self.assertNotIn("other@example.com", recipients["cc"])

    def test_inactive_invalid_and_duplicate_recipients_are_removed(self):
        self.assignment("officer", "shared@example.com", PenugasanUnitBisnis.ROLE_RISK_OFFICER)
        self.assignment("pairing", "shared@example.com", PenugasanUnitBisnis.ROLE_PAIRING_OFFICER)
        self.assignment("inactive", "inactive@example.com", PenugasanUnitBisnis.ROLE_RISK_OFFICER, active=False)
        self.assignment("invalid", "not-an-email", PenugasanUnitBisnis.ROLE_RISK_OFFICER)

        recipients = resolve_profile_recipients(self.profile)

        self.assertEqual(recipients["to"], ["shared@example.com"])
        self.assertEqual(recipients["cc"], [])

    def test_missing_pairing_is_warning_not_delivery_error(self):
        self.assignment("officer", "officer@example.com", PenugasanUnitBisnis.ROLE_RISK_OFFICER)

        recipients = resolve_profile_recipients(self.profile)

        self.assertEqual(recipients["to"], ["officer@example.com"])
        self.assertEqual(recipients["cc"], [])
        self.assertTrue(any("Pairing" in warning for warning in recipients["warnings"]))

    def test_support_email_is_fallback_when_risk_officer_is_missing(self):
        app_setting = AppSetting.objects.first() or AppSetting()
        app_setting.support_email = "admin-erm@example.com"
        app_setting.save()

        recipients = resolve_profile_recipients(self.profile)

        self.assertEqual(recipients["to"], ["admin-erm@example.com"])
        self.assertTrue(any("Risk Officer" in warning for warning in recipients["warnings"]))

    def test_email_uses_to_cc_absolute_url_and_creates_log(self):
        self.assignment("officer", "officer@example.com", PenugasanUnitBisnis.ROLE_RISK_OFFICER)
        self.assignment("pairing", "pairing@example.com", PenugasanUnitBisnis.ROLE_PAIRING_OFFICER)
        result = check_profile_completeness(self.profile)
        recipients = resolve_profile_recipients(self.profile)

        sent, error = send_profile_completeness_notification(result, recipients)

        self.assertTrue(sent, error)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["officer@example.com"])
        self.assertEqual(mail.outbox[0].cc, ["pairing@example.com"])
        self.assertIn("https://erm.example.com/admin/risk/reassessmentsummary/", mail.outbox[0].body)
        log = ProfileCompletenessNotificationLog.objects.get()
        self.assertEqual(log.recipient_to, ["officer@example.com"])
        self.assertEqual(log.recipient_cc, ["pairing@example.com"])

    def test_email_includes_published_profile_completeness_tutorial(self):
        category = KnowledgeBaseCategory.objects.create(
            nama="Tutorial Profil Risiko", slug="tutorial-profil-risiko"
        )
        KnowledgeBaseArticle.objects.create(
            kategori=category,
            judul="Cara Melengkapi Profil Risiko",
            konten="Panduan",
            ringkasan="Langkah perbaikan data profil.",
            status=KnowledgeBaseArticle.STATUS_PUBLISHED,
            tutorial_placement=(
                KnowledgeBaseArticle.TUTORIAL_PLACEMENT_PROFILE_COMPLETENESS_EMAIL
            ),
            video_youtube_url="https://www.youtube.com/watch?v=profile123",
        )
        self.assignment("officer", "officer@example.com", PenugasanUnitBisnis.ROLE_RISK_OFFICER)
        result = check_profile_completeness(self.profile)

        sent, error = send_profile_completeness_notification(
            result, resolve_profile_recipients(self.profile)
        )

        self.assertTrue(sent, error)
        self.assertIn("Cara Melengkapi Profil Risiko", mail.outbox[0].body)
        self.assertIn("https://www.youtube.com/watch?v=profile123", mail.outbox[0].body)
        self.assertIn("Tonton Video Tutorial", mail.outbox[0].alternatives[0].content)

    def test_same_findings_and_recipients_are_deduplicated_until_changed(self):
        self.assignment("officer", "officer@example.com", PenugasanUnitBisnis.ROLE_RISK_OFFICER)
        result = check_profile_completeness(self.profile)
        recipients = resolve_profile_recipients(self.profile)
        send_profile_completeness_notification(result, recipients)

        allowed, reason = should_send_notification(result, recipients)

        self.assertFalse(allowed)
        self.assertIn("tidak berubah", reason)

    def test_percentage_ratio_and_empty_requirement_are_safe(self):
        half = CompletenessResult(self.profile, required_count=10, completed_count=5)
        empty = CompletenessResult(self.profile)

        self.assertEqual(half.percentage, Decimal("50.00"))
        self.assertEqual(empty.percentage, Decimal("100.00"))
        self.assertEqual(empty.status_label, "Lengkap")

    def test_qualitative_legacy_typo_skips_optional_numeric_findings(self):
        self.item.kategori_dampak = MasterKategoriDampak.objects.create(
            nama="Dampak Kualilatif"
        )
        self.item.save(update_fields=["kategori_dampak"])

        result = check_profile_completeness(self.profile)

        numeric_messages = [
            finding.message for finding in result.findings
            if "Nilai Dampak" in finding.message or "Nilai Probabilitas" in finding.message
        ]
        self.assertEqual(numeric_messages, [])

    def test_quantitative_missing_numeric_fields_reduce_percentage(self):
        result = check_profile_completeness(self.profile)

        self.assertLess(result.percentage, Decimal("100"))
        self.assertTrue(any("Nilai Dampak Risiko Inheren" in finding.message for finding in result.findings))

    def test_email_records_assessment_and_percentage_subject(self):
        self.assignment("officer2", "officer2@example.com", PenugasanUnitBisnis.ROLE_RISK_OFFICER)
        result = check_profile_completeness(self.profile)

        sent, error = send_profile_completeness_notification(
            result, resolve_profile_recipients(self.profile)
        )

        self.assertTrue(sent, error)
        self.assertEqual(ProfileCompletenessAssessment.objects.count(), 1)
        self.assertIn(result.percentage_display, mail.outbox[0].subject)

    def test_monitoring_uses_latest_revision_once_per_unit_and_year(self):
        revision = ReAssessmentSummary.objects.create(
            judul="Profil Risiko UB TEST - Juli 2026",
            tahun=2026,
            unit_bisnis=self.unit,
            kontrak_manajemen=self.profile.kontrak_manajemen,
        )

        monitored = list(latest_profile_revisions().filter(unit_bisnis=self.unit, tahun=2026))

        self.assertEqual(monitored, [revision])

    def test_dry_run_command_does_not_send_email_and_displays_recipients(self):
        self.assignment("officer", "officer@example.com", PenugasanUnitBisnis.ROLE_RISK_OFFICER)
        output = StringIO()

        call_command(
            "notify_incomplete_risk_profiles",
            profile_id=self.profile.pk,
            dry_run=True,
            stdout=output,
        )

        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("officer@example.com", output.getvalue())
        self.assertIn("mode=dry-run", output.getvalue())
