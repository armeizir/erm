from datetime import date
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase

from monthly_report.management.commands.send_monthly_report_daily_reminders import (
    previous_month,
    select_latest_pending_reports,
)


class DailyMonthlyReminderCommandTests(SimpleTestCase):
    def _report(
        self,
        *,
        pk=58,
        reassessment_id=10,
        status="draft",
        version=1,
    ):
        return SimpleNamespace(
            pk=pk,
            reassessment_id=reassessment_id,
            status=status,
            versi=version,
            reassessment="Profil Risiko SPI",
            periode=SimpleNamespace(nama_periode="Jul 2026"),
            get_status_display=lambda: status.replace("_", " ").title(),
        )

    def test_previous_month_handles_year_boundary(self):
        self.assertEqual(previous_month(date(2026, 1, 15)), (2025, 12))
        self.assertEqual(previous_month(date(2026, 8, 3)), (2026, 7))

    def test_latest_approved_version_suppresses_older_draft(self):
        reports = [
            self._report(pk=20, status="approved", version=2),
            self._report(pk=10, status="draft", version=1),
        ]
        self.assertEqual(
            list(select_latest_pending_reports(reports)),
            [],
        )

    @patch(
        "monthly_report.management.commands."
        "send_monthly_report_daily_reminders."
        "resolve_monthly_report_notification_recipients"
    )
    @patch(
        "monthly_report.management.commands."
        "send_monthly_report_daily_reminders."
        "monthly_report_notification_stage"
    )
    @patch(
        "monthly_report.management.commands."
        "send_monthly_report_daily_reminders."
        "latest_pending_reports"
    )
    @patch(
        "monthly_report.management.commands."
        "send_monthly_report_daily_reminders."
        "send_monthly_report_notification"
    )
    def test_dry_run_validates_recipients_without_sending(
        self,
        send_notification,
        latest_reports,
        notification_stage,
        resolve_recipients,
    ):
        latest_reports.return_value = [self._report()]
        notification_stage.return_value = {
            "title": "Input Laporan Risiko Bulanan",
            "instruction": "Mohon melengkapi laporan.",
        }
        resolve_recipients.return_value = {
            "recipients": ["risk.office@example.com"],
            "cc_recipients": ["reviewer@example.com"],
            "bcc_recipients": ["pairing@example.com"],
        }
        output = StringIO()

        call_command(
            "send_monthly_report_daily_reminders",
            run_date="2026-08-03",
            dry_run=True,
            stdout=output,
        )

        latest_reports.assert_called_once_with(
            2026,
            7,
            report_ids=[],
        )
        resolve_recipients.assert_called_once()
        send_notification.assert_not_called()
        self.assertIn("DRY-RUN report=58", output.getvalue())

    @patch(
        "monthly_report.management.commands."
        "send_monthly_report_daily_reminders."
        "monthly_report_notification_stage"
    )
    @patch(
        "monthly_report.management.commands."
        "send_monthly_report_daily_reminders."
        "latest_pending_reports"
    )
    @patch(
        "monthly_report.management.commands."
        "send_monthly_report_daily_reminders."
        "send_monthly_report_notification"
    )
    def test_final_delivery_uses_existing_notification_service(
        self,
        send_notification,
        latest_reports,
        notification_stage,
    ):
        latest_reports.return_value = [self._report()]
        notification_stage.return_value = {
            "title": "Input Laporan Risiko Bulanan",
            "instruction": "Mohon melengkapi laporan.",
        }
        send_notification.return_value = 1

        call_command(
            "send_monthly_report_daily_reminders",
            run_date="2026-08-03",
            base_url="https://erm.plnbatam.com",
        )

        send_notification.assert_called_once()
        kwargs = send_notification.call_args.kwargs
        self.assertEqual(kwargs["delivery_mode"], "final")
        self.assertEqual(
            kwargs["base_url"],
            "https://erm.plnbatam.com",
        )
        self.assertIn(
            "[PENGINGAT OTOMATIS]",
            kwargs["subject_override"],
        )
