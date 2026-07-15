from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.urls import reverse

from risk.models import AppSetting


STAGE_PREPARE = "prepare"
STAGE_REVIEW = "review"
STAGE_APPROVE = "approve"
MONTH_NAMES = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
}


def monthly_report_deadline(report):
    if report.periode_id and report.periode.tanggal_selesai:
        first_next_month = report.periode.tanggal_selesai + timedelta(days=1)
        return first_next_month.replace(day=5)
    return None


def format_indonesian_date(value):
    if not value:
        return ""
    return f"{value.day} {MONTH_NAMES[value.month]} {value.year}"


def monthly_report_admin_url(report, request=None, base_url=None):
    path = reverse("risk_admin:monthly_report_monthlyriskreport_change", args=[report.pk])
    if request is not None:
        return request.build_absolute_uri(path)
    if base_url:
        return f"{base_url.rstrip('/')}{path}"
    return path


def monthly_report_notification_stage(report):
    if report.status in {"draft", "revision"}:
        return {
            "stage": STAGE_PREPARE,
            "recipient": report.prepared_by,
            "title": "Input Laporan Risiko Bulanan",
            "instruction": (
                "Mohon Risk Officer menyiapkan dan melengkapi laporan risiko bulan sebelumnya "
                "paling lambat tanggal 5."
            ),
        }
    if report.status == "submitted":
        return {
            "stage": STAGE_REVIEW,
            "recipient": report.reviewed_by,
            "title": "Paraf / Review Laporan Risiko Bulanan",
            "instruction": "Mohon Reviewer melakukan paraf/review atas laporan risiko bulanan.",
        }
    if report.status == "under_review":
        return {
            "stage": STAGE_APPROVE,
            "recipient": report.approved_by,
            "title": "Tanda Tangan Digital Laporan Risiko Bulanan",
            "instruction": "Mohon Approver melakukan tanda tangan digital atas laporan risiko bulanan.",
        }
    return None


def _mail_connection(app_setting):
    if app_setting.email_smtp_aktif and app_setting.email_host:
        return get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=app_setting.email_host,
            port=app_setting.email_port,
            username=app_setting.email_host_user or None,
            password=app_setting.email_host_password or None,
            use_tls=app_setting.email_use_tls,
            use_ssl=app_setting.email_use_ssl,
        )
    return None


def send_monthly_report_notification(report, request=None, base_url=None):
    stage = monthly_report_notification_stage(report)
    if not stage:
        raise ValidationError("Status laporan tidak memerlukan notifikasi tahap berikutnya.")

    app_setting = AppSetting.get_solo()
    recipient = stage["recipient"]
    test_email = app_setting.monthly_report_notification_test_email
    if test_email:
        recipients = [test_email]
    else:
        if not recipient:
            raise ValidationError(f"Penerima untuk tahap {stage['title']} belum diisi.")
        if not recipient.email:
            raise ValidationError(f"Email user {recipient.get_username()} belum diisi.")
        recipients = [recipient.email]

    context = {
        "report": report,
        "stage": stage,
        "recipient": recipient,
        "test_email": test_email,
        "deadline": monthly_report_deadline(report),
        "deadline_text": format_indonesian_date(monthly_report_deadline(report)),
        "report_url": monthly_report_admin_url(report, request=request, base_url=base_url),
        "app_setting": app_setting,
    }
    subject = f"{stage['title']} - {report.reassessment} {report.periode.nama_periode}"
    text_body = render_to_string("monthly_report/email/notification.txt", context)
    html_body = render_to_string("monthly_report/email/notification.html", context)
    from_email = app_setting.default_from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None)

    message = EmailMultiAlternatives(
        subject,
        text_body,
        from_email,
        recipients,
        connection=_mail_connection(app_setting),
    )
    message.attach_alternative(html_body, "text/html")
    return message.send()
