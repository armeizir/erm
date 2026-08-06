from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.urls import reverse

from risk.models import AppSetting
from risk.models import KnowledgeBaseArticle
from risk.models import PenugasanUnitBisnis
from risk.services.kpmr_automation import calculate_kpmr_for_report
from .recipient_services import build_approved_report_recipients


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
        deadline_day = AppSetting.get_solo().monthly_report_deadline_day
        return first_next_month.replace(day=deadline_day)
    return None


def format_indonesian_date(value):
    if not value:
        return ""
    return f"{value.day} {MONTH_NAMES[value.month]} {value.year}"


def monthly_report_email_tutorial():
    return (
        KnowledgeBaseArticle.objects.filter(
            status=KnowledgeBaseArticle.STATUS_PUBLISHED,
            tutorial_placement=(
                KnowledgeBaseArticle.TUTORIAL_PLACEMENT_MONTHLY_REPORT_EMAIL
            ),
        )
        .exclude(video_youtube_url="")
        .order_by(
            "-dipublikasikan_pada",
            "-diperbarui_pada",
            "-pk",
        )
        .first()
    )


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


def monthly_report_notification_stage(report):
    normalized_status = (report.status or "").strip().lower()
    if normalized_status in {"draft", "revision"}:
        deadline_day = AppSetting.get_solo().monthly_report_deadline_day
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
                f"paling lambat tanggal {deadline_day}. Pairing Officer unit terkait menerima salinan email ini "
                "sebagai pendamping pemantauan."
            ),
        }
    if normalized_status == "submitted":
        return {
            "stage": STAGE_REVIEW,
            "recipient": report.reviewed_by,
            "recipient_role": "Reviewed by",
            "bcc_recipient": _pairing_officer_for_report(report),
            "bcc_recipient_role": "Pairing Officer",
            "title": "Paraf / Review Laporan Risiko Bulanan",
            "instruction": "Mohon Reviewer melakukan paraf/review atas laporan risiko bulanan.",
        }
    if normalized_status == "under_review":
        return {
            "stage": STAGE_APPROVE,
            "recipient": report.approved_by,
            "recipient_role": "Approved by",
            "bcc_recipient": _pairing_officer_for_report(report),
            "bcc_recipient_role": "Pairing Officer",
            "title": "Tanda Tangan Digital Laporan Risiko Bulanan",
            "instruction": "Mohon Approver melakukan tanda tangan digital atas laporan risiko bulanan.",
        }
    if normalized_status == "approved":
        recipients = build_approved_report_recipients(report)
        return {
            "stage": "completed",
            "recipient": recipients.to_users[0] if recipients.to_users else None,
            "recipient_role": "Pairing Officer",
            "approved_recipients": recipients,
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
            password=app_setting.runtime_email_host_password or None,
            use_tls=app_setting.email_use_tls,
            use_ssl=app_setting.email_use_ssl,
        )
    return None


def _valid_recipient_user_email(user, recipients):
    return (user.email or "").strip().casefold() in {
        email.casefold() for email in recipients
    }


def _merge_unique_emails(*email_groups, excluded=()):
    seen = {
        (email or "").strip().casefold()
        for email in excluded
        if (email or "").strip()
    }
    merged = []
    for group in email_groups:
        for email in group or []:
            normalized = (email or "").strip()
            key = normalized.casefold()
            if not normalized or key in seen:
                continue
            seen.add(key)
            merged.append(normalized)
    return merged


def _workflow_cc_emails(report):
    users = [
        ("Reviewer", report.reviewed_by),
        ("Approver", report.approved_by),
    ]
    missing = [
        f"{role}: {user.get_username()}"
        for role, user in users
        if user is not None and not (user.email or "").strip()
    ]
    if missing:
        raise ValidationError(
            "Email Reviewer/Approver belum diisi: " + ", ".join(missing)
        )
    return [
        user.email
        for _role, user in users
        if user is not None and (user.email or "").strip()
    ]


def _notification_kpmr(report):
    if report.status not in {
        "submitted",
        "under_review",
        "approved",
    }:
        return None

    return calculate_kpmr_for_report(report)


