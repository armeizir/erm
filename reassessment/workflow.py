from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import ReAssessment, ReAssessmentWorkflowLog


class ReAssessmentWorkflowService:
    @staticmethod
    def _log(reassessment, actor, action, from_status, to_status, note="", metadata=None):
        ReAssessmentWorkflowLog.objects.create(
            reassessment=reassessment,
            action=action,
            from_status=from_status,
            to_status=to_status,
            actor=actor,
            note=note or "",
            metadata=metadata or {},
        )

    @staticmethod
    def validate_before_submit(reassessment: ReAssessment):
        errors = []

        risk_qs = reassessment.risk_events.select_related("km_item", "risk_owner")
        if not risk_qs.exists():
            errors.append("Minimal harus ada 1 Risk Event sebelum submit.")

        for risk in risk_qs:
            if not risk.km_item_id:
                errors.append(f"Risk {risk.no_risiko} belum di-mapping ke KM item.")
            if not risk.risk_owner_id:
                errors.append(f"Risk {risk.no_risiko} belum memiliki risk owner.")
            if not risk.peristiwa_risiko:
                errors.append(f"Risk {risk.no_risiko} belum memiliki peristiwa risiko.")

        if errors:
            raise ValidationError(errors)

    @staticmethod
    @transaction.atomic
    def submit(reassessment: ReAssessment, actor, note=""):
        if reassessment.status not in {
            ReAssessment.STATUS_DRAFT,
            ReAssessment.STATUS_REJECTED_RKM,
            ReAssessment.STATUS_REJECTED_KM,
        }:
            raise ValidationError("Status saat ini tidak bisa di-submit.")

        ReAssessmentWorkflowService.validate_before_submit(reassessment)

        from_status = reassessment.status
        reassessment.status = ReAssessment.STATUS_SUBMITTED
        reassessment.submitted_at = timezone.now()
        if note:
            reassessment.catatan_unit = note
        reassessment.save()

        ReAssessmentWorkflowService._log(
            reassessment=reassessment,
            actor=actor,
            action=ReAssessmentWorkflowLog.ACTION_SUBMIT,
            from_status=from_status,
            to_status=reassessment.status,
            note=note,
        )
        return reassessment

    @staticmethod
    @transaction.atomic
    def start_rkm_review(reassessment: ReAssessment, actor, note=""):
        if reassessment.status != ReAssessment.STATUS_SUBMITTED:
            raise ValidationError("Hanya data submitted yang bisa masuk review RKM.")

        from_status = reassessment.status
        reassessment.status = ReAssessment.STATUS_REVIEW_RKM
        reassessment.reviewed_by_rkm = actor
        reassessment.reviewed_rkm_at = timezone.now()
        if note:
            reassessment.catatan_rkm = note
        reassessment.save()

        ReAssessmentWorkflowService._log(
            reassessment,
            actor,
            ReAssessmentWorkflowLog.ACTION_REVIEW_RKM,
            from_status,
            reassessment.status,
            note,
        )
        return reassessment

    @staticmethod
    @transaction.atomic
    def approve_rkm(reassessment: ReAssessment, actor, note=""):
        if reassessment.status not in {
            ReAssessment.STATUS_SUBMITTED,
            ReAssessment.STATUS_REVIEW_RKM,
        }:
            raise ValidationError("Belum berada pada tahap review RKM.")

        from_status = reassessment.status
        reassessment.status = ReAssessment.STATUS_APPROVED_RKM
        reassessment.approved_by_rkm = actor
        reassessment.approved_rkm_at = timezone.now()
        if note:
            reassessment.catatan_rkm = note
        reassessment.save()

        ReAssessmentWorkflowService._log(
            reassessment,
            actor,
            ReAssessmentWorkflowLog.ACTION_APPROVE_RKM,
            from_status,
            reassessment.status,
            note,
        )
        return reassessment

    @staticmethod
    @transaction.atomic
    def reject_rkm(reassessment: ReAssessment, actor, note):
        if reassessment.status not in {
            ReAssessment.STATUS_SUBMITTED,
            ReAssessment.STATUS_REVIEW_RKM,
        }:
            raise ValidationError("Belum berada pada tahap review RKM.")

        if not note:
            raise ValidationError("Catatan reject RKM wajib diisi.")

        from_status = reassessment.status
        reassessment.status = ReAssessment.STATUS_REJECTED_RKM
        reassessment.catatan_rkm = note
        reassessment.save()

        ReAssessmentWorkflowService._log(
            reassessment,
            actor,
            ReAssessmentWorkflowLog.ACTION_REJECT_RKM,
            from_status,
            reassessment.status,
            note,
        )
        return reassessment

    @staticmethod
    @transaction.atomic
    def start_km_review(reassessment: ReAssessment, actor, note=""):
        if reassessment.status != ReAssessment.STATUS_APPROVED_RKM:
            raise ValidationError("Hanya data APPROVED_RKM yang bisa masuk review KM.")

        from_status = reassessment.status
        reassessment.status = ReAssessment.STATUS_REVIEW_KM
        reassessment.reviewed_by_km = actor
        reassessment.reviewed_km_at = timezone.now()
        if note:
            reassessment.catatan_km = note
        reassessment.save()

        ReAssessmentWorkflowService._log(
            reassessment,
            actor,
            ReAssessmentWorkflowLog.ACTION_REVIEW_KM,
            from_status,
            reassessment.status,
            note,
        )
        return reassessment

    @staticmethod
    @transaction.atomic
    def approve_km(reassessment: ReAssessment, actor, note="", escalate=False):
        if reassessment.status not in {
            ReAssessment.STATUS_APPROVED_RKM,
            ReAssessment.STATUS_REVIEW_KM,
        }:
            raise ValidationError("Belum berada pada tahap review KM.")

        from_status = reassessment.status
        reassessment.status = ReAssessment.STATUS_APPROVED_KM
        reassessment.approved_by_km = actor
        reassessment.approved_km_at = timezone.now()
        reassessment.is_escalated = bool(escalate)
        if note:
            reassessment.catatan_km = note
        reassessment.save()

        ReAssessmentWorkflowService._log(
            reassessment,
            actor,
            ReAssessmentWorkflowLog.ACTION_APPROVE_KM,
            from_status,
            reassessment.status,
            note,
            metadata={"escalate": bool(escalate)},
        )
        return reassessment

    @staticmethod
    @transaction.atomic
    def reject_km(reassessment: ReAssessment, actor, note):
        if reassessment.status not in {
            ReAssessment.STATUS_APPROVED_RKM,
            ReAssessment.STATUS_REVIEW_KM,
        }:
            raise ValidationError("Belum berada pada tahap review KM.")

        if not note:
            raise ValidationError("Catatan reject KM wajib diisi.")

        from_status = reassessment.status
        reassessment.status = ReAssessment.STATUS_REJECTED_KM
        reassessment.catatan_km = note
        reassessment.save()

        ReAssessmentWorkflowService._log(
            reassessment,
            actor,
            ReAssessmentWorkflowLog.ACTION_REJECT_KM,
            from_status,
            reassessment.status,
            note,
        )
        return reassessment

    @staticmethod
    @transaction.atomic
    def lock(reassessment: ReAssessment, actor, note=""):
        if reassessment.status != ReAssessment.STATUS_APPROVED_KM:
            raise ValidationError("Hanya APPROVED_KM yang bisa di-lock.")

        from_status = reassessment.status
        reassessment.status = ReAssessment.STATUS_LOCKED
        reassessment.locked_at = timezone.now()
        reassessment.save()

        ReAssessmentWorkflowService._log(
            reassessment,
            actor,
            ReAssessmentWorkflowLog.ACTION_LOCK,
            from_status,
            reassessment.status,
            note,
        )
        return reassessment