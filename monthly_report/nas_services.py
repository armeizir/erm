from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from .nas_models import NASEvidence, NASEvidenceReview, validate_nas_url


def can_verify(user):
    return bool(user.is_active and user.is_staff and
        (user.is_superuser or user.has_perm("monthly_report.verify_nasevidence")))


def can_access_report(user, report):
    if not user.is_active or not user.is_staff: return False
    if user.is_superuser: return True
    if not user.has_perm("monthly_report.view_monthlyriskreport") and not user.has_perm("monthly_report.change_monthlyriskreport"):
        return False
    if user.pk in {report.prepared_by_id,report.reviewed_by_id,report.approved_by_id}:
        return True
    from risk.access_policy import organizational_groups_for_user
    return organizational_groups_for_user(user).filter(pk=report.reassessment.unit_bisnis_id).exists()


@transaction.atomic
def review_evidence(evidence_id, user, action, note):
    from .models import MonthlyRiskReport
    if not can_verify(user): raise PermissionDenied
    # Lock report first, matching the submit transaction and evidence creation.
    report_id=NASEvidence.objects.values_list("report_id",flat=True).get(pk=evidence_id)
    report=MonthlyRiskReport.objects.select_for_update().get(pk=report_id)
    if not can_access_report(user,report): raise PermissionDenied
    if report.status not in {"draft","revision"} or getattr(report,"is_locked",False):
        raise ValidationError("Verifikasi diubah hanya saat Draft/Revisi dan tidak terkunci.")
    evidence=NASEvidence.objects.select_for_update().get(pk=evidence_id,report_id=report.pk)
    if action not in {"verify","revoke"} or not (note or "").strip():
        raise ValidationError("Pilih tindakan dan isi catatan pemeriksaan.")
    if action=="verify":
        if evidence.report_scope != f"{report.reassessment_id}:{report.periode_id}":
            raise ValidationError("Bidang/periode laporan berubah; catat ulang eviden sesuai laporan.")
        validate_nas_url(evidence.read_url)
        if evidence.read_url.rstrip("/")==evidence.upload_url_snapshot.rstrip("/"):
            raise ValidationError("Link unggah tidak menjadi eviden terverifikasi.")
        from .nas_models import NASEvidenceLocation
        if NASEvidenceLocation.objects.filter(upload_url=evidence.read_url).exists():
            raise ValidationError("Link File Request tidak dapat diverifikasi sebagai link baca.")
    now=timezone.now()
    NASEvidence.objects.filter(pk=evidence.pk).update(verified=action=="verify",
        verified_by_id=user.pk if action=="verify" else None,
        verified_at=now if action=="verify" else None)
    NASEvidenceReview.objects.create(evidence=evidence,actor=user,action=action,note=note.strip())
    evidence.refresh_from_db()
    return evidence


def has_verified_nas_evidence(report):
    records=NASEvidence.objects.filter(report=report,verified=True,
        verified_by__isnull=False,verified_at__isnull=False)
    for row in records:
        try: validate_nas_url(row.read_url)
        except ValidationError: continue
        latest=row.reviews.order_by("-created_at","-pk").first()
        if (row.report_scope == f"{report.reassessment_id}:{report.periode_id}"
                and latest and latest.action=="verify" and latest.actor_id==row.verified_by_id
                and row.read_url.rstrip("/") != row.upload_url_snapshot.rstrip("/")):
            return True
    return False
