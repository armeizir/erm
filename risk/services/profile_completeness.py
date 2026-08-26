import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.validators import validate_email
from django.db.models import OuterRef, Subquery
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from risk.models import (
    AppSetting,
    KnowledgeBaseArticle,
    PenugasanUnitBisnis,
    ProfileCompletenessAssessment,
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
    required_count: int = 0
    completed_count: int = 0

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
    def incomplete_count(self):
        return max(self.required_count - self.completed_count, 0)

    @property
    def percentage(self):
        if not self.required_count:
            return Decimal("100.00")
        return (
            Decimal(self.completed_count) * Decimal("100") / Decimal(self.required_count)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def percentage_display(self):
        return f"{self.percentage:.2f}".replace(".", ",") + "%"

    @property
    def status_label(self):
        complete = Decimal(str(getattr(settings, "PROFILE_COMPLETENESS_COMPLETE_THRESHOLD", 100)))
        almost = Decimal(str(getattr(settings, "PROFILE_COMPLETENESS_ALMOST_THRESHOLD", 80)))
        if self.percentage >= complete:
            return "Lengkap"
        if self.percentage >= almost:
            return "Hampir Lengkap"
        return "Perlu Perbaikan"

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
            "required_count": self.required_count,
            "completed_count": self.completed_count,
            "incomplete_count": self.incomplete_count,
            "percentage": str(self.percentage),
            "status": self.status_label,
        }


def _is_filled(value):
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def is_qualitative_risk(item):
    value = str(getattr(item, "kategori_dampak", "") or "").casefold()
    normalized = re.sub(r"[^a-z]", "", value)
    return "kualitatif" in normalized or "kualilatif" in normalized


def profile_completeness_queryset():
    return ReAssessmentSummary.objects.select_related(
        "unit_bisnis", "kontrak_manajemen", "rkm", "risk_matrix"
    ).prefetch_related(
        "item__taksonomi_t3",
        "item__sasaran_kbumn",
        "item__kategori_risiko",
        "item__kategori_dampak",
        "item__skala_probabilitas",
        "item__skala_dampak_q1", "item__skala_dampak_q2",
        "item__skala_dampak_q3", "item__skala_dampak_q4",
        "item__skala_probabilitas_q1", "item__skala_probabilitas_q2",
        "item__skala_probabilitas_q3", "item__skala_probabilitas_q4",
    )


def latest_profile_revisions(queryset=None):
    """Satu revision terbaru per unit/tahun untuk layar monitoring."""
    queryset = queryset if queryset is not None else ReAssessmentSummary.objects.all()
    latest = ReAssessmentSummary.objects.filter(
        unit_bisnis_id=OuterRef("unit_bisnis_id"), tahun=OuterRef("tahun")
    ).order_by("-dibuat_pada", "-pk").values("pk")[:1]
    return queryset.filter(pk=Subquery(latest))


# PROFILE_COMPLETENESS_CAUSE_IDENTITY_V3
def _profile_identity_text(value):
    return " ".join(str(value or "").split()).casefold()


def _risk_cause_identity(item):
    return (
        getattr(item, "no_item", None),
        getattr(item, "no_risiko", None),
        _profile_identity_text(getattr(item, "peristiwa_risiko", "")),
        getattr(item, "no_penyebab_risiko", None),
        _profile_identity_text(getattr(item, "penyebab_risiko", "")),
    )


def check_profile_completeness(profile):
    findings = []
    required_count = completed_count = 0

    def add(section, severity, message, item=None):
        label = ""
        if item:
            label = f"Item {item.no_item or '-'} – {(item.peristiwa_risiko or 'Tanpa peristiwa').strip()}"
        findings.append(Finding(section, severity, message, getattr(item, "pk", None), label))

    def require(value, section, message, item=None):
        nonlocal required_count, completed_count
        required_count += 1
        if _is_filled(value):
            completed_count += 1
            return True
        add(section, "error", message, item)
        return False

    require(profile.judul, "Data Profil", "Judul Profil Risiko belum diisi.")
    require(profile.tahun if profile.tahun and 2000 <= profile.tahun <= 2100 else None, "Data Profil", "Tahun profil kosong atau tidak valid.")
    require(profile.unit_bisnis_id, "Data Profil", "Bidang/Unit Bisnis belum dipilih.")
    require(profile.kontrak_manajemen_id, "Kontrak Manajemen / Sasaran", "Kontrak Manajemen belum dipilih.")
    require(profile.risk_matrix_id, "Data Profil", "Matriks Risiko belum dipilih.")
    require(profile.rkm_id, "Kontrak Manajemen / Sasaran", "RKM belum dipilih.")
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

    items = list(profile.item.filter(is_active=True))
    if not items:
        add("Item Risiko", "error", "Profil belum memiliki item risiko.")
        return CompletenessResult(profile, findings, required_count, completed_count)

    by_number = {}
    by_event = {}
    likely_duplicates = {}
    for item in items:
        if require(item.no_item, "Data Risiko", "Nomor item belum diisi.", item):
            by_number.setdefault(item.no_item, []).append(item)
        event = (item.peristiwa_risiko or "").strip()
        if require(event, "Data Risiko", "Peristiwa Risiko belum diisi.", item):
            by_event.setdefault(event.casefold(), []).append(item)
        require(item.taksonomi_t3_id, "Data Risiko", "Taksonomi Risiko PLN T3 belum diisi.", item)
        require(item.sasaran_kbumn_id, "Kontrak Manajemen / Sasaran", "Sasaran KBUMN belum diisi.", item)
        require(item.kategori_risiko_id, "Data Risiko", "Kategori Risiko belum diisi.", item)
        if item.unit_bisnis_id != profile.unit_bisnis_id or item.summary_id != profile.pk:
            add("Item Risiko", "error", "Relasi unit atau profil item tidak konsisten.", item)
        qualitative = is_qualitative_risk(item)
        if not qualitative:
            require(item.nilai_dampak, "Risiko Inheren", "Nilai Dampak Risiko Inheren belum diisi.", item)
            require(item.nilai_probabilitas, "Risiko Inheren", "Nilai Probabilitas Risiko Inheren belum diisi.", item)
        require(item.skala_probabilitas_id, "Risiko Inheren", "Skala Probabilitas Risiko Inheren belum diisi.", item)
        require(item.penyebab_risiko, "Penyebab Risiko", "Penyebab Risiko belum diisi.", item)
        require(item.rencana_perlakuan_risiko, "Rencana Perlakuan Risiko", "Rencana Perlakuan Risiko belum diisi.", item)
        kri_parts = [item.key_risk_indicators, item.unit_satuan_kri, item.threshold_aman,
                     item.threshold_hati_hati, item.threshold_bahaya, item.kri_threshold_direction]
        if any(value not in (None, "") for value in kri_parts) and not all(
            value not in (None, "") for value in kri_parts
        ):
            for value in kri_parts:
                require(value, "KRI", "Konfigurasi KRI belum lengkap.", item)
        for quarter in range(1, 5):
            # Eksposur Risiko adalah derived field:
            # Nilai Dampak x Nilai Probabilitas.
            # Karena dihitung otomatis oleh model, exposure bukan input
            # mandatory pada Profile Completeness.
            required = (
                (f"nilai_dampak_q{quarter}", "Nilai Dampak"),
                (f"skala_dampak_q{quarter}_id", "Skala Dampak"),
                (f"nilai_probabilitas_q{quarter}", "Nilai Probabilitas"),
                (f"skala_probabilitas_q{quarter}_id", "Skala Probabilitas"),
                (f"skala_risiko_q{quarter}", "Skala Risiko"),
                (f"level_nilai_risiko_q{quarter}", "Level Risiko"),
            )
            for attribute, label in required:
                if qualitative and attribute.startswith(("nilai_dampak_", "nilai_probabilitas_")):
                    continue
                require(getattr(item, attribute, None), "Risiko Residual", f"{label} Q{quarter} belum tersedia.", item)
        signature = (event.casefold(), item.taksonomi_t3_id, item.sasaran_kbumn_id, item.kategori_risiko_id)
        likely_duplicates.setdefault(signature, []).append(item)

    # no_item boleh berulang: satu KPI dapat memiliki beberapa risk event,
    # dan satu risk event dapat memiliki beberapa cause/penyebab.
    # Karena itu by_number/by_event/signature bukan bukti duplikasi.
    exact_risk_causes = {}
    for item in items:
        identity = _risk_cause_identity(item)
        if identity[2] and identity[4]:
            exact_risk_causes.setdefault(identity, []).append(item)

    for identity, duplicates in exact_risk_causes.items():
        if len(duplicates) > 1:
            add(
                "Duplikasi atau Ketidakkonsistenan",
                "warning",
                (
                    f"Risiko dan penyebab yang sama tercatat {len(duplicates)} kali: "
                    f"{duplicates[0].peristiwa_risiko} / "
                    f"{duplicates[0].penyebab_risiko}."
                ),
            )

    numbers = sorted(by_number)
    if numbers and numbers != list(range(numbers[0], numbers[-1] + 1)):
        add("Duplikasi atau Ketidakkonsistenan", "warning", "Urutan nomor item memiliki celah dan perlu diverifikasi.")
    return CompletenessResult(profile, findings, required_count, completed_count)


def record_profile_assessment(result, triggered_by=None):
    previous = result.profile.completeness_assessments.order_by("-reviewed_at").first()
    snapshot = ProfileCompletenessAssessment.objects.create(
        profile=result.profile,
        unit_bisnis=result.profile.unit_bisnis,
        tahun=result.profile.tahun,
        percentage=result.percentage,
        required_count=result.required_count,
        completed_count=result.completed_count,
        finding_count=len(result.findings),
        issue_fingerprint=result.fingerprint,
        triggered_by=triggered_by if getattr(triggered_by, "is_authenticated", False) else None,
    )
    return snapshot, previous


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


def profile_completeness_email_tutorial():
    return (
        KnowledgeBaseArticle.objects.filter(
            status=KnowledgeBaseArticle.STATUS_PUBLISHED,
            tutorial_placement=(
                KnowledgeBaseArticle.TUTORIAL_PLACEMENT_PROFILE_COMPLETENESS_EMAIL
            ),
        )
        .exclude(video_youtube_url="")
        .order_by("-dipublikasikan_pada", "-diperbarui_pada", "-pk")
        .first()
    )


def should_send_notification(result, recipients, force=False, now=None):
    if result.is_complete or not recipients["to"]:
        return False, "Profil lengkap" if result.is_complete else "Penerima utama tidak tersedia"
    if force:
        return True, "Dipaksa"
    duplicate = ProfileCompletenessNotificationLog.objects.filter(
        profile=result.profile, issue_fingerprint=result.fingerprint,
        status=ProfileCompletenessNotificationLog.STATUS_SENT,
        recipient_to=recipients["to"], recipient_cc=recipients["cc"],
    ).exists()
    return (not duplicate, "Persentase dan temuan tidak berubah" if duplicate else "Temuan baru/berubah")


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


def send_profile_completeness_notification(result, recipients, base_url=None, connection=None, triggered_by=None):
    snapshot, previous = record_profile_assessment(result, triggered_by=triggered_by)
    delta = result.percentage - previous.percentage if previous else None
    context = {
        "profile": result.profile, "result": result, "groups": result.grouped(),
        "recipients": recipients, "profile_url": profile_admin_url(result.profile, base_url),
        "tutorial": profile_completeness_email_tutorial(),
        "previous": previous, "snapshot": snapshot, "delta": delta,
    }
    subject = f"Perbaikan Kelengkapan Profil Risiko – {result.profile.unit_bisnis.name} – {result.profile.tahun} – {result.percentage_display}"
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

        # Error tetap disimpan ke ProfileCompletenessNotificationLog,
        # dan juga ditulis ke application log agar diagnosis SMTP tidak
        # memerlukan pengiriman ulang email.
        try:
            import logging

            logging.getLogger(__name__).warning(
                "Profile completeness email failed | profile=%s | unit=%s | to=%s | cc=%s | error=%s",
                result.profile.pk,
                result.profile.unit_bisnis_id,
                recipients.get("to", []),
                recipients.get("cc", []),
                error,
            )
        except Exception:
            # Logging tidak boleh menggagalkan workflow notifikasi.
            pass

    ProfileCompletenessNotificationLog.objects.create(
        profile=result.profile, unit_bisnis=result.profile.unit_bisnis,
        recipient_to=recipients["to"], recipient_cc=recipients["cc"],
        risk_officer_ids=[entry["id"] for entry in recipients["officers"]],
        pairing_ids=[entry["id"] for entry in recipients["pairings"]],
        issue_fingerprint=result.fingerprint, issue_count=len(result.findings),
        status=status, sent_at=now if sent else None, error_message=error,
    )
    return bool(sent), error
