from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from risk.models import AppSetting

from .models import AwarenessAttempt, AwarenessCampaign


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


def active_awareness_campaigns(at=None):
    at = at or timezone.localdate()
    return AwarenessCampaign.objects.filter(
        is_active=True,
        start_date__lte=at,
        end_date__gte=at,
    ).order_by("-start_date", "title")


def pending_awareness_users(campaign):
    attempted_ids = AwarenessAttempt.objects.filter(campaign=campaign).values_list("user_id", flat=True)
    return (
        get_user_model()
        .objects
        .filter(is_active=True, email__isnull=False)
        .exclude(email="")
        .exclude(id__in=attempted_ids)
        .order_by("username")
    )


def awareness_base_url(request=None, base_url=None):
    if request:
        return request.build_absolute_uri("/").rstrip("/")
    if base_url:
        return base_url.rstrip("/")
    configured = getattr(settings, "AWARENESS_BASE_URL", "") or getattr(settings, "BASE_URL", "")
    if configured:
        return configured.rstrip("/")
    hosts = [host for host in getattr(settings, "ALLOWED_HOSTS", []) if host and host != "*"]
    host = hosts[0] if hosts else "127.0.0.1:8001"
    scheme = "http" if host.startswith(("localhost", "127.", "[::1]")) else "https"
    return f"{scheme}://{host}".rstrip("/")


def campaign_material_url(campaign, request=None, base_url=None):
    return f"{awareness_base_url(request=request, base_url=base_url)}{reverse('awareness:campaign_material', args=[campaign.pk])}"


def campaign_participants_url(campaign, request=None, base_url=None):
    return f"{awareness_base_url(request=request, base_url=base_url)}{reverse('awareness:campaign_participants', args=[campaign.pk])}"


def campaign_period_text(campaign):
    start = campaign.start_date
    end = campaign.end_date
    if start.month == end.month and start.year == end.year:
        return f"{start.day} s/d {end.day} {MONTH_NAMES[end.month]} {end.year}"
    return (
        f"{start.day} {MONTH_NAMES[start.month]} {start.year} "
        f"s/d {end.day} {MONTH_NAMES[end.month]} {end.year}"
    )


def campaign_subject(campaign):
    month_label = f"{MONTH_NAMES[campaign.start_date.month]} {campaign.start_date.year}"
    return f"Pelaksanaan {campaign.title} Bulan {month_label}"


def _progress_color(percent):
    if percent >= 80:
        return "#169c43"
    if percent >= 60:
        return "#f4b400"
    return "#e6354f"


