"""Explicit SMT revision transitions; no changes to historical content or files."""
import re
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .models import Document


def next_revision(documents):
    numbers = []
    width = 2
    for obj in documents:
        if not re.fullmatch(r"[0-9]+", obj.revisi):
            raise ValidationError("Nomor revisi nonnumerik perlu disesuaikan sebelum duplikasi.")
        numbers.append(int(obj.revisi))
        width = max(width, len(obj.revisi))
    value = str(max(numbers) + 1).zfill(width)
    if len(value) > 30:
        raise ValidationError("Nomor revisi melebihi batas kolom.")
    return value


@transaction.atomic
def create_revision(source_id):
    source = Document.objects.select_for_update().get(pk=source_id)
    family = list(Document.objects.select_for_update().filter(
        jenis=source.jenis, nomor=source.nomor))
    if source.status != Document.Status.ACTIVE:
        raise ValidationError("Revisi baru hanya dibuat dari versi yang Berlaku.")
    child = Document.objects.filter(revisi_sebelumnya=source).first()
    if child:
        if child.status in {Document.Status.DRAFT, Document.Status.REVIEW}:
            return child, False
        raise ValidationError("Versi ini sudah memiliki revisi lanjutan.")
    if any(d.status in {Document.Status.DRAFT, Document.Status.REVIEW} for d in family):
        raise ValidationError("Masih ada Draft/Dalam Review untuk nomor ini. Selesaikan revisi tersebut dahulu.")
    excluded = {"id", "revisi", "status", "tanggal_berlaku", "catatan_revisi",
                "dibuat_pada", "diperbarui_pada", "revisi_sebelumnya"}
    excluded.update(['penyusun_user', 'verifikator_user', 'pengesah_user'])
    excluded.update(['penyusun_nama', 'penyusun_jabatan', 'penyusun_tanggal', 'verifikator_nama', 'verifikator_jabatan', 'verifikator_tanggal', 'pengesah_nama', 'pengesah_jabatan', 'pengesah_tanggal'])
    values = {f.attname: getattr(source, f.attname)
              for f in Document._meta.concrete_fields if f.name not in excluded}
    # SMT_AUTO_DIVISION_V1: nomor urut tetap; hanya kode divisi yang diganti.
    parts = source.nomor.split("-")
    if len(parts) == 5 and parts[0] in {"PI", "IK"} and parts[3] == "PRM":
        parts[3] = "MRK"
        values["nomor"] = "-".join(parts)
    target = Document(**values, revisi=next_revision(family), status="draft",
                      tanggal_berlaku=None, revisi_sebelumnya=source,
                      catatan_revisi="")
    target.full_clean()
    target.save()
    # Lampiran final/pengesahan tetap di arsip sumber, tidak dianggap sah untuk draft baru.
    return target, True


@transaction.atomic
def activate_revision(target_id, effective_date, actor=None):
    target = Document.objects.select_for_update().get(pk=target_id)
    if target.status not in {Document.Status.DRAFT, Document.Status.REVIEW}:
        raise ValidationError("Hanya Draft/Dalam Review yang dapat disahkan.")
    # Browser actions always supply the actor. Configured workflows cannot bypass this.
    if actor is not None or target.pengesah_jabatan or target.verifikator_jabatan:
        if target.status != 'review' or not target.verifikator_tanggal:
            raise ValidationError("Dokumen harus diverifikasi dahulu.")
        from .approval_positions import record_action
        record_action(target, 'pengesah', actor)
    if not effective_date or effective_date > timezone.localdate():
        raise ValidationError("Isi tanggal berlaku yang tidak melebihi tanggal hari ini.")
    family = list(Document.objects.select_for_update().filter(
        jenis=target.jenis, nomor=target.nomor))
    active = [d for d in family if d.status == Document.Status.ACTIVE]
    if target.revisi_sebelumnya_id:
        source = Document.objects.select_for_update().get(pk=target.revisi_sebelumnya_id)
        if source.status != Document.Status.ACTIVE or source.jenis != target.jenis:
            raise ValidationError("Versi sebelumnya sudah berubah. Periksa riwayat revisi.")
        if any(d.pk != source.pk for d in active):
            raise ValidationError("Nomor dokumen tujuan sudah mempunyai versi Berlaku.")
        if source.tanggal_berlaku and effective_date < source.tanggal_berlaku:
            raise ValidationError("Tanggal berlaku tidak boleh mendahului versi sebelumnya.")
    elif active:
        raise ValidationError("Gunakan Buat Revisi Baru dari versi Berlaku untuk mengganti dokumen ini.")
    else:
        source = None
    if source:
        Document.objects.filter(pk=source.pk, status="active").update(
            status="retired", diperbarui_pada=timezone.now())
    target.status = Document.Status.ACTIVE
    target.tanggal_berlaku = effective_date
    target.full_clean()
    target.save(update_fields=["status", "tanggal_berlaku", "pengesah_tanggal", "pengesah_user", "pengesah_nama", "diperbarui_pada"])
    return target, source


@transaction.atomic
def verify_revision(target_id, actor):
    target = Document.objects.select_for_update().get(pk=target_id)
    if target.status != 'draft':
        raise ValidationError("Hanya Draft yang dapat diverifikasi.")
    if not target.penyusun_user_id or not target.verifikator_jabatan or not target.pengesah_jabatan:
        raise ValidationError("Pilih penyusun serta jabatan verifikator dan pengesah dahulu.")
    from .approval_positions import record_action
    record_action(target, 'verifikator', actor)
    target.status = 'review'
    target.save(update_fields=['status', 'verifikator_user', 'verifikator_nama',
                               'verifikator_tanggal', 'diperbarui_pada'])
    return target
