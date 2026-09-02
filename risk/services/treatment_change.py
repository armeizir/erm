from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from risk.models import (
    ReAssessmentItem,
    RiskTreatmentChangeRequest,
)


ID_FIELDS = {
    "opsi_perlakuan_risiko_id",
    "pos_anggaran_id",
    "jenis_program_dalam_rkap_id",
    "pic_organization_unit_id",
    "pic_user_assignment_id",
}

TEXT_FIELDS = {
    "rencana_perlakuan_risiko",
    "output_perlakuan_risiko",
    "prk",
    "pic",
}

M2M_FIELD = "jenis_rencana_perlakuan_risiko_ids"

TIMELINE_FIELDS = {
    f"timeline_{month}"
    for month in range(1, 13)
}


def snapshot_treatment(item):
    return {
        "opsi_perlakuan_risiko_id":
            item.opsi_perlakuan_risiko_id,

        "jenis_rencana_perlakuan_risiko_ids":
            list(
                item.jenis_rencana_perlakuan_risiko
                .order_by("pk")
                .values_list("pk", flat=True)
            ),

        "rencana_perlakuan_risiko":
            item.rencana_perlakuan_risiko,

        "output_perlakuan_risiko":
            item.output_perlakuan_risiko,

        "biaya_perlakuan_risiko":
            (
                None
                if item.biaya_perlakuan_risiko is None
                else str(item.biaya_perlakuan_risiko)
            ),

        "pos_anggaran_id":
            item.pos_anggaran_id,

        "prk":
            item.prk,

        "jenis_program_dalam_rkap_id":
            item.jenis_program_dalam_rkap_id,

        "pic":
            item.pic,

        "pic_organization_unit_id":
            item.pic_organization_unit_id,

        "pic_user_assignment_id":
            item.pic_user_assignment_id,

        **{
            f"timeline_{month}":
                getattr(item, f"timeline_{month}")
            for month in range(1, 13)
        },
    }


def normalize_proposed_changes(changes):
    if not isinstance(changes, dict):
        raise ValidationError(
            "Usulan perubahan harus berupa dictionary."
        )

    invalid = (
        set(changes)
        - RiskTreatmentChangeRequest.ALLOWED_CHANGE_KEYS
    )

    if invalid:
        raise ValidationError(
            "Field tidak diperbolehkan: "
            + ", ".join(sorted(invalid))
        )

    result = {}

    for key, value in changes.items():

        if key in ID_FIELDS:
            if value in (None, ""):
                result[key] = None
            else:
                try:
                    result[key] = int(value)
                except (TypeError, ValueError):
                    raise ValidationError(
                        f"{key} harus berupa ID numerik."
                    )

        elif key == M2M_FIELD:
            if value in (None, ""):
                result[key] = []
            elif not isinstance(
                value,
                (list, tuple, set),
            ):
                raise ValidationError(
                    f"{key} harus berupa list ID."
                )
            else:
                try:
                    result[key] = sorted(
                        {
                            int(item_id)
                            for item_id in value
                        }
                    )
                except (TypeError, ValueError):
                    raise ValidationError(
                        f"{key} berisi ID tidak valid."
                    )

        elif key == "biaya_perlakuan_risiko":
            if value in (None, ""):
                result[key] = None
            else:
                try:
                    result[key] = str(
                        Decimal(str(value))
                    )
                except (
                    InvalidOperation,
                    TypeError,
                    ValueError,
                ):
                    raise ValidationError(
                        "Biaya Perlakuan Risiko tidak valid."
                    )

        elif key in TIMELINE_FIELDS:
            try:
                timeline_value = int(value)
            except (TypeError, ValueError):
                raise ValidationError(
                    f"{key} harus 0 atau 1."
                )

            if timeline_value not in (0, 1):
                raise ValidationError(
                    f"{key} harus 0 atau 1."
                )

            result[key] = timeline_value

        elif key in TEXT_FIELDS:
            result[key] = (
                None
                if value is None
                else str(value)
            )

        else:
            result[key] = value

    return result


