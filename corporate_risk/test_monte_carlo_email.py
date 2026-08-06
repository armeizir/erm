from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings

from corporate_risk.pdf_reports import (
    multi_metric_item_label,
    multi_metric_pdf_filename,
)

from corporate_risk.monte_carlo_email import (
    MultiMetricResultEmailForm,
    send_multi_metric_result_email,
)


def make_result():
    return SimpleNamespace(
        pk=8,
        corporate_risk_item=(
            "Serangan Cyber terhadap IT dan OT"
        ),
        forecast_periode="Juli 2026",
        target_status="Tercapai",
        risk_status="Aman",
        probability_not_achieve_target=0,
    )


@override_settings(
    EMAIL_BACKEND=(
        "django.core.mail.backends.locmem.EmailBackend"
    ),
    DEFAULT_FROM_EMAIL="erm@example.com",
)
class MultiMetricResultEmailFormTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.active_user = User.objects.create_user(
            username="risk.officer",
            email="risk.officer@example.com",
            first_name="Risk",
            last_name="Officer",
        )

        self.no_email_user = User.objects.create_user(
            username="tanpa.email",
            email="",
        )

        self.inactive_user = User.objects.create_user(
            username="nonaktif",
            email="nonaktif@example.com",
            is_active=False,
        )

        self.result = make_result()

    def test_active_user_with_email_is_available(self):
        form = MultiMetricResultEmailForm(
            result=self.result,
        )

        available_ids = set(
            form.fields["recipients"]
            .queryset.values_list("pk", flat=True)
        )

        self.assertIn(
            self.active_user.pk,
            available_ids,
        )
        self.assertNotIn(
            self.no_email_user.pk,
            available_ids,
        )
        self.assertNotIn(
            self.inactive_user.pk,
            available_ids,
        )

    def test_selected_and_manual_emails_are_combined(self):
        form = MultiMetricResultEmailForm(
            data={
                "recipients": [
                    str(self.active_user.pk),
                ],
                "additional_emails": (
                    "manual@example.com; "
                    "RISK.OFFICER@example.com"
                ),
                "subject": "Hasil Monte Carlo",
                "message": "Terlampir hasil simulasi.",
            },
            result=self.result,
        )

        self.assertTrue(
            form.is_valid(),
            form.errors,
        )
        self.assertEqual(
            form.cleaned_data["recipient_emails"],
            [
                "risk.officer@example.com",
                "manual@example.com",
            ],
        )

    def test_recipient_is_required(self):
        form = MultiMetricResultEmailForm(
            data={
                "recipients": [],
                "additional_emails": "",
                "subject": "Hasil Monte Carlo",
                "message": "Terlampir hasil simulasi.",
            },
            result=self.result,
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            "Pilih minimal satu penerima",
            str(form.non_field_errors()),
        )

    def test_pdf_filename_uses_item_and_period(self):
        result = make_result()
        result.corporate_risk_item = SimpleNamespace(
            no_risiko=11,
            no_item=None,
            peristiwa_risiko=(
                "Serangan Cyber terhadap IT dan OT"
            ),
        )
        result.forecast_periode = "Mei 2026"

        self.assertEqual(
            multi_metric_item_label(result),
            (
                "#11 - Serangan Cyber terhadap "
                "IT dan OT"
            ),
        )
        self.assertEqual(
            multi_metric_pdf_filename(result),
            (
                "monte-carlo-11-serangan-cyber-"
                "terhadap-it-dan-ot-mei-2026.pdf"
            ),
        )

    @patch(
        "corporate_risk.history_notifications."
        "_mail_connection",
    )
    @patch(
        "corporate_risk.monte_carlo_email."
        "render_multi_metric_pdf",
        return_value=b"%PDF-1.4 test",
    )
    def test_email_sent_separately_with_pdf(
        self,
        render_pdf_mock,
        mail_connection_mock,
    ):
        mail_connection_mock.return_value = (
            mail.get_connection()
        )

        sent_count = send_multi_metric_result_email(
            result=self.result,
            recipients=[
                "one@example.com",
                "two@example.com",
            ],
            subject="Hasil Monte Carlo",
            body="Terlampir hasil simulasi.",
            sent_by=self.active_user,
            result_url=(
                "https://erm.example.com/"
                "admin/corporate_risk/result/8/change/"
            ),
        )

        self.assertEqual(sent_count, 2)
        self.assertEqual(len(mail.outbox), 2)

        self.assertEqual(
            mail.outbox[0].to,
            ["one@example.com"],
        )
        self.assertEqual(
            mail.outbox[1].to,
            ["two@example.com"],
        )

        for message in mail.outbox:
            self.assertEqual(
                len(message.to),
                1,
            )
            attachment = next(
                item
                for item in message.attachments
                if item[0].endswith(".pdf")
            )
            self.assertEqual(
                attachment[1],
                b"%PDF-1.4 test",
            )
            self.assertEqual(
                attachment[0],
                (
                    "monte-carlo-serangan-cyber-"
                    "terhadap-it-dan-ot-juli-2026.pdf"
                ),
            )
            self.assertEqual(
                attachment[2],
                "application/pdf",
            )

        render_pdf_mock.assert_called_once_with(
            self.result
        )
        mail_connection_mock.assert_called_once()
