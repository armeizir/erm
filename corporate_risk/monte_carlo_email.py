from __future__ import annotations

import re
from collections.abc import Iterable

from django import forms
from django.conf import settings
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.validators import validate_email
from django.template.loader import render_to_string

from .pdf_reports import render_multi_metric_pdf


MAX_RECIPIENTS = 50


class UserEmailChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        full_name = obj.get_full_name().strip()
        identity = full_name or obj.get_username()
        return f"{identity} — {obj.email}"


def _result_item_label(result) -> str:
    item = getattr(result, "corporate_risk_item", None)
    return str(item) if item is not None else f"Hasil #{result.pk}"


def _result_period_label(result) -> str:
    period = getattr(result, "forecast_periode", None)
    return str(period) if period is not None else "-"


def default_email_subject(result) -> str:
    subject = (
        f"Hasil Monte Carlo - {_result_item_label(result)} "
        f"- {_result_period_label(result)}"
    )
    return subject[:255]


def default_email_message(result) -> str:
    target_status = getattr(result, "target_status", None) or "-"
    risk_status = getattr(result, "risk_status", None) or "-"
    probability = getattr(
        result,
        "probability_not_achieve_target",
        None,
    )

    probability_text = (
        f"{float(probability):,.2f}%"
        if probability is not None
        else "-"
    )

    return (
        "Yth. Bapak/Ibu,\n\n"
        "Terlampir hasil analisis Multi Metric Monte Carlo ERM "
        "PLN Batam dengan informasi utama sebagai berikut:\n\n"
        f"Risiko: {_result_item_label(result)}\n"
        f"Periode forecast: {_result_period_label(result)}\n"
        f"Status target: {target_status}\n"
        f"Status risiko: {risk_status}\n"
        "Probabilitas target tidak tercapai: "
        f"{probability_text}\n\n"
        "Detail analisis, grafik, proyeksi, dan rekomendasi "
        "tercantum pada lampiran PDF.\n\n"
        "Salam,\n"
        "Enterprise Risk Management PLN Batam"
    )


class MultiMetricResultEmailForm(forms.Form):
    recipients = UserEmailChoiceField(
        queryset=get_user_model().objects.none(),
        required=False,
        label="Penerima dari Pengguna ERM",
        widget=FilteredSelectMultiple(
            "Penerima",
            is_stacked=False,
        ),
        help_text=(
            "Pilih satu atau beberapa pengguna aktif yang "
            "memiliki alamat email."
        ),
    )

    additional_emails = forms.CharField(
        required=False,
        label="Alamat Email Tambahan",
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": (
                    "contoh1@plnbatam.com; "
                    "contoh2@plnbatam.com"
                ),
            }
        ),
        help_text=(
            "Opsional. Pisahkan beberapa alamat dengan koma, "
            "titik koma, spasi, atau baris baru."
        ),
    )

    subject = forms.CharField(
        max_length=255,
        label="Subjek Email",
    )

    message = forms.CharField(
        label="Pesan Pengantar",
        widget=forms.Textarea(attrs={"rows": 12}),
    )

    def __init__(self, *args, result=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.result = result

        User = get_user_model()
        self.fields["recipients"].queryset = (
            User.objects.filter(is_active=True)
            .exclude(email__isnull=True)
            .exclude(email="")
            .order_by(
                "first_name",
                "last_name",
                "username",
            )
        )

        if not self.is_bound and result is not None:
            self.fields["subject"].initial = (
                default_email_subject(result)
            )
            self.fields["message"].initial = (
                default_email_message(result)
            )

    def clean_additional_emails(self):
        raw_value = self.cleaned_data.get(
            "additional_emails",
            "",
        )

        candidates = [
            value.strip()
            for value in re.split(r"[,;\s]+", raw_value)
            if value.strip()
        ]

        validated = []

        for email in candidates:
            validate_email(email)
            validated.append(email.lower())

        return validated

    def clean(self):
        cleaned_data = super().clean()

        selected_users = cleaned_data.get("recipients")
        manual_emails = cleaned_data.get(
            "additional_emails",
            [],
        )

        addresses = []

        if selected_users:
            for user in selected_users:
                if user.email:
                    addresses.append(user.email.strip().lower())

        addresses.extend(manual_emails)

        # Deduplikasi dengan mempertahankan urutan.
        unique_addresses = list(dict.fromkeys(addresses))

        if not unique_addresses:
            raise forms.ValidationError(
                "Pilih minimal satu penerima atau isi alamat "
                "email tambahan."
            )

        if len(unique_addresses) > MAX_RECIPIENTS:
            raise forms.ValidationError(
                f"Jumlah penerima maksimal {MAX_RECIPIENTS} "
                "alamat email."
            )

        cleaned_data["recipient_emails"] = unique_addresses
        return cleaned_data


def send_multi_metric_result_email(
    *,
    result,
    recipients: Iterable[str],
    subject: str,
    body: str,
    sent_by=None,
    result_url: str = "",
) -> int:
    recipient_list = list(dict.fromkeys(
        address.strip().lower()
        for address in recipients
        if address and address.strip()
    ))

    if not recipient_list:
        raise ValueError("Penerima email belum tersedia.")

    if len(recipient_list) > MAX_RECIPIENTS:
        raise ValueError(
            f"Jumlah penerima maksimal {MAX_RECIPIENTS}."
        )

    # PDF dibuat satu kali dari hasil yang telah tersimpan.
    # Simulasi Monte Carlo tidak dijalankan ulang.
    pdf_bytes = render_multi_metric_pdf(result)

    if not pdf_bytes:
        raise RuntimeError(
            "PDF hasil Monte Carlo gagal dibuat."
        )

    filename = (
        f"multi_metric_monte_carlo_result_{result.pk}.pdf"
    )

    context = {
        "result": result,
        "body": body,
        "result_url": result_url,
        "sent_by": sent_by,
    }

    text_body = render_to_string(
        "corporate_risk/email/"
        "multi_metric_monte_carlo_result.txt",
        context,
    )

    html_body = render_to_string(
        "corporate_risk/email/"
        "multi_metric_monte_carlo_result.html",
        context,
    )

    from_email = getattr(
        settings,
        "DEFAULT_FROM_EMAIL",
        None,
    )

    connection = get_connection()
    messages = []

    # Dibuat sebagai email terpisah agar penerima tidak
    # melihat alamat penerima lainnya.
    for recipient in recipient_list:
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=from_email,
            to=[recipient],
        )
        email.attach_alternative(html_body, "text/html")
        email.attach(
            filename,
            pdf_bytes,
            "application/pdf",
        )
        messages.append(email)

    sent_count = connection.send_messages(messages)

    if sent_count != len(messages):
        raise RuntimeError(
            f"Email terkirim {sent_count} dari "
            f"{len(messages)} penerima."
        )

    return sent_count
