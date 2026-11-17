"""Explicit revision rows; legacy notes are preserved, never guessed or parsed."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms.models import BaseInlineFormSet
from django.utils import timezone
from .models import Document, DocumentRevisionEntry


class RevisionEntryFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        rows = [f.cleaned_data for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        if rows and not any(row.get("revisi", "").strip() == self.instance.revisi for row in rows):
            raise ValidationError("Tambahkan satu baris uraian untuk revisi dokumen berjalan: " + self.instance.revisi)


def revision_rows(document):
    rows = list(document.daftar_perubahan.all())
    if not rows:
        return [(document.revisi, document.tanggal_berlaku, document.catatan_revisi or "Belum ada catatan revisi.")]
    return [(row.revisi, document.tanggal_berlaku if row.revisi == document.revisi else row.tanggal_berlaku,
             row.uraian) for row in rows]


@transaction.atomic
def save_revision_formset(formset):
    document = Document.objects.select_for_update().get(pk=formset.instance.pk)
    if document.status not in {"draft", "review"}:
        raise ValidationError("Dokumen sudah disahkan/diarsipkan. Muat ulang halaman.")
    changed = any(form.has_changed() for form in formset.forms)
    if not changed:
        return formset.save()
    result = formset.save()
    # Also clear old approvals on Draft; no approval survives a history edit.
    Document.objects.filter(pk=document.pk).update(status="draft", verifikator_tanggal=None,
        pengesah_tanggal=None, diperbarui_pada=timezone.now())
    formset.instance.status = "draft"
    formset.instance.verifikator_tanggal = formset.instance.pengesah_tanggal = None
    return result


def copy_revision_history(source, target):
    rows = revision_rows(source)
    DocumentRevisionEntry.objects.bulk_create([
        DocumentRevisionEntry(document=target, revisi=rev, tanggal_berlaku=day,
                              uraian=note, urutan=index)
        for index, (rev, day, note) in enumerate(rows, 1)
    ])
