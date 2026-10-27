from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html
from riskproject.admin_site import risk_admin_site
from .models import Document, ProsedurIntegrasi, InstruksiKerja, Attachment
from .forms import DocumentForm
from .richtext import RICH_FIELDS, editor_html


class AttachmentForm(forms.ModelForm):
    class Meta:
        model = Attachment
        fields = "__all__"
        widgets = {"berkas": forms.FileInput()}


class AttachmentInline(admin.TabularInline):
    model = Attachment
    form = AttachmentForm
    extra = 0
    fields = ("nama", "jenis", "berkas", "unduh")
    readonly_fields = ("unduh",)

    @admin.display(description="Berkas tersimpan")
    def unduh(self, obj):
        if not obj.pk:
            return "—"
        model = "prosedurintegrasi" if obj.document.jenis == "PI" else "instruksikerja"
        return format_html('<a href="{}">Unduh</a>', reverse(f"risk_admin:smt_{model}_download", args=[obj.document_id, obj.pk]))

    def get_fields(self, request, obj=None):
        if obj and not self.has_change_permission(request, obj):
            return ("nama", "jenis", "unduh")
        return self.fields

    # Lampiran memakai izin dokumen induk, bukan izin model lampiran terpisah.
    def has_view_permission(self, request, obj=None):
        return request.user.has_perm(f"smt.view_{obj._meta.model_name}") or request.user.has_perm(f"smt.change_{obj._meta.model_name}") if obj else True

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm(f"smt.change_{obj._meta.model_name}") if obj else False

    def has_add_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)


class DocumentAdmin(admin.ModelAdmin):
    form = DocumentForm
    change_form_template = "admin/smt/change_form.html"
    kind = None
    list_display = ("nomor", "judul", "unit_pemilik", "revisi", "status", "tanggal_berlaku")
    list_filter = ("status", "unit_pemilik")
    search_fields = ("nomor", "judul")
    readonly_fields = ("dibuat_pada", "diperbarui_pada", "riwayat_revisi")
    inlines = (AttachmentInline,)
    save_as = True
    actions = None

    class Media:
        css = {"all": ("smt/editor.css",)}

    def get_queryset(self, request):
        return super().get_queryset(request).filter(jenis=self.kind).select_related("unit_pemilik", "prosedur_induk")

    def get_fields(self, request, obj=None):
        fields = ["nomor", "judul", "unit_pemilik", "revisi", "tanggal_berlaku", "status"]
        if self.kind == "IK":
            fields.append("prosedur_induk")
        content = list(RICH_FIELDS)
        if obj and not self.has_change_permission(request, obj):
            content = [f"formatted_{name}" for name in content]
        return fields + content + ["riwayat_revisi", "dibuat_pada", "diperbarui_pada"]

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj and not self.has_change_permission(request, obj):
            fields.extend(f"formatted_{name}" for name in RICH_FIELDS)
        return fields

    def get_form(self, request, obj=None, **kwargs):
        parent = super().get_form(request, obj, **kwargs)
        kind = self.kind
        class KindForm(parent):
            def __init__(self, *args, **kw):
                super().__init__(*args, **kw)
                self.instance.jenis = kind
        return KindForm

    @admin.display(description="Riwayat revisi")
    def riwayat_revisi(self, obj):
        if not obj or not obj.pk:
            return "Simpan dokumen terlebih dahulu."
        return "; ".join(f"Rev. {d.revisi}: {d.get_status_display()}" for d in Document.objects.filter(jenis=obj.jenis, nomor=obj.nomor))

    def document_pdf(self, request, object_id):
        obj = get_object_or_404(self.get_queryset(request), pk=object_id)
        if not self.has_view_or_change_permission(request, obj):
            raise PermissionDenied
        from django.http import HttpResponse
        from django.utils.text import slugify
        from .pdf import build_document_pdf
        response = HttpResponse(build_document_pdf(obj), content_type="application/pdf")
        filename = f"{slugify(obj.nomor)}-rev-{slugify(obj.revisi)}.pdf"
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    def get_urls(self):
        return [path("<int:object_id>/pdf/", self.admin_site.admin_view(self.document_pdf), name=f"smt_{self.model._meta.model_name}_pdf"), path("<int:object_id>/lampiran/<int:attachment_id>/", self.admin_site.admin_view(self.download), name=f"smt_{self.model._meta.model_name}_download")] + super().get_urls()

    def download(self, request, object_id, attachment_id):
        obj = get_object_or_404(self.get_queryset(request), pk=object_id)
        if not self.has_view_or_change_permission(request, obj):
            raise PermissionDenied
        attachment = get_object_or_404(Attachment, pk=attachment_id, document_id=obj.pk)
        try:
            file = attachment.berkas.open("rb")
        except FileNotFoundError:
            raise Http404("Berkas tidak ditemukan.")
        response = FileResponse(file, as_attachment=True, filename=f"{attachment.nama}{__import__('pathlib').Path(attachment.berkas.name).suffix}")
        response["Cache-Control"] = "private, no-store"
        return response


def _formatted_field(name):
    def display(self, obj):
        from django.utils.safestring import mark_safe
        # Only our sanitized HTML vocabulary reaches mark_safe.
        return format_html('<div class="smt-rich-readonly">{}</div>',
                           mark_safe(editor_html(getattr(obj, name))))
    display.short_description = Document._meta.get_field(name).verbose_name
    return display


for _field in RICH_FIELDS:
    setattr(DocumentAdmin, f"formatted_{_field}", _formatted_field(_field))


@admin.register(ProsedurIntegrasi, site=risk_admin_site)
class ProsedurIntegrasiAdmin(DocumentAdmin):
    kind = "PI"


@admin.register(InstruksiKerja, site=risk_admin_site)
class InstruksiKerjaAdmin(DocumentAdmin):
    kind = "IK"
