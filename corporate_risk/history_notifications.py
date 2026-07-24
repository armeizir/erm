from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db.models import F
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from risk.models import AppSetting

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


def send_metric_history_assignment_notification(history, request=None, base_url=None):
    history = MonteCarloMetricHistory.objects.select_related(
        "assigned_to", "metric__corporate_risk_item", "periode"
    ).get(pk=history.pk)
    user = history.assigned_to
    if not user:
        raise ValidationError("User pengisi data belum ditentukan.")
    if not user.is_active:
        raise ValidationError("User pengisi data tidak aktif.")
    if not user.email:
        raise ValidationError(f"Email user {user.get_username()} belum diisi.")
    app_setting = AppSetting.get_solo()
    context = {
        "history": history,
        "recipient": user,
        "input_url": metric_history_input_url(history, request=request, base_url=base_url),
    }
    subject = f"Input Data Histori Risiko - {history.metric.name} - {history.periode.nama_periode}"
    message = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string("corporate_risk/email/metric_history_assignment.txt", context),
        from_email=app_setting.default_from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None),
        to=[user.email],
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