@transaction.atomic
def create_change_request(
    *,
    reassessment_item,
    changes,
    alasan_perubahan,
    actor,
    dampak_perubahan="",
):
    item = (
        ReAssessmentItem.objects
        .select_for_update()
        .get(pk=reassessment_item.pk)
    )

    if not alasan_perubahan or not alasan_perubahan.strip():
        raise ValidationError(
            "Alasan perubahan wajib diisi."
        )

    existing_open = (
        RiskTreatmentChangeRequest.objects
        .filter(
            reassessment_item=item,
            status__in=(
                RiskTreatmentChangeRequest.OPEN_STATUSES
            ),
        )
        .exists()
    )

    if existing_open:
        raise ValidationError(
            "Masih ada usulan perubahan aktif "
            "untuk Rencana Perlakuan Risiko ini."
        )

    before = snapshot_treatment(item)
    normalized = normalize_proposed_changes(changes)

    effective = {
        key: value
        for key, value in normalized.items()
        if before.get(key) != value
    }

    if not effective:
        raise ValidationError(
            "Tidak ada perubahan terhadap data current."
        )

    last_version = (
        RiskTreatmentChangeRequest.objects
        .filter(reassessment_item=item)
        .aggregate(max_version=Max("version"))
        ["max_version"]
        or 0
    )

    obj = RiskTreatmentChangeRequest(
        reassessment_item=item,
        version=last_version + 1,
        before_snapshot=before,
        proposed_changes=effective,
        alasan_perubahan=alasan_perubahan.strip(),
        dampak_perubahan=(
            dampak_perubahan.strip()
            if dampak_perubahan
            else ""
        ),
        created_by=actor,
        status=RiskTreatmentChangeRequest.STATUS_DRAFT,
    )

    obj.full_clean()
    obj.save()

    return obj


def _assert_snapshot_current(change, item):
    current = snapshot_treatment(item)

    if current != change.before_snapshot:
        raise ValidationError(
            "Rencana Perlakuan Risiko telah berubah "
            "sejak usulan ini dibuat. "
            "Kembalikan usulan untuk revisi dan buat "
            "snapshot terbaru."
        )


@transaction.atomic
def submit_change_request(*, change_request, actor):
    change = (
        RiskTreatmentChangeRequest.objects
        .select_for_update()
        .select_related("reassessment_item")
        .get(pk=change_request.pk)
    )

    if change.status not in {
        RiskTreatmentChangeRequest.STATUS_DRAFT,
        RiskTreatmentChangeRequest.STATUS_REVISION,
    }:
        raise ValidationError(
            "Hanya Draft atau Perlu Revisi yang dapat diajukan."
        )

    item = (
        ReAssessmentItem.objects
        .select_for_update()
        .get(pk=change.reassessment_item_id)
    )

    _assert_snapshot_current(change, item)

    change.status = (
        RiskTreatmentChangeRequest.STATUS_SUBMITTED
    )
    change.requested_by = actor
    change.requested_at = timezone.now()

    change.full_clean()
    change.save(
        update_fields=[
            "status",
            "requested_by",
            "requested_at",
            "updated_at",
        ]
    )

    return change


@transaction.atomic
def start_review(*, change_request, actor):
    change = (
        RiskTreatmentChangeRequest.objects
        .select_for_update()
        .get(pk=change_request.pk)
    )

    if (
        change.status
        != RiskTreatmentChangeRequest.STATUS_SUBMITTED
    ):
        raise ValidationError(
            "Hanya usulan berstatus Diajukan "
            "yang dapat mulai direview."
        )

    change.status = (
        RiskTreatmentChangeRequest.STATUS_UNDER_REVIEW
    )
    change.reviewed_by = actor
    change.reviewed_at = timezone.now()

    change.full_clean()
    change.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        ]
    )

    return change


