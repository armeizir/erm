import hashlib
import json
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.validators import validate_email
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from risk.models import (
    AppSetting,
    PenugasanUnitBisnis,
    ProfileCompletenessNotificationLog,
    ReAssessmentSummary,
)


@dataclass(frozen=True)
class Finding:
    section: str
    severity: str
    message: str
    item_id: int | None = None
    item_label: str = ""


@dataclass
class CompletenessResult:
    profile: ReAssessmentSummary
    findings: list[Finding] = field(default_factory=list)

    @property
    def is_complete(self):
        return not self.findings

    @property
    def error_count(self):
        return sum(item.severity == "error" for item in self.findings)

    @property
    def warning_count(self):
        return sum(item.severity == "warning" for item in self.findings)

    @property
    def fingerprint(self):
        payload = [
            (item.section, item.severity, item.item_id, item.message)
            for item in self.findings
        ]
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()

    def grouped(self):
        grouped = {}
        for finding in self.findings:
            grouped.setdefault(finding.section, []).append(finding)
        return grouped

    def as_dict(self):
        return {
            "is_complete": self.is_complete,
            "profile_errors": [f.message for f in self.findings if not f.item_id],
            "item_errors": [f.message for f in self.findings if f.item_id],
            "warning_count": self.warning_count,
            "error_count": self.error_count,
        }


def profile_completeness_queryset():
    return ReAssessmentSummary.objects.select_related(
        "unit_bisnis", "kontrak_manajemen", "rkm", "risk_matrix"
    ).prefetch_related(
        "item__taksonomi_t3",
        "item__sasaran_kbumn",
        "item__kategori_risiko",
        "item__skala_probabilitas",
        "item__skala_dampak_q1", "item__skala_dampak_q2",
        "item__skala_dampak_q3", "item__skala_dampak_q4",
        "item__skala_probabilitas_q1", "item__skala_probabilitas_q2",
        "item__skala_probabilitas_q3", "item__skala_probabilitas_q4",
    )