def resolve_monthly_report_notification_recipients(
    report,
    stage=None,
    *,
    delivery_mode="auto",
    test_email_override="",
):
    if delivery_mode not in {"auto", "test", "final"}:
        raise ValidationError(
            "Mode pengiriman notifikasi tidak dikenal."
        )

    stage = stage or monthly_report_notification_stage(report)
    if not stage:
        raise ValidationError(
            "Status laporan tidak memerlukan notifikasi tahap berikutnya."
        )

    app_setting = AppSetting.get_solo()

    if delivery_mode == "test":
        test_email = (test_email_override or "").strip()
        if not test_email:
            raise ValidationError(
                "Email tujuan uji coba wajib diisi."
            )
        return {
            "recipients": [test_email],
            "cc_recipients": [],
            "bcc_recipients": [],
            "recipient": None,
            "recipient_names": [],
            "test_email": test_email,
        }

    if delivery_mode == "final":
        test_email = ""
    else:
        test_email = (
            ""
            if stage.get("ignore_test_email")
            else (
                app_setting.monthly_report_notification_test_email
                or ""
            ).strip()
        )

    if test_email:
        return {
            "recipients": [test_email],
            "cc_recipients": [],
            "bcc_recipients": [],
            "recipient": None,
            "recipient_names": [],
            "test_email": test_email,
        }

    def unique_users(users):
        result = []
        seen = set()

        for user in users or []:
            if user is None:
                continue

            key = getattr(user, "pk", None)
            if key is None:
                key = (
                    getattr(user, "email", "")
                    or getattr(user, "username", "")
                    or str(id(user))
                ).strip().casefold()

            if key in seen:
                continue

            seen.add(key)
            result.append(user)

        return result

    def emails_for(users, role_label):
        emails = []
        missing = []

        for user in unique_users(users):
            email = (getattr(user, "email", "") or "").strip()
            if email:
                emails.append(email)
                continue

            username = (
                user.get_username()
                if hasattr(user, "get_username")
                else str(user)
            )
            missing.append(username)

        if missing:
            import logging

            logging.getLogger(__name__).warning(
                "Penerima notifikasi dilewati karena email "
                "belum diisi. Peran=%s; pengguna=%s",
                role_label,
                ", ".join(missing),
            )

        return _merge_unique_emails(emails)

    status = report.status
    prepared_by = getattr(report, "prepared_by", None)
    reviewed_by = getattr(report, "reviewed_by", None)
    approved_by = getattr(report, "approved_by", None)

    stage_recipients = list(stage.get("recipients") or [])
    stage_recipient = stage.get("recipient")
    pairing = stage.get("bcc_recipient")

    prepared_users = (
        stage_recipients
        if stage_recipients
        else ([prepared_by] if prepared_by is not None else [])
    )

    if reviewed_by is None and status == "submitted":
        reviewed_by = stage_recipient

    if approved_by is None and status == "under_review":
        approved_by = stage_recipient

    pairing_users = [pairing] if pairing is not None else []

    to_users = []
    cc_users = []
    bcc_users = []

    if status in {"draft", "revision"}:
        to_users = prepared_users
        cc_users = [reviewed_by, approved_by]
        bcc_users = pairing_users
        to_emails = emails_for(to_users, "Prepared")

    elif status == "submitted":
        to_users = [reviewed_by]
        cc_users = [approved_by, *prepared_users]
        bcc_users = pairing_users
        to_emails = emails_for(to_users, "Reviewed")

    elif status == "under_review":
        to_users = [approved_by]
        cc_users = [reviewed_by, *prepared_users]
        bcc_users = pairing_users
        to_emails = emails_for(to_users, "Approved")

    elif status == "approved":
        approved_recipients = stage.get(
            "approved_recipients"
        )

        if approved_recipients is None:
            from .recipient_services import (
                build_approved_report_recipients,
            )

            approved_recipients = (
                build_approved_report_recipients(report)
            )

        to_emails = _merge_unique_emails(
            list(getattr(approved_recipients, "to", []) or []),
            list(getattr(approved_recipients, "cc", []) or []),
        )

        if not to_emails:
            reason = getattr(approved_recipients, "reason", "")
            raise ValidationError(
                reason
                or "Email Pairing dan atasan organisasi belum tersedia."
            )

        to_users = list(
            getattr(approved_recipients, "to_users", [])
            or pairing_users
        )
        cc_users = [
            approved_by,
            reviewed_by,
            *prepared_users,
        ]
        bcc_users = []

    else:
        raise ValidationError(
            f"Status laporan {status!r} belum memiliki konfigurasi penerima."
        )

    if not to_emails:
        raise ValidationError(
            "Penerima utama notifikasi belum tersedia."
        )

    cc_emails = _merge_unique_emails(
        emails_for(cc_users, "penerima CC"),
        excluded=to_emails,
    )

    bcc_emails = _merge_unique_emails(
        emails_for(bcc_users, "Pairing"),
        excluded=[*to_emails, *cc_emails],
    )

    to_users = unique_users(to_users)
    recipient = to_users[0] if to_users else None
    recipient_names = [
        user.get_full_name().strip() or user.get_username()
        for user in to_users
    ]

    return {
        "recipients": to_emails,
        "cc_recipients": cc_emails,
        "bcc_recipients": bcc_emails,
        "recipient": recipient,
        "recipient_names": recipient_names,
        "test_email": "",
    }



