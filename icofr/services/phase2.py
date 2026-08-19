from __future__ import annotations

from collections import Counter

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from masterdata.models import OrganizationUnitUserAssignment

from icofr.models import (
    CSAAssessment,
    CSASample,
    CSASampleAttributeResult,
    ICoFRDistributionBatch,
    ICoFRQuestion,
    ICoFRSchedule,
    ICoFRScheduleUnit,
    ICoFRStage,
    ICoFRWorkItem,
    QuestionnaireAnswer,
    QuestionnaireSubmission,
    RCMMapping,
)


def _stage_unit_field(stage):
    stage = ICoFRStage(stage)
    return {
        ICoFRStage.QUESTIONNAIRE: "questionnaire_active",
        ICoFRStage.LINE1: "line1_active",
        ICoFRStage.LINE2: "line2_active",
        ICoFRStage.LINE3: "line3_active",
    }[stage]


def _primary_org_assignment(user, on_date):
    if not user:
        return None
    qs = OrganizationUnitUserAssignment.objects.filter(
        user=user,
        aktif=True,
        tanggal_mulai__lte=on_date,
    ).filter(Q(tanggal_selesai__isnull=True) | Q(tanggal_selesai__gte=on_date))
    assignment = qs.order_by("-utama", "-is_unit_head", "-tanggal_mulai", "pk").first()
    return assignment.organization_unit if assignment else None


def _validate_distribution(schedule: ICoFRSchedule, stage):
    stage = ICoFRStage(stage)
    config = schedule.stage_config(stage)
    if not config["active"]:
        raise ValidationError(f"Tahap {stage.label} belum diaktifkan pada penjadwalan.")
    if not config["start"] or not config["end"]:
        raise ValidationError(f"Tanggal tahap {stage.label} belum lengkap.")
    if schedule.rcm_set.status != schedule.rcm_set.Status.FINAL:
        raise ValidationError("RCM harus berstatus Final / Locked sebelum distribusi.")
    unit_field = _stage_unit_field(stage)
    if not schedule.unit_activations.filter(**{unit_field: True}).exists():
        raise ValidationError(f"Belum ada Organization Unit yang diaktifkan untuk {stage.label}.")
    return config


def ensure_questionnaire_answers(submission: QuestionnaireSubmission):
    questions = ICoFRQuestion.objects.filter(
        rcm_type=submission.work_item.entry.rcm_set.rcm_type,
        is_active=True,
    ).order_by("sequence", "id")
    existing = set(submission.answers.values_list("question_id", flat=True))
    QuestionnaireAnswer.objects.bulk_create(
        [QuestionnaireAnswer(submission=submission, question=q) for q in questions if q.pk not in existing],
        ignore_conflicts=True,
    )
    return submission.answers.count()


def ensure_sample_attributes(sample: CSASample):
    entry = sample.assessment.work_item.entry
    attributes = entry.control_attributes.all().order_by("sequence", "id")
    existing = set(sample.attribute_results.values_list("attribute_id", flat=True))
    CSASampleAttributeResult.objects.bulk_create(
        [
            CSASampleAttributeResult(sample=sample, attribute=attribute)
            for attribute in attributes
            if attribute.pk not in existing
        ],
        ignore_conflicts=True,
    )
    return sample.attribute_results.count()


