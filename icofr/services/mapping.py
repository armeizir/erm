from __future__ import annotations

import re

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from icofr.models import RCMEntry, RCMMapping
from risk.models import RiwayatJabatanUser


User = get_user_model()


def normalize_position(value):
    text = str(value or "").upper().strip()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _active_position_candidates(position, on_date):
    target = normalize_position(position)
    if not target:
        return []
    rows = (
        RiwayatJabatanUser.objects.select_related("user")
        .filter(
            tanggal_mulai__lte=on_date,
            user__is_active=True,
            user__is_staff=True,
        )
        .filter(tanggal_selesai__isnull=True)
    )
    exact = []
    for row in rows:
        if normalize_position(row.jabatan) == target:
            exact.append(row.user)
    unique = {user.pk: user for user in exact}
    return list(unique.values())


def _resolve(position, on_date):
    candidates = _active_position_candidates(position, on_date)
    if len(candidates) == 1:
        return candidates[0], ""
    if not position:
        return None, "Jabatan kosong pada RCM."
    if not candidates:
        return None, f"Tidak ditemukan user aktif dengan jabatan persis: {position}."
    return None, f"Ditemukan {len(candidates)} user aktif untuk jabatan: {position}; perlu mapping manual."


@transaction.atomic
def auto_map_entry(entry: RCMEntry, *, user=None, on_date=None):
    on_date = on_date or timezone.localdate()
    mapping, _ = RCMMapping.objects.select_for_update().get_or_create(entry=entry)
    preparer, preparer_note = _resolve(entry.preparer_position, on_date)
    reviewer, reviewer_note = _resolve(entry.reviewer_position, on_date)
    mapping.preparer_user = preparer
    mapping.reviewer_user = reviewer
    mapping.mapping_note = "\n".join(note for note in (preparer_note, reviewer_note) if note)
    mapping.mapped_by = user
    mapping.refresh_status()
    mapping.save()
    return mapping


@transaction.atomic
def auto_map_rcm(rcm_set, *, user=None, on_date=None):
    result = {"total": 0, "mapped": 0, "partial": 0, "failed": 0}
    for entry in rcm_set.entries.select_related("risk", "control").all():
        mapping = auto_map_entry(entry, user=user, on_date=on_date)
        result["total"] += 1
        if mapping.status == RCMMapping.Status.MAPPED:
            result["mapped"] += 1
        elif mapping.status == RCMMapping.Status.PARTIAL:
            result["partial"] += 1
        else:
            result["failed"] += 1
    return result
