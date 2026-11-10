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
    list_display = ("nomor", "judul", "unit_pemilik", "revisi", "status", "tanggal_berlaku", "lihat_pdf")
    list_filter = ("status", "unit_pemilik")
    search_fields = ("nomor", "judul")
    readonly_fields = ("dibuat_pada", "diperbarui_pada", "riwayat_revisi", "revisi_sebelumnya")
    inlines = (AttachmentInline,)
    save_as = False
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
        return fields + content + ["revisi_sebelumnya", "riwayat_revisi", "dibuat_pada", "diperbarui_pada"]

    def get_fieldsets(self, request, obj=None):
        fields = self.get_fields(request, obj)
        approval = ['penyusun_nama', 'penyusun_jabatan', 'penyusun_tanggal', 'verifikator_nama', 'verifikator_jabatan', 'verifikator_tanggal', 'pengesah_nama', 'pengesah_jabatan', 'pengesah_tanggal']
        return (
            (None, {"fields": fields}),
            ("Lembar Pengesahan", {
                "fields": approval,
                "description": "Isi nama, jabatan dan tanggal sesuai dokumen resmi. "
                    "Data ini tidak merupakan tanda tangan elektronik. Unggah lembar "
                    "bertanda tangan pada Lampiran dokumen, jenis Lembar Pengesahan. "
                    "Dokumen Berlaku/Tidak Berlaku hanya dapat dilihat; gunakan Buat Revisi Baru.",
            }),
        )

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj and not self.has_change_permission(request, obj):
            fields.extend(f"formatted_{name}" for name in RICH_FIELDS)
            fields.extend(['penyusun_nama', 'penyusun_jabatan', 'penyusun_tanggal', 'verifikator_nama', 'verifikator_jabatan', 'verifikator_tanggal', 'pengesah_nama', 'pengesah_jabatan', 'pengesah_tanggal'])
        return fields

    def get_form(self, request, obj=None, **kwargs):
        parent = super().get_form(request, obj, **kwargs)
        kind = self.kind
        class KindForm(parent):
            def __init__(self, *args, **kw):
                super().__init__(*args, **kw)
                self.instance.jenis = kind
                if "status" in self.fields:
                    self.fields["status"].choices = [("draft", "Draft"), ("review", "Dalam Review")]
                if self.instance.revisi_sebelumnya_id:
                    for name in ("nomor", "revisi", "unit_pemilik", "prosedur_induk"):
                        if name in self.fields:
                            self.fields[name].disabled = True
        return KindForm

    def has_change_permission(self, request, obj=None):
        if obj and obj.status in {"active", "retired"}:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and obj.status in {"active", "retired"}:
            return False
        return super().has_delete_permission(request, obj)

    def save_model(self, request, obj, form, change):
        if change:
            current = Document.objects.select_for_update().get(pk=obj.pk)
            if current.status in {"active", "retired"}:
                raise PermissionDenied("Versi sudah disahkan/diarsipkan; muat ulang halaman.")
        if obj.status not in {"draft", "review"}:
            raise PermissionDenied("Gunakan Sahkan Revisi untuk memberlakukan dokumen.")
        super().save_model(request, obj, form, change)

    def can_revise(self, request, obj):
        return (obj.status == "active" and self.has_add_permission(request)
                and super().has_change_permission(request, obj))

    def change_view(self, request, object_id, form_url="", extra_context=None):
        obj = self.get_object(request, object_id)
        context = dict(extra_context or {})
        if obj:
            context["can_create_revision"] = self.can_revise(request, obj)
            context["can_activate_revision"] = (obj.status in {"draft", "review"}
                and self.has_change_permission(request, obj))
        return super().change_view(request, object_id, form_url, context)

    def revision_view(self, request, object_id):
        from django.core.exceptions import ValidationError
        from django.db import transaction, IntegrityError
        from django.template.response import TemplateResponse
        from django.shortcuts import redirect
        from django.contrib import messages
        from .revision import create_revision
        obj = get_object_or_404(self.get_queryset(request), pk=object_id)
        if not self.can_revise(request, obj):
            raise PermissionDenied
        if request.method == "POST":
            try:
                with transaction.atomic():
                    target, created = create_revision(obj.pk)
                    if created:
                        self.log_addition(request, target,
                            f"Draft revisi {target.revisi} disalin dari ID {obj.pk}, revisi {obj.revisi}.")
                self.message_user(request, "Draft revisi siap diperbarui." if created
                                  else "Draft revisi sudah ada; dibuka kembali.", messages.SUCCESS)
                return redirect(f"{self.admin_site.name}:smt_{self.model._meta.model_name}_change", target.pk)
            except (ValidationError, IntegrityError) as exc:
                error = "; ".join(exc.messages) if isinstance(exc, ValidationError) else "Revisi berubah bersamaan; muat ulang halaman."
                self.message_user(request, error, messages.ERROR)
        context = {**self.admin_site.each_context(request), "opts": self.model._meta,
                   "original": obj, "title": "Buat Revisi Baru", "mode": "revision"}
        return TemplateResponse(request, "admin/smt/revision_confirm.html", context)

    def activate_view(self, request, object_id):
        from django.core.exceptions import ValidationError
        from django.db import transaction, IntegrityError
        from django.template.response import TemplateResponse
        from django.shortcuts import redirect
        from django.contrib import messages
        from .revision import activate_revision
        obj = get_object_or_404(self.get_queryset(request), pk=object_id)
        if not self.has_change_permission(request, obj):
            raise PermissionDenied
        if obj.status not in {"draft", "review"}:
            raise PermissionDenied
        source = obj.revisi_sebelumnya
        if source and not super().has_change_permission(request, source):
            raise PermissionDenied
        class ActivationForm(forms.Form):
            tanggal_berlaku = forms.DateField(label="Tanggal berlaku",
                widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
        form = ActivationForm(request.POST if request.method == "POST" else None,
                              initial={"tanggal_berlaku": obj.tanggal_berlaku})
        if request.method == "POST" and form.is_valid():
            try:
                with transaction.atomic():
                    target, previous = activate_revision(obj.pk, form.cleaned_data["tanggal_berlaku"])
                    if previous:
                        self.log_change(request, previous,
                            f"Tidak Berlaku; digantikan ID {target.pk}, revisi {target.revisi}.")
                    self.log_change(request, target, "Disahkan menjadi Berlaku melalui konfirmasi revisi.")
                self.message_user(request, "Dokumen Berlaku; versi sebelumnya tersimpan sebagai arsip.", messages.SUCCESS)
                return redirect(f"{self.admin_site.name}:smt_{self.model._meta.model_name}_change", target.pk)
            except (ValidationError, IntegrityError) as exc:
                form.add_error(None, "; ".join(exc.messages) if isinstance(exc, ValidationError)
                               else "Revisi berubah bersamaan; muat ulang halaman.")
        context = {**self.admin_site.each_context(request), "opts": self.model._meta,
                   "original": obj, "title": "Sahkan Revisi", "mode": "activate", "form": form}
        return TemplateResponse(request, "admin/smt/revision_confirm.html", context)

    @admin.display(description="Riwayat revisi")
    def riwayat_revisi(self, obj):
        if not obj or not obj.pk:
            return "Simpan dokumen terlebih dahulu."
        ids = {obj.pk}
        frontier = {obj.pk}
        while frontier:
            from django.db.models import Q
            rows = list(Document.objects.filter(
                Q(pk__in=frontier) | Q(revisi_sebelumnya_id__in=frontier)
            ).values_list("pk", "revisi_sebelumnya_id"))
            found = {value for row in rows for value in row if value is not None}
            frontier = found - ids
            ids |= found
        from django.db.models import Q
        return "; ".join(
            f"{d.nomor} — Rev. {d.revisi}: {d.get_status_display()}"
            for d in Document.objects.filter(
                Q(pk__in=ids) | Q(jenis=obj.jenis, nomor=obj.nomor)
            ).order_by("dibuat_pada", "pk")
        )

    @admin.display(description="PDF")
    def lihat_pdf(self, obj):
        url = reverse(
            f"{self.admin_site.name}:smt_{self.model._meta.model_name}_pdf",
            args=[obj.pk],
        )
        return format_html(
            '<a href="{}" target="_blank" rel="noopener" '
            'title="Lihat output PDF" aria-label="Lihat output PDF" '
            'style="white-space:nowrap">📄 PDF</a>',
            url,
        )

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
        return [
            path("<int:object_id>/revision/", self.admin_site.admin_view(self.revision_view),
                 name=f"smt_{self.model._meta.model_name}_revision"),
            path("<int:object_id>/activate/", self.admin_site.admin_view(self.activate_view),
                 name=f"smt_{self.model._meta.model_name}_activate"),
        ] + [path("<int:object_id>/pdf/", self.admin_site.admin_view(self.document_pdf), name=f"smt_{self.model._meta.model_name}_pdf"), path("<int:object_id>/lampiran/<int:attachment_id>/", self.admin_site.admin_view(self.download), name=f"smt_{self.model._meta.model_name}_download")] + super().get_urls()

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
