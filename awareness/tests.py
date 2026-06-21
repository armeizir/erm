from datetime import date, timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AwarenessAnswer, AwarenessAttempt, AwarenessCampaign, AwarenessQuestion


class AwarenessFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        User = get_user_model()
        self.user = User.objects.create_user(username="risk.user", email="risk@example.com", password="secret")
        self.other = User.objects.create_user(username="other.user", email="other@example.com", password="secret")
        self.admin = User.objects.create_superuser(username="admin", email="admin@example.com", password="secret")
        self.staff = User.objects.create_user(
            username="staff.awareness",
            email="staff-awareness@example.com",
            password="secret",
            is_staff=True,
        )
        today = timezone.localdate()
        self.campaign = AwarenessCampaign.objects.create(
            title="Awareness Manajemen Risiko Dasar 2026",
            description="Kuis dasar",
            topic="manajemen_risiko",
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=30),
            passing_score=70,
            max_attempts=1,
            is_active=True,
        )
        self.q1 = AwarenessQuestion.objects.create(
            campaign=self.campaign,
            order=1,
            question_text="Apa tujuan utama manajemen risiko?",
            option_a="Menghilangkan risiko",
            option_b="Mengidentifikasi, menilai, mengendalikan, dan memantau risiko",
            option_c="Menghindari bisnis",
            option_d="Menunda keputusan",
            correct_answer="B",
            explanation="Manajemen risiko mengelola ketidakpastian.",
        )
        self.q2 = AwarenessQuestion.objects.create(
            campaign=self.campaign,
            order=2,
            question_text="Apa arti KRI?",
            option_a="Key Risk Indicator",
            option_b="Key Revenue Income",
            option_c="Knowledge Risk Input",
            option_d="Key Review Instruction",
            correct_answer="A",
            explanation="KRI adalah indikator risiko utama.",
        )

    def test_user_login_can_view_active_campaign(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("awareness:campaign_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.campaign.title)

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(reverse("awareness:campaign_list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_user_can_start_quiz(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("awareness:start_campaign", args=[self.campaign.pk]))

        self.assertEqual(response.status_code, 302)
        attempt = AwarenessAttempt.objects.get(user=self.user, campaign=self.campaign)
        self.assertEqual(attempt.status, AwarenessAttempt.STATUS_IN_PROGRESS)
        self.assertIn(reverse("awareness:quiz_attempt", args=[attempt.pk]), response["Location"])

    def test_user_can_submit_answers_and_score_is_calculated(self):
        self.client.force_login(self.user)
        attempt = AwarenessAttempt.objects.create(
            user=self.user,
            campaign=self.campaign,
            attempt_number=1,
            total_questions=2,
        )

        response = self.client.post(reverse("awareness:submit_attempt", args=[attempt.pk]), {
            f"question_{self.q1.pk}": "B",
            f"question_{self.q2.pk}": "D",
        })

        attempt.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(attempt.correct_count, 1)
        self.assertEqual(attempt.wrong_count, 1)
        self.assertEqual(float(attempt.score), 50.0)
        self.assertEqual(attempt.status, AwarenessAttempt.STATUS_FAILED)
        self.assertEqual(AwarenessAnswer.objects.filter(attempt=attempt).count(), 2)

    def test_passing_score_marks_passed(self):
        self.client.force_login(self.user)
        attempt = AwarenessAttempt.objects.create(
            user=self.user,
            campaign=self.campaign,
            attempt_number=1,
            total_questions=2,
        )

        self.client.post(reverse("awareness:submit_attempt", args=[attempt.pk]), {
            f"question_{self.q1.pk}": "B",
            f"question_{self.q2.pk}": "A",
        })

        attempt.refresh_from_db()
        self.assertEqual(float(attempt.score), 100.0)
        self.assertEqual(attempt.status, AwarenessAttempt.STATUS_PASSED)

    def test_user_cannot_view_other_user_attempt(self):
        self.client.force_login(self.user)
        attempt = AwarenessAttempt.objects.create(
            user=self.other,
            campaign=self.campaign,
            attempt_number=1,
        )

        response = self.client.get(reverse("awareness:quiz_attempt", args=[attempt.pk]))

        self.assertEqual(response.status_code, 403)

    def test_max_attempts_blocks_new_attempt(self):
        self.client.force_login(self.user)
        AwarenessAttempt.objects.create(
            user=self.user,
            campaign=self.campaign,
            attempt_number=1,
            status=AwarenessAttempt.STATUS_FAILED,
            submitted_at=timezone.now(),
        )

        response = self.client.post(reverse("awareness:start_campaign", args=[self.campaign.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(AwarenessAttempt.objects.filter(user=self.user, campaign=self.campaign).count(), 1)

    def test_start_campaign_requires_post(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("awareness:start_campaign", args=[self.campaign.pk]))

        self.assertEqual(response.status_code, 405)
        self.assertFalse(AwarenessAttempt.objects.filter(user=self.user, campaign=self.campaign).exists())

    def test_admin_export_excel_generates_xlsx(self):
        self.client.force_login(self.admin)
        AwarenessAttempt.objects.create(
            user=self.user,
            campaign=self.campaign,
            attempt_number=1,
            status=AwarenessAttempt.STATUS_PASSED,
            score=100,
            correct_count=2,
            wrong_count=0,
            submitted_at=timezone.now(),
        )

        response = self.client.get(reverse("risk_admin:awareness_campaign_export_xlsx", args=[self.campaign.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertGreater(len(response.content), 1000)

    def test_staff_can_open_awareness_campaign_admin_without_explicit_permission(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse("risk_admin:awareness_awarenesscampaign_changelist"))

        self.assertEqual(response.status_code, 200)

    def test_staff_dashboard_shows_risk_awareness_menu(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse("risk_admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Risk Awareness")

    def test_seed_command_creates_campaign_and_questions(self):
        out = StringIO()

        call_command("seed_awareness_risk_management", stdout=out)

        campaign = AwarenessCampaign.objects.get(title="Awareness Manajemen Risiko Dasar 2026")
        self.assertGreaterEqual(campaign.questions.count(), 10)
        self.assertIn("Seed awareness selesai", out.getvalue())
