from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AwarenessAttempt, AwarenessCampaign
from .notifications import awareness_group_result_rows, send_awareness_notification


class AwarenessCampaignPeriodClosureTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(
            username="risk.user",
            email="risk.user@example.com",
            password="secret",
        )
        self.group = Group.objects.create(name="BID RISIKO")
        self.user.groups.add(self.group)
        today = timezone.localdate()
        self.campaign = AwarenessCampaign.objects.create(
            title="Awareness Manajemen Risiko Juli 2026",
            start_date=today - timedelta(days=10),
            end_date=today - timedelta(days=1),
            passing_score=70,
            is_active=True,
        )

    def test_expired_campaign_is_hidden_and_persisted_inactive(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("awareness:campaign_list"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.campaign.title)
        self.campaign.refresh_from_db()
        self.assertFalse(self.campaign.is_active)

    def test_direct_quiz_access_expires_open_attempt_after_campaign_end(self):
        attempt = AwarenessAttempt.objects.create(
            campaign=self.campaign,
            user=self.user,
            attempt_number=1,
            status=AwarenessAttempt.STATUS_IN_PROGRESS,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("awareness:quiz_attempt", args=[attempt.pk]))

        self.assertRedirects(
            response,
            reverse("awareness:attempt_result", args=[attempt.pk]),
            fetch_redirect_response=False,
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, AwarenessAttempt.STATUS_EXPIRED)
        self.assertIsNotNone(attempt.submitted_at)

    def test_direct_submit_is_blocked_after_campaign_end(self):
        attempt = AwarenessAttempt.objects.create(
            campaign=self.campaign,
            user=self.user,
            attempt_number=1,
            status=AwarenessAttempt.STATUS_IN_PROGRESS,
        )
        self.client.force_login(self.user)

        response = self.client.post(reverse("awareness:submit_attempt", args=[attempt.pk]))

        self.assertRedirects(
            response,
            reverse("awareness:attempt_result", args=[attempt.pk]),
            fetch_redirect_response=False,
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, AwarenessAttempt.STATUS_EXPIRED)

    def test_group_result_uses_latest_completed_attempt_per_user(self):
        AwarenessAttempt.objects.create(
            campaign=self.campaign,
            user=self.user,
            attempt_number=1,
            status=AwarenessAttempt.STATUS_FAILED,
            score=50,
            submitted_at=timezone.now() - timedelta(hours=1),
        )
        AwarenessAttempt.objects.create(
            campaign=self.campaign,
            user=self.user,
            attempt_number=2,
            status=AwarenessAttempt.STATUS_PASSED,
            score=90,
            submitted_at=timezone.now(),
        )

        result = awareness_group_result_rows(self.campaign)
        row = next(row for row in result["rows"] if row["unit"] == self.group.name)

        self.assertEqual(row["respondent_count"], 1)
        self.assertEqual(row["average_score"], 90)
        self.assertEqual(row["passed_count"], 1)
        self.assertEqual(row["failed_count"], 0)
        self.assertEqual(row["pass_rate"], 100)
        self.assertEqual(row["understanding"], "Sangat Baik")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="PLN Batam ERM <erm@plnbatam.com>",
    )
    def test_expired_campaign_email_is_thank_you_and_group_result(self):
        AwarenessAttempt.objects.create(
            campaign=self.campaign,
            user=self.user,
            attempt_number=1,
            status=AwarenessAttempt.STATUS_PASSED,
            score=90,
            submitted_at=timezone.now(),
        )

        sent = send_awareness_notification(
            self.campaign,
            ["risk.admin@plnbatam.com"],
            base_url="https://erm.plnbatam.com",
        )

        self.assertEqual(sent, 1)
        message = mail.outbox[0]
        self.assertIn("Terima Kasih atas Partisipasi", message.subject)
        self.assertIn("Terima kasih atas partisipasi", message.body)
        self.assertIn("Hasil pemahaman per group", message.body)
        self.assertIn("BID RISIKO", message.body)
        self.assertNotIn("Silakan mengisi awareness", message.body)

        html_body = message.alternatives[0].content
        self.assertIn("Hasil Pemahaman per Group", html_body)
        self.assertIn("BID RISIKO", html_body)
        self.assertNotIn("Isi Awareness Sekarang", html_body)
