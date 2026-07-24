from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from masterdata.models import OrganizationUnitUserAssignment
from risk.models import AppSetting
from risk.models import PenugasanUnitBisnis
from risk.services.kpmr_automation import calculate_kpmr_for_report


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


def _pairing_officer_for_report(report):
    if not report.reassessment_id or not report.reassessment.unit_bisnis_id:
        return None
    assignment = (
        PenugasanUnitBisnis.objects.filter(
            unit_bisnis=report.reassessment.unit_bisnis,
            peran=PenugasanUnitBisnis.ROLE_PAIRING_OFFICER,
            aktif=True,
            user__is_active=True,
        )
        .select_related("user")
        .order_by("user__first_name", "user__last_name", "user__username", "id")
        .first()
    )
    return assignment.user if assignment else None


def _risk_officers_for_report(report):
    if not report.reassessment_id or not report.reassessment.unit_bisnis_id:
        return []
    return [
        assignment.user
        for assignment in PenugasanUnitBisnis.objects.filter(
            unit_bisnis=report.reassessment.unit_bisnis,
            peran=PenugasanUnitBisnis.ROLE_RISK_OFFICER,
            aktif=True,
            user__is_active=True,
        )
        .select_related("user")
        .order_by("user__first_name", "user__last_name", "user__username", "id")
    ]


def _active_organization_assignment(user):
    today = timezone.localdate()
    return (
        OrganizationUnitUserAssignment.objects.filter(
            user=user,
            user__is_active=True,
            aktif=True,
            tanggal_mulai__lte=today,
        )
        .filter(Q(tanggal_selesai__isnull=True) | Q(tanggal_selesai__gte=today))
        .select_related("organization_unit", "organization_unit__parent")
        .order_by("-utama", "organization_unit__code", "id")
        .first()
    )


def _pairing_superiors(pairing):
    """Return active heads from the Pairing Officer's unit through its ancestors."""
    assignment = _active_organization_assignment(pairing)
    if assignment is None:
        return []

    today = timezone.localdate()
    organization = assignment.organization_unit
    users = []
    seen_user_ids = {pairing.pk}
    seen_organization_ids = set()
    while organization and organization.pk not in seen_organization_ids:
        seen_organization_ids.add(organization.pk)
        heads = (
            OrganizationUnitUserAssignment.objects.filter(
                organization_unit=organization,
                is_unit_head=True,
                aktif=True,
                user__is_active=True,
                tanggal_mulai__lte=today,
            )
            .filter(Q(tanggal_selesai__isnull=True) | Q(tanggal_selesai__gte=today))
            .select_related("user")
            .order_by("user__first_name", "user__last_name", "user__username", "id")
        )
        for head in heads:
            if head.user_id not in seen_user_ids:
                users.append(head.user)
                seen_user_ids.add(head.user_id)
        organization = organization.parent
    return users