def awareness_progress_rows(campaign):
    User = get_user_model()
    completed_statuses = [
        AwarenessAttempt.STATUS_SUBMITTED,
        AwarenessAttempt.STATUS_PASSED,
        AwarenessAttempt.STATUS_FAILED,
        AwarenessAttempt.STATUS_EXPIRED,
    ]
    responded_ids = set(
        AwarenessAttempt.objects.filter(campaign=campaign, status__in=completed_statuses)
        .values_list("user_id", flat=True)
        .distinct()
    )
    unit_targets = list(campaign.unit_targets.filter(is_active=True).order_by("order", "unit_name"))
    if unit_targets:
        rows = []
        total_employee_count = 0
        total_respondent_count = 0
        for target in unit_targets:
            member_ids = set(
                User.objects.filter(
                    is_active=True,
                    groups__name__iexact=target.unit_name,
                ).values_list("id", flat=True)
            )
            # Target manual merepresentasikan jumlah pegawai dalam unit
            # organisasi. Penugasan lintas unit (misalnya pairing officer MRK)
            # tidak mengubah unit asal pegawai dan tidak boleh menambah jumlah
            # responden unit pada email awareness.
            respondent_count = len(member_ids & responded_ids)
            employee_count = target.employee_count
            pending_count = max(employee_count - respondent_count, 0)
            percent = min(round((respondent_count / employee_count) * 100), 100) if employee_count else 0
            total_employee_count += employee_count
            total_respondent_count += respondent_count
            rows.append({
                "unit": target.unit_name,
                "employee_count": employee_count,
                "respondent_count": respondent_count,
                "pending_count": pending_count,
                "percent": percent,
                "color": _progress_color(percent),
                "highlight": percent >= 100,
            })

        total_pending_count = max(total_employee_count - total_respondent_count, 0)
        total_percent = min(round((total_respondent_count / total_employee_count) * 100), 100) if total_employee_count else 0
        return {
            "rows": rows,
            "total": {
                "employee_count": total_employee_count,
                "respondent_count": total_respondent_count,
                "pending_count": total_pending_count,
                "percent": total_percent,
                "color": _progress_color(total_percent),
            },
        }

    groups = Group.objects.exclude(name__startswith="ROLE -").order_by("name")
    rows = []
    total_user_ids = set()
    total_responded_ids = set()

    for group in groups:
        member_ids = set(
            User.objects.filter(is_active=True, groups=group).values_list("id", flat=True)
        )
        # Unit organisasi Awareness mengikuti group pengguna. Penugasan lintas
        # unit hanya menentukan peran pada workflow risiko dan tidak memindahkan
        # pegawai ke unit tempat ia ditugaskan.
        user_ids = member_ids
        if not user_ids:
            continue

        unit_responded_ids = user_ids & responded_ids
        employee_count = len(user_ids)
        respondent_count = len(unit_responded_ids)
        pending_count = max(employee_count - respondent_count, 0)
        percent = round((respondent_count / employee_count) * 100) if employee_count else 0
        total_user_ids.update(user_ids)
        total_responded_ids.update(unit_responded_ids)
        rows.append({
            "unit": group.name,
            "employee_count": employee_count,
            "respondent_count": respondent_count,
            "pending_count": pending_count,
            "percent": percent,
            "color": _progress_color(percent),
            "highlight": percent >= 100,
        })

    total_employee_count = len(total_user_ids)
    total_respondent_count = len(total_responded_ids)
    total_pending_count = max(total_employee_count - total_respondent_count, 0)
    total_percent = round((total_respondent_count / total_employee_count) * 100) if total_employee_count else 0
    return {
        "rows": rows,
        "total": {
            "employee_count": total_employee_count,
            "respondent_count": total_respondent_count,
            "pending_count": total_pending_count,
            "percent": total_percent,
            "color": _progress_color(total_percent),
        },
    }


def send_awareness_notification(campaign, recipients, request=None, base_url=None):
    recipients = [email for email in recipients if email]
    if not recipients:
        return 0

    app_setting = AppSetting.get_solo()
    progress = awareness_progress_rows(campaign)
    context = {
        "campaign": campaign,
        "app_setting": app_setting,
        "material_url": campaign_material_url(campaign, request=request, base_url=base_url),
        "participants_url": campaign_participants_url(campaign, request=request, base_url=base_url),
        "period_text": campaign_period_text(campaign),
        "month_year": f"{MONTH_NAMES[campaign.start_date.month]} {campaign.start_date.year}",
        "email_heading": campaign.email_heading,
        "email_subheading": campaign.email_subheading,
        "progress_rows": progress["rows"],
        "progress_total": progress["total"],
        "footer_year": campaign.start_date.year,
    }
    subject = campaign_subject(campaign)
    text_body = render_to_string("awareness/email/notification.txt", context)
    html_body = render_to_string("awareness/email/notification.html", context)
    from_email = app_setting.default_from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None)
    connection = None
    if app_setting.email_smtp_aktif and app_setting.email_host:
        connection = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=app_setting.email_host,
            port=app_setting.email_port,
            username=app_setting.email_host_user or None,
            password=app_setting.email_host_password or None,
            use_tls=app_setting.email_use_tls,
            use_ssl=app_setting.email_use_ssl,
        )

    message = EmailMultiAlternatives(subject, text_body, from_email, recipients, connection=connection)
    message.attach_alternative(html_body, "text/html")
    return message.send()