@transaction.atomic
def request_revision(
    *,
    change_request,
    actor,
    reviewer_note,
):
    change = (
        RiskTreatmentChangeRequest.objects
        .select_for_update()
        .get(pk=change_request.pk)
    )

    if change.status not in {
        RiskTreatmentChangeRequest.STATUS_SUBMITTED,
        RiskTreatmentChangeRequest.STATUS_UNDER_REVIEW,
    }:
        raise ValidationError(
            "Usulan ini tidak berada dalam tahap review."
        )

    if not reviewer_note or not reviewer_note.strip():
        raise ValidationError(
            "Catatan reviewer wajib diisi."
        )

    change.status = (
        RiskTreatmentChangeRequest.STATUS_REVISION
    )
    change.reviewed_by = actor
    change.reviewed_at = timezone.now()
    change.reviewer_note = reviewer_note.strip()

    change.full_clean()
    change.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "reviewer_note",
            "updated_at",
        ]
    )

    return change


@transaction.atomic
def reject_change_request(
    *,
    change_request,
    actor,
    reviewer_note,
):
    change = (
        RiskTreatmentChangeRequest.objects
        .select_for_update()
        .get(pk=change_request.pk)
    )

    if change.status not in {
        RiskTreatmentChangeRequest.STATUS_SUBMITTED,
        RiskTreatmentChangeRequest.STATUS_UNDER_REVIEW,
    }:
        raise ValidationError(
            "Usulan ini tidak berada dalam tahap review."
        )

    if not reviewer_note or not reviewer_note.strip():
        raise ValidationError(
            "Alasan penolakan wajib diisi."
        )

    change.status = (
        RiskTreatmentChangeRequest.STATUS_REJECTED
    )
    change.reviewed_by = actor
    change.reviewed_at = timezone.now()
    change.reviewer_note = reviewer_note.strip()

    change.full_clean()
    change.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "reviewer_note",
            "updated_at",
        ]
    )

    return change


@transaction.atomic
def approve_change_request(
    *,
    change_request,
    actor,
    reviewer_note="",
):
    change = (
        RiskTreatmentChangeRequest.objects
        .select_for_update()
        .select_related("reassessment_item")
        .get(pk=change_request.pk)
    )

    if change.status not in {
        RiskTreatmentChangeRequest.STATUS_SUBMITTED,
        RiskTreatmentChangeRequest.STATUS_UNDER_REVIEW,
    }:
        raise ValidationError(
            "Hanya usulan yang sedang direview "
            "yang dapat disetujui."
        )

    item = (
        ReAssessmentItem.objects
        .select_for_update()
        .get(pk=change.reassessment_item_id)
    )

    _assert_snapshot_current(change, item)

    scalar_update_fields = []

    for key, value in change.proposed_changes.items():

        if key == M2M_FIELD:
            continue

        if key == "biaya_perlakuan_risiko":
            value = (
                None
                if value is None
                else Decimal(value)
            )

        setattr(item, key, value)

        field_name = (
            key[:-3]
            if key.endswith("_id")
            else key
        )

        scalar_update_fields.append(field_name)

    item.full_clean()

    if scalar_update_fields:
        item.save(
            update_fields=sorted(
                set(scalar_update_fields)
            )
        )

    if M2M_FIELD in change.proposed_changes:
        item.jenis_rencana_perlakuan_risiko.set(
            change.proposed_changes[M2M_FIELD]
        )

    now = timezone.now()

    change.status = (
        RiskTreatmentChangeRequest.STATUS_APPROVED
    )

    if change.reviewed_by_id is None:
        change.reviewed_by = actor
        change.reviewed_at = now

    change.approved_by = actor
    change.approved_at = now
    change.applied_at = now

    if reviewer_note:
        change.reviewer_note = reviewer_note.strip()

    change.full_clean()
    change.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "reviewer_note",
            "approved_by",
            "approved_at",
            "applied_at",
            "updated_at",
        ]
    )

    return change