def monthly_report_notification_stage(report):
    if report.status in {"draft", "revision"}:
        return {
            "stage": STAGE_PREPARE,
            "recipients": _risk_officers_for_report(report),
            "recipient_role": "Risk Office",
            "bcc_recipient": _pairing_officer_for_report(report),
            "bcc_recipient_role": "Pairing Officer",
            "ignore_test_email": True,
            "title": "Input Laporan Risiko Bulanan",
            "instruction": (
                "Mohon Risk Office menyiapkan dan melengkapi laporan risiko bulan sebelumnya "
                "paling lambat tanggal 5. Pairing Officer unit terkait menerima salinan email ini "
                "sebagai pendamping pemantauan."
            ),
        }
    if report.status == "submitted":
        return {
            "stage": STAGE_REVIEW,
            "recipient": report.reviewed_by,
            "recipient_role": "Reviewed by",
            "bcc_recipient": _pairing_officer_for_report(report),
            "bcc_recipient_role": "Pairing Officer",
            "title": "Paraf / Review Laporan Risiko Bulanan",
            "instruction": "Mohon Reviewer melakukan paraf/review atas laporan risiko bulanan.",
        }
    if report.status == "under_review":
        return {
            "stage": STAGE_APPROVE,
            "recipient": report.approved_by,
            "recipient_role": "Approved by",
            "bcc_recipient": _pairing_officer_for_report(report),
            "bcc_recipient_role": "Pairing Officer",
            "title": "Tanda Tangan Digital Laporan Risiko Bulanan",
            "instruction": "Mohon Approver melakukan tanda tangan digital atas laporan risiko bulanan.",
        }
    if report.status == "approved":
        pairing = _pairing_officer_for_report(report)
        return {
            "stage": "completed",
            "recipient": pairing,
            "recipient_role": "Pairing Officer",
            "cc_recipients": _pairing_superiors(pairing) if pairing else [],
            "title": "Laporan Risiko Bulanan Telah Disetujui",
            "instruction": (
                "Laporan risiko bulanan telah disetujui. Mohon Pairing Officer dan "
                "atasan pada hierarki organisasi melakukan pemantauan dan tindak lanjut "
                "sesuai kewenangan."
            ),
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


def send_monthly_report_notification(
    report,
    request=None,
    base_url=None,
    correction_note="",
):
    stage = monthly_report_notification_stage(report)
    if not stage:
        raise ValidationError("Status laporan tidak memerlukan notifikasi tahap berikutnya.")
    correction_note = (correction_note or "").strip()
    if correction_note:
        if report.status != "revision":
            raise ValidationError(
                "Komentar koreksi hanya dapat dikirim untuk laporan berstatus Revision."
            )
        stage = {
            **stage,
            "title": "Koreksi Laporan Risiko Bulanan",
            "instruction": (
                "Laporan dikembalikan oleh reviewer/approver. "
                "Mohon Prepared by memperbaiki laporan sesuai komentar koreksi, "
                "kemudian melakukan Submit Ulang."
            ),
        }

    app_setting = AppSetting.get_solo()
    recipient_users = stage.get("recipients")
    recipient = stage.get("recipient")
    bcc_recipient = stage.get("bcc_recipient")
    cc_recipient_users = stage.get("cc_recipients") or []
    recipient_names = []
    test_email = "" if stage.get("ignore_test_email") else app_setting.monthly_report_notification_test_email
    bcc_recipients = []
    cc_recipients = []
    if test_email:
        recipients = [test_email]
    else:
        if recipient_users is not None:
            if not recipient_users:
                raise ValidationError("Belum ada Risk Officer aktif pada BID/Unit Bisnis laporan.")
            users_without_email = [user.get_username() for user in recipient_users if not user.email]
            if users_without_email:
                raise ValidationError(
                    "Email Risk Officer belum diisi: " + ", ".join(users_without_email)
                )
            recipients = list(dict.fromkeys(user.email for user in recipient_users))
            recipient = recipient_users[0]
            recipient_names = [
                user.get_full_name().strip() or user.get_username()
                for user in recipient_users
            ]
        elif not recipient:
            role = stage.get("recipient_role") or f"tahap {stage['title']}"
            raise ValidationError(f"Penerima {role} untuk laporan ini belum diisi.")
        else:
            if not recipient.email:
                raise ValidationError(f"Email user {recipient.get_username()} belum diisi.")
            recipients = [recipient.email]
            recipient_names = [
                recipient.get_full_name().strip() or recipient.get_username()
            ]
        if "bcc_recipient" in stage:
            if not bcc_recipient:
                role = stage.get("bcc_recipient_role") or "BCC"
                raise ValidationError(f"Penerima BCC {role} untuk laporan ini belum diisi.")
            if not bcc_recipient.email:
                raise ValidationError(f"Email user {bcc_recipient.get_username()} belum diisi.")
            bcc_recipients = [bcc_recipient.email]
        users_without_email = [
            user.get_username() for user in cc_recipient_users if not user.email
        ]
        if users_without_email:
            raise ValidationError(
                "Email atasan organisasi belum diisi: " + ", ".join(users_without_email)
            )
        recipient_emails = set(recipients)
        cc_recipients = list(
            dict.fromkeys(
                user.email
                for user in cc_recipient_users
                if user.email not in recipient_emails
            )
        )

    context = {
        "report": report,
        "stage": stage,
        "recipient": recipient,
        "recipient_names": recipient_names,
        "test_email": test_email,
        "deadline": monthly_report_deadline(report),
        "deadline_text": format_indonesian_date(monthly_report_deadline(report)),
        "report_url": monthly_report_admin_url(report, request=request, base_url=base_url),
        "app_setting": app_setting,
        "kpmr": calculate_kpmr_for_report(report),
        "correction_note": correction_note,
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
        cc=cc_recipients,
        bcc=bcc_recipients,
        connection=_mail_connection(app_setting),
    )
    message.attach_alternative(html_body, "text/html")
    return message.send()
