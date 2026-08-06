from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from monthly_report.notifications import (
    _notification_kpmr,
    resolve_monthly_report_notification_recipients,
)


class DummyUser:
    def __init__(self, username, email):
        self.pk = username
        self.username = username
        self.email = email

    def get_username(self):
        return self.username

    def get_full_name(self):
        return self.username


class MonthlyNotificationRoutingV3Tests(SimpleTestCase):
    def setUp(self):
        self.prepared = DummyUser(
            "prepared",
            "prepared@example.com",
        )
        self.reviewed = DummyUser(
            "reviewed",
            "reviewed@example.com",
        )
        self.approved = DummyUser(
            "approved",
            "approved@example.com",
        )
        self.pairing = DummyUser(
            "pairing",
            "pairing@example.com",
        )
        self.app_setting = SimpleNamespace(
            monthly_report_notification_test_email="",
        )

    def report(self, status):
        return SimpleNamespace(
            status=status,
            prepared_by=self.prepared,
            reviewed_by=self.reviewed,
            approved_by=self.approved,
        )

    def stage(self, status):
        return {
            "recipients": [self.prepared],
            "recipient": (
                self.reviewed
                if status == "submitted"
                else self.approved
                if status == "under_review"
                else self.pairing
            ),
            "bcc_recipient": self.pairing,
            "approved_recipients": (
                SimpleNamespace(
                    to=[self.pairing.email],
                    cc=[
                        "manager@example.com",
                        "director@example.com",
                    ],
                    to_users=[self.pairing],
                    reason="",
                )
                if status == "approved"
                else None
            ),
        }

    def resolve(self, status):
        with patch(
            "monthly_report.notifications.AppSetting.get_solo",
            return_value=self.app_setting,
        ):
            return resolve_monthly_report_notification_recipients(
                self.report(status),
                stage=self.stage(status),
                delivery_mode="final",
            )

    def test_draft(self):
        result = self.resolve("draft")
        self.assertEqual(
            result["recipients"],
            ["prepared@example.com"],
        )
        self.assertEqual(
            result["cc_recipients"],
            [
                "reviewed@example.com",
                "approved@example.com",
            ],
        )
        self.assertEqual(
            result["bcc_recipients"],
            ["pairing@example.com"],
        )

    def test_submitted(self):
        result = self.resolve("submitted")
        self.assertEqual(
            result["recipients"],
            ["reviewed@example.com"],
        )
        self.assertEqual(
            result["cc_recipients"],
            [
                "approved@example.com",
                "prepared@example.com",
            ],
        )
        self.assertEqual(
            result["bcc_recipients"],
            ["pairing@example.com"],
        )

    def test_under_review(self):
        result = self.resolve("under_review")
        self.assertEqual(
            result["recipients"],
            ["approved@example.com"],
        )
        self.assertEqual(
            result["cc_recipients"],
            [
                "reviewed@example.com",
                "prepared@example.com",
            ],
        )
        self.assertEqual(
            result["bcc_recipients"],
            ["pairing@example.com"],
        )

    def test_approved(self):
        result = self.resolve("approved")
        self.assertEqual(
            result["recipients"],
            [
                "pairing@example.com",
                "manager@example.com",
                "director@example.com",
            ],
        )
        self.assertEqual(
            result["cc_recipients"],
            [
                "approved@example.com",
                "reviewed@example.com",
                "prepared@example.com",
            ],
        )
        self.assertEqual(
            result["bcc_recipients"],
            [],
        )

    def test_missing_cc_email_is_skipped(self):
        self.prepared.email = ""

        result = self.resolve("submitted")

        self.assertEqual(
            result["recipients"],
            ["reviewed@example.com"],
        )
        self.assertEqual(
            result["cc_recipients"],
            ["approved@example.com"],
        )
        self.assertEqual(
            result["bcc_recipients"],
            ["pairing@example.com"],
        )

    @patch(
        "monthly_report.notifications.calculate_kpmr_for_report",
        return_value="KPMR",
    )
    def test_kpmr_statuses(self, calculate_mock):
        self.assertIsNone(
            _notification_kpmr(self.report("draft"))
        )
        self.assertIsNone(
            _notification_kpmr(self.report("revision"))
        )

        for status in (
            "submitted",
            "under_review",
            "approved",
        ):
            self.assertEqual(
                _notification_kpmr(self.report(status)),
                "KPMR",
            )

        self.assertEqual(calculate_mock.call_count, 3)