def check_profile_completeness(profile):
    findings = []

    def add(section, severity, message, item=None):
        label = ""
        if item:
            label = f"Item {item.no_item or '-'} – {(item.peristiwa_risiko or 'Tanpa peristiwa').strip()}"
        findings.append(Finding(section, severity, message, getattr(item, "pk", None), label))

    if not (profile.judul or "").strip():
        add("Data Profil", "error", "Judul Profil Risiko belum diisi.")
    if not profile.tahun or profile.tahun < 2000 or profile.tahun > 2100:
        add("Data Profil", "error", "Tahun profil kosong atau tidak valid.")
    if not profile.unit_bisnis_id:
        add("Data Profil", "error", "Bidang/Unit Bisnis belum dipilih.")
    if not profile.kontrak_manajemen_id:
        add("Data Profil", "error", "Kontrak Manajemen belum dipilih.")
    if not profile.risk_matrix_id:
        add("Data Profil", "error", "Matriks Risiko belum dipilih.")
    if not profile.rkm_id:
        add("Data Profil", "error", "RKM belum dipilih.")
    if profile.kontrak_manajemen_id:
        if profile.kontrak_manajemen.tahun != profile.tahun:
            add("Data Profil", "warning", "Tahun Kontrak Manajemen tidak sama dengan tahun profil.")
        if profile.unit_bisnis_id and profile.kontrak_manajemen.unit_bisnis_id != profile.unit_bisnis_id:
            add("Data Profil", "error", "Unit Kontrak Manajemen tidak sama dengan unit profil.")
    if profile.rkm_id:
        if profile.rkm.tahun != profile.tahun:
            add("Data Profil", "warning", "Tahun RKM tidak sama dengan tahun profil.")
        if profile.unit_bisnis_id and profile.rkm.unit_bisnis_id != profile.unit_bisnis_id:
            add("Data Profil", "error", "Unit RKM tidak sama dengan unit profil.")

    items = list(profile.item.all())
    if not items:
        add("Item Risiko", "error", "Profil belum memiliki item risiko.")
        return CompletenessResult(profile, findings)

    by_number = {}
    by_event = {}
    likely_duplicates = {}
    for item in items:
        if not item.no_item:
            add("Item Risiko", "error", "Nomor item belum diisi.", item)
        else:
            by_number.setdefault(item.no_item, []).append(item)
        event = (item.peristiwa_risiko or "").strip()
        if not event:
            add("Item Risiko", "error", "Peristiwa Risiko belum diisi.", item)
        else:
            by_event.setdefault(event.casefold(), []).append(item)
        if not item.taksonomi_t3_id:
            add("Item Risiko", "error", "Taksonomi Risiko PLN T3 belum diisi.", item)
        if not item.sasaran_kbumn_id:
            add("Item Risiko", "error", "Sasaran KBUMN belum diisi.", item)
        if not item.kategori_risiko_id:
            add("Item Risiko", "error", "Kategori Risiko belum diisi.", item)
        if item.unit_bisnis_id != profile.unit_bisnis_id or item.summary_id != profile.pk:
            add("Item Risiko", "error", "Relasi unit atau profil item tidak konsisten.", item)
        if item.nilai_dampak is None:
            add("Data Inheren", "error", "Nilai Dampak Risiko Inheren belum diisi.", item)
        if item.nilai_probabilitas is None:
            add("Data Inheren", "error", "Nilai Probabilitas Risiko Inheren belum diisi.", item)
        if not item.skala_probabilitas_id:
            add("Data Inheren", "error", "Skala Probabilitas Risiko Inheren belum diisi.", item)
        if not (item.penyebab_risiko or "").strip():
            add("Item Risiko", "error", "Penyebab Risiko belum diisi.", item)
        if not (item.rencana_perlakuan_risiko or "").strip():
            add("Item Risiko", "error", "Rencana Perlakuan Risiko belum diisi.", item)
        kri_parts = [item.key_risk_indicators, item.unit_satuan_kri, item.threshold_aman,
                     item.threshold_hati_hati, item.threshold_bahaya, item.kri_threshold_direction]
        if any(value not in (None, "") for value in kri_parts) and not all(
            value not in (None, "") for value in kri_parts
        ):
            add("Item Risiko", "error", "Konfigurasi KRI belum lengkap.", item)
        for quarter in range(1, 5):
            required = (
                (f"nilai_dampak_q{quarter}", "Nilai Dampak"),
                (f"skala_dampak_q{quarter}_id", "Skala Dampak"),
                (f"nilai_probabilitas_q{quarter}", "Nilai Probabilitas"),
                (f"skala_probabilitas_q{quarter}_id", "Skala Probabilitas"),
                (f"skala_risiko_q{quarter}", "Skala Risiko"),
                (f"level_nilai_risiko_q{quarter}", "Level Risiko"),
                (f"eksposur_risiko_q{quarter}", "Target Eksposur Risiko"),
            )
            for attribute, label in required:
                if getattr(item, attribute, None) in (None, ""):
                    add("Target Residual/Reassessment", "error", f"{label} Q{quarter} belum tersedia.", item)
        signature = (event.casefold(), item.taksonomi_t3_id, item.sasaran_kbumn_id, item.kategori_risiko_id)
        likely_duplicates.setdefault(signature, []).append(item)

    for number, duplicates in by_number.items():
        if len(duplicates) > 1:
            add("Duplikasi atau Ketidakkonsistenan", "warning", f"Nomor item {number} digunakan pada beberapa risiko.")
    for event, duplicates in by_event.items():
        if len(duplicates) > 1:
            add("Duplikasi atau Ketidakkonsistenan", "warning", f"Peristiwa risiko yang sama tercatat {len(duplicates)} kali: {duplicates[0].peristiwa_risiko}.")
    for signature, duplicates in likely_duplicates.items():
        if signature[0] and len(duplicates) > 1:
            add("Duplikasi atau Ketidakkonsistenan", "warning", f"{len(duplicates)} item memiliki peristiwa, taksonomi, sasaran, dan kategori yang sama.")
    numbers = sorted(by_number)
    if numbers and numbers != list(range(numbers[0], numbers[-1] + 1)):
        add("Duplikasi atau Ketidakkonsistenan", "warning", "Urutan nomor item memiliki celah dan perlu diverifikasi.")
    return CompletenessResult(profile, findings)


def _valid_email(user):
    if not user.is_active or not (user.email or "").strip():
        return ""
    email = user.email.strip().casefold()
    try:
        validate_email(email)
    except ValidationError:
        return ""
    return email


def resolve_profile_recipients(profile):
    assignments = PenugasanUnitBisnis.objects.filter(
        unit_bisnis_id=profile.unit_bisnis_id, aktif=True,
        peran__in=(PenugasanUnitBisnis.ROLE_RISK_OFFICER, PenugasanUnitBisnis.ROLE_PAIRING_OFFICER),
    ).select_related("user").order_by("user__username")
    officers, pairings, warnings = [], [], []
    for assignment in assignments:
        email = _valid_email(assignment.user)
        if not email:
            continue
        target = officers if assignment.peran == PenugasanUnitBisnis.ROLE_RISK_OFFICER else pairings
        if email not in [entry["email"] for entry in target]:
            target.append({"id": assignment.user_id, "name": assignment.user.get_full_name().strip() or assignment.user.username, "email": email})
    to = [entry["email"] for entry in officers]
    cc = [entry["email"] for entry in pairings if entry["email"] not in to]
    app_setting = AppSetting.objects.first()
    if not to:
        fallback = _valid_config_email(getattr(app_setting, "support_email", ""))
        if fallback:
            to = [fallback]
        warnings.append("Risk Officer unit belum ditetapkan atau tidak memiliki email valid.")
    if not cc:
        warnings.append(f"Pairing untuk unit {profile.unit_bisnis.name} belum ditetapkan.")
    return {"to": to, "cc": cc, "officers": officers, "pairings": pairings, "warnings": warnings}