def send_monthly_report_notification(
    report,
    request=None,
    base_url=None,
    correction_note="",
    approved_transition=False,
    delivery_mode="auto",
    test_email_override="",
    subject_override="",
    instruction_override="",
):
    if delivery_mode not in {"auto", "test", "final"}:
        raise ValidationError("Mode pengiriman notifikasi tidak dikenal.")
    normalized_status = (report.status or "").strip().lower()
    if (
        normalized_status == "approved"
        and not approved_transition
        and delivery_mode == "auto"
    ):
        raise ValidationError(
            "Notifikasi Approved hanya dikirim saat transisi status menjadi "
            "Approved."
        )

    stage = monthly_report_notification_stage(report)
    if not stage:
        raise ValidationError(
            "Status laporan tidak memerlukan notifikasi tahap berikutnya."
        )

    correction_note = (correction_note or "").strip()
    if correction_note:
        if normalized_status != "revision":
            raise ValidationError(
                "Komentar koreksi hanya dapat dikirim untuk laporan "
                "berstatus Revision."
            )
        stage = {
            **stage,
            "title": "Koreksi Laporan Risiko Bulanan",
            "instruction": (
                "Laporan dikembalikan oleh reviewer/approver. "
                "Mohon Prepared by memperbaiki laporan sesuai komentar "
                "koreksi, kemudian melakukan Submit Ulang."
            ),
        }

    instruction_override = (instruction_override or "").strip()
    if instruction_override:
        stage = {**stage, "instruction": instruction_override}

    delivery = resolve_monthly_report_notification_recipients(
        report,
        stage=stage,
        delivery_mode=delivery_mode,
        test_email_override=test_email_override,
    )
    app_setting = AppSetting.get_solo()
    show_kpmr = normalized_status in {"submitted", "under_review", "approved"}
    kpmr = calculate_kpmr_for_report(report) if show_kpmr else None
    context = {
        "report": report,
        "stage": stage,
        "recipient": delivery["recipient"],
        "recipient_names": delivery["recipient_names"],
        "test_email": delivery["test_email"],
        "deadline": monthly_report_deadline(report),
        "deadline_text": format_indonesian_date(
            monthly_report_deadline(report)
        ),
        "report_url": monthly_report_admin_url(
            report,
            request=request,
            base_url=base_url,
        ),
        "app_setting": app_setting,
        "show_kpmr": show_kpmr,
        "kpmr_is_preview": show_kpmr and normalized_status != "approved",
        "kpmr": _notification_kpmr(report),
        "correction_note": correction_note,
        "tutorial": monthly_report_email_tutorial(),
    }
    subject = (
        (subject_override or "").strip()
        or f"{stage['title']} - {report.reassessment} "
        f"{report.periode.nama_periode}"
    )
    text_body = render_to_string(
        "monthly_report/email/notification.txt",
        context,
    )
    html_body = render_to_string(
        "monthly_report/email/notification.html",
        context,
    )
    from_email = (
        app_setting.default_from_email
        or getattr(settings, "DEFAULT_FROM_EMAIL", None)
    )

    message = EmailMultiAlternatives(
        subject,
        text_body,
        from_email,
        delivery["recipients"],
        cc=delivery["cc_recipients"],
        bcc=delivery["bcc_recipients"],
        connection=_mail_connection(app_setting),
    )
    message.attach_alternative(html_body, "text/html")
    return message.send()