@transaction.atomic
def distribute_schedule_stage(schedule: ICoFRSchedule, stage, *, user=None):
    """Create/update assignment snapshots for a scheduled stage.

    Distribution is intentionally idempotent. Existing work items are retained and only
    missing snapshots are filled; completed workflow data is never overwritten.
    """

    stage = ICoFRStage(stage)
    config = _validate_distribution(schedule, stage)
    stage_date = config["start"] or timezone.localdate()
    unit_field = _stage_unit_field(stage)
    enabled_unit_ids = set(
        schedule.unit_activations.filter(**{unit_field: True}).values_list("organization_unit_id", flat=True)
    )

    entries = schedule.rcm_set.entries.select_related("risk", "control").all()
    mappings = {
        mapping.entry_id: mapping
        for mapping in RCMMapping.objects.filter(entry__rcm_set=schedule.rcm_set).select_related(
            "preparer_user", "reviewer_user"
        )
    }

    batch = ICoFRDistributionBatch.objects.create(
        schedule=schedule,
        stage=stage,
        distributed_by=user,
        total_entries=entries.count(),
    )

    skip_reasons = Counter()
    distributed = 0
    created = 0
    updated = 0

    for entry in entries.iterator():
        mapping = mappings.get(entry.pk)
        if not mapping or not mapping.preparer_user_id:
            skip_reasons["Preparer belum terpetakan"] += 1
            continue
        # Reviewer wajib untuk Line 1; untuk questionnaire tetap disnapshot agar audit trail lengkap.
        if stage == ICoFRStage.LINE1 and not mapping.reviewer_user_id:
            skip_reasons["Reviewer Line 1 belum terpetakan"] += 1
            continue
        if (
            stage == ICoFRStage.LINE1
            and mapping.preparer_user_id
            and mapping.preparer_user_id == mapping.reviewer_user_id
        ):
            skip_reasons["Preparer dan Reviewer sama (SoD)"] += 1
            continue

        organization_unit = _primary_org_assignment(mapping.preparer_user, stage_date)
        if not organization_unit:
            skip_reasons["Organization Unit preparer belum terpetakan"] += 1
            continue
        if organization_unit.pk not in enabled_unit_ids:
            skip_reasons["Organization Unit tidak diaktifkan"] += 1
            continue

        item, was_created = ICoFRWorkItem.objects.get_or_create(
            schedule=schedule,
            stage=stage,
            entry=entry,
            defaults={
                "organization_unit": organization_unit,
                "preparer_user": mapping.preparer_user,
                "reviewer_user": mapping.reviewer_user,
                "distribution_batch": batch,
            },
        )
        if was_created:
            created += 1
        elif item.status in {ICoFRWorkItem.Status.READY, ICoFRWorkItem.Status.DRAFT}:
            changed = False
            snapshots = {
                "organization_unit": organization_unit,
                "preparer_user": mapping.preparer_user,
                "reviewer_user": mapping.reviewer_user,
            }
            for field, value in snapshots.items():
                if getattr(item, f"{field}_id") != (value.pk if value else None):
                    setattr(item, field, value)
                    changed = True
            if changed:
                item.distribution_batch = batch
                item.save(
                    update_fields=(
                        "organization_unit",
                        "preparer_user",
                        "reviewer_user",
                        "distribution_batch",
                        "updated_at",
                    )
                )
                updated += 1

        if stage == ICoFRStage.QUESTIONNAIRE:
            submission, _ = QuestionnaireSubmission.objects.get_or_create(work_item=item)
            ensure_questionnaire_answers(submission)
        elif stage == ICoFRStage.LINE1:
            CSAAssessment.objects.get_or_create(work_item=item)

        distributed += 1

    skipped = batch.total_entries - distributed
    batch.distributed_count = distributed
    batch.skipped_count = skipped
    batch.status = (
        ICoFRDistributionBatch.Status.COMPLETED
        if skipped == 0
        else ICoFRDistributionBatch.Status.PARTIAL
        if distributed
        else ICoFRDistributionBatch.Status.FAILED
    )
    batch.summary = {
        "created": created,
        "updated": updated,
        "skip_reasons": dict(skip_reasons),
    }
    batch.save(
        update_fields=(
            "distributed_count",
            "skipped_count",
            "status",
            "summary",
            "updated_at",
        )
    )
    return batch


def preview_schedule_stage(schedule: ICoFRSchedule, stage):
    """Return a side-effect-free readiness summary before distribution.

    The preview intentionally applies the same business gates as distribution:
    active schedule, Final RCM, active organization unit, mapping, and Line 1 SoD.
    It is used by the admin workspace so users can resolve issues before creating
    work items.
    """

    stage = ICoFRStage(stage)
    config = _validate_distribution(schedule, stage)
    stage_date = config["start"] or timezone.localdate()
    unit_field = _stage_unit_field(stage)
    enabled_unit_ids = set(
        schedule.unit_activations.filter(**{unit_field: True}).values_list("organization_unit_id", flat=True)
    )

    mappings = {
        mapping.entry_id: mapping
        for mapping in RCMMapping.objects.filter(entry__rcm_set=schedule.rcm_set).select_related(
            "preparer_user", "reviewer_user"
        )
    }
    existing_ids = set(
        ICoFRWorkItem.objects.filter(schedule=schedule, stage=stage).values_list("entry_id", flat=True)
    )

    skip_reasons = Counter()
    ready = 0
    existing = 0
    to_create = 0
    total = 0

    for entry in schedule.rcm_set.entries.only("id").iterator():
        total += 1
        mapping = mappings.get(entry.pk)
        if not mapping or not mapping.preparer_user_id:
            skip_reasons["Preparer belum terpetakan"] += 1
            continue
        if stage == ICoFRStage.LINE1 and not mapping.reviewer_user_id:
            skip_reasons["Reviewer Line 1 belum terpetakan"] += 1
            continue
        if (
            stage == ICoFRStage.LINE1
            and mapping.preparer_user_id
            and mapping.preparer_user_id == mapping.reviewer_user_id
        ):
            skip_reasons["Preparer dan Reviewer sama (SoD)"] += 1
            continue

        organization_unit = _primary_org_assignment(mapping.preparer_user, stage_date)
        if not organization_unit:
            skip_reasons["Organization Unit preparer belum terpetakan"] += 1
            continue
        if organization_unit.pk not in enabled_unit_ids:
            skip_reasons["Organization Unit tidak diaktifkan"] += 1
            continue

        ready += 1
        if entry.pk in existing_ids:
            existing += 1
        else:
            to_create += 1

    return {
        "stage": stage,
        "stage_label": stage.label,
        "total_entries": total,
        "ready_count": ready,
        "skipped_count": total - ready,
        "existing_count": existing,
        "to_create_count": to_create,
        "enabled_unit_count": len(enabled_unit_ids),
        "skip_reasons": dict(skip_reasons),
        "start": config["start"],
        "end": config["end"],
    }