def _valid_config_email(value):
    value = (value or "").strip().casefold()
    if not value:
        return ""
    try:
        validate_email(value)
    except ValidationError:
        return ""
    return value


def profile_admin_url(profile, base_url=None):
    path = reverse("admin:risk_reassessmentsummary_change", args=[profile.pk])
    base = (base_url or getattr(settings, "APP_BASE_URL", "") or getattr(settings, "SITE_URL", "")).rstrip("/")
    return f"{base}{path}" if base else path


def profile_mail_connection():
    app_setting = AppSetting.objects.first()
    if app_setting and app_setting.email_smtp_aktif and app_setting.email_host:
        return get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=app_setting.email_host,
            port=app_setting.email_port,
            username=app_setting.email_host_user or None,
            password=app_setting.runtime_email_host_password or None,
            use_tls=app_setting.email_use_tls,
            use_ssl=app_setting.email_use_ssl,
        )
    return get_connection()


def should_send_notification(result, recipients, force=False, now=None):
    if result.is_complete or not recipients["to"]:
        return False, "Profil lengkap" if result.is_complete else "Penerima utama tidak tersedia"
    if force:
        return True, "Dipaksa"
    now = now or timezone.now()
    recipient_key = sorted(recipients["to"] + recipients["cc"])
    recent = ProfileCompletenessNotificationLog.objects.filter(
        profile=result.profile, issue_fingerprint=result.fingerprint,
        status=ProfileCompletenessNotificationLog.STATUS_SENT,
        sent_at__gte=now - timedelta(days=3),
        recipient_to=recipients["to"], recipient_cc=recipients["cc"],
    ).exists()
    return (not recent, "Temuan sama sudah dikirim dalam 3 hari" if recent else "Temuan baru/berubah")


def close_resolved_notifications(profile):
    return profile.completeness_notification_logs.filter(
        status=ProfileCompletenessNotificationLog.STATUS_SENT, resolved_at__isnull=True
    ).update(status=ProfileCompletenessNotificationLog.STATUS_RESOLVED, resolved_at=timezone.now())


def log_undeliverable_notification(result, recipients, message):
    return ProfileCompletenessNotificationLog.objects.create(
        profile=result.profile,
        unit_bisnis=result.profile.unit_bisnis,
        recipient_to=recipients["to"],
        recipient_cc=recipients["cc"],
        risk_officer_ids=[entry["id"] for entry in recipients["officers"]],
        pairing_ids=[entry["id"] for entry in recipients["pairings"]],
        issue_fingerprint=result.fingerprint,
        issue_count=len(result.findings),
        status=ProfileCompletenessNotificationLog.STATUS_FAILED,
        error_message=message,
    )


def send_profile_completeness_notification(result, recipients, base_url=None, connection=None):
    context = {
        "profile": result.profile, "result": result, "groups": result.grouped(),
        "recipients": recipients, "profile_url": profile_admin_url(result.profile, base_url),
    }
    subject = f"[ERM PLN Batam] Perbaikan Kelengkapan Profil Risiko – {result.profile.unit_bisnis.name} – {result.profile.tahun}"
    app_setting = AppSetting.objects.first()
    message = EmailMultiAlternatives(
        subject,
        render_to_string("risk/email/profile_completeness.txt", context),
        getattr(app_setting, "default_from_email", "") or settings.DEFAULT_FROM_EMAIL,
        recipients["to"], cc=recipients["cc"], connection=connection or profile_mail_connection(),
    )
    message.attach_alternative(render_to_string("risk/email/profile_completeness.html", context), "text/html")
    now = timezone.now()
    try:
        sent = message.send()
        status = ProfileCompletenessNotificationLog.STATUS_SENT if sent else ProfileCompletenessNotificationLog.STATUS_FAILED
        error = "" if sent else "Backend email tidak mengirim pesan."
    except Exception as exc:
        sent, status, error = 0, ProfileCompletenessNotificationLog.STATUS_FAILED, str(exc)[:2000]
    ProfileCompletenessNotificationLog.objects.create(
        profile=result.profile, unit_bisnis=result.profile.unit_bisnis,
        recipient_to=recipients["to"], recipient_cc=recipients["cc"],
        risk_officer_ids=[entry["id"] for entry in recipients["officers"]],
        pairing_ids=[entry["id"] for entry in recipients["pairings"]],
        issue_fingerprint=result.fingerprint, issue_count=len(result.findings),
        status=status, sent_at=now if sent else None, error_message=error,
    )
    return bool(sent), error
