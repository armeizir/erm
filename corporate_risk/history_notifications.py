from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db.models import F
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from risk.models import AppSetting, PenugasanUnitBisnis

from .models import MonteCarloMetricHistory


def metric_history_input_url(history, request=None, base_url=None):
    path = reverse("metric_history_assigned_input", args=[history.pk])
    if request is not None:
        return request.build_absolute_uri(path)
    if base_url:
        return f"{base_url.rstrip('/')}{path}"
    return path


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


def metric_history_pairing_officer(history):
    # Kembalikan Pairing Officer aktif untuk unit histori metric.
    history = MonteCarloMetricHistory.objects.select_related(
        "assigned_to",
        "metric__rkap_item__unit_penanggung_jawab",
        "metric__corporate_risk_item__rkap_item__unit_penanggung_jawab",
    ).get(pk=history.pk)

    assigned_user = history.assigned_to
    candidate_units = []
    seen_unit_ids = set()

    def add_unit(unit):
        if unit and unit.pk not in seen_unit_ids:
            seen_unit_ids.add(unit.pk)
            candidate_units.append(unit)

    metric_rkap = history.metric.rkap_item
    add_unit(
        metric_rkap.unit_penanggung_jawab
        if metric_rkap
        else None
    )

    corporate_risk_rkap = history.metric.corporate_risk_item.rkap_item
    add_unit(
        corporate_risk_rkap.unit_penanggung_jawab
        if corporate_risk_rkap
        else None
    )

    if assigned_user:
        for role in (
            PenugasanUnitBisnis.ROLE_RISK_OFFICER,
            PenugasanUnitBisnis.ROLE_RISK_CHAMPION,
        ):
            for assignment in (
                PenugasanUnitBisnis.objects.filter(
                    user=assigned_user,
                    peran=role,
                    aktif=True,
                )
                .select_related("unit_bisnis")
                .order_by("id")
            ):
                add_unit(assignment.unit_bisnis)

        for unit in assigned_user.groups.order_by("name", "id"):
            add_unit(unit)

    assigned_email = (
        (assigned_user.email or "").strip().casefold()
        if assigned_user
        else ""
    )

    for unit in candidate_units:
        assignment = (
            PenugasanUnitBisnis.objects.filter(
                unit_bisnis=unit,
                peran=PenugasanUnitBisnis.ROLE_PAIRING_OFFICER,
                aktif=True,
                user__is_active=True,
            )
            .select_related("user")
            .order_by("id")
            .first()
        )
        if not assignment:
            continue

        pairing_user = assignment.user
        pairing_email = (pairing_user.email or "").strip()

        if (
            pairing_email
            and pairing_email.casefold() != assigned_email
        ):
            return pairing_user

    return None


def send_metric_history_assignment_notification(history, request=None, base_url=None):
    history = MonteCarloMetricHistory.objects.select_related(
        "assigned_to",
        "metric__corporate_risk_item",
        "metric__rkap_item__unit_penanggung_jawab",
        "metric__corporate_risk_item__rkap_item__unit_penanggung_jawab",
        "periode",
    ).get(pk=history.pk)
    user = history.assigned_to
    if not user:
        raise ValidationError("User pengisi data belum ditentukan.")
    if not user.is_active:
        raise ValidationError("User pengisi data tidak aktif.")
    if not user.email:
        raise ValidationError(f"Email user {user.get_username()} belum diisi.")

    pairing_officer = metric_history_pairing_officer(history)
    cc_recipients = (
        [(pairing_officer.email or "").strip()]
        if pairing_officer
        else []
    )

    app_setting = AppSetting.get_solo()
    context = {
        "history": history,
        "recipient": user,
        "pairing_officer": pairing_officer,
        "input_url": metric_history_input_url(history, request=request, base_url=base_url),
    }
    subject = f"Input Data Histori Risiko - {history.metric.name} - {history.periode.nama_periode}"
    message = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string("corporate_risk/email/metric_history_assignment.txt", context),
        from_email=app_setting.default_from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None),
        to=[user.email],
        cc=cc_recipients,
        connection=_mail_connection(app_setting),
    )
    message.attach_alternative(
        render_to_string("corporate_risk/email/metric_history_assignment.html", context),
        "text/html",
    )
    sent = message.send(fail_silently=False)
    if not sent:
        raise ValidationError("Server email tidak mengonfirmasi pengiriman notifikasi.")
    MonteCarloMetricHistory.objects.filter(pk=history.pk).update(
        notification_sent_at=timezone.now(),
        notification_count=F("notification_count") + 1,
    )
    return user.email
