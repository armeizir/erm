from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from .nas_models import NASEvidenceLocation, NASEvidence
from .nas_services import can_access_report,can_verify,review_evidence


class NASEvidenceLocationAdmin(admin.ModelAdmin):
    list_display=("report","folder_path","enabled")
    search_fields=("folder_path",)
    readonly_fields=("updated_at",)
    actions=None
    def has_module_permission(self,request): return request.user.is_active and request.user.is_superuser
    def has_view_permission(self,request,obj=None): return self.has_module_permission(request)
    def has_add_permission(self,request): return self.has_module_permission(request)
    def has_change_permission(self,request,obj=None): return self.has_module_permission(request)
    def has_delete_permission(self,request,obj=None): return False


class NASEvidenceForm(forms.ModelForm):
    class Meta:
        model=NASEvidence
        fields=("title","read_url","relative_path","description")


class NASEvidenceAdminMixin:
    def get_fields(self,request,obj=None):
        fields=list(super().get_fields(request,obj))
        if "nas_evidence_button" not in fields: fields.append("nas_evidence_button")
        return fields
    def get_readonly_fields(self,request,obj=None):
        return tuple(super().get_readonly_fields(request,obj))+("nas_evidence_button",)
    @admin.display(description="Eviden NAS")
    def nas_evidence_button(self,obj):
        if not obj or not obj.pk: return "Simpan laporan terlebih dahulu."
        url=reverse(f"{self.admin_site.name}:monthly_report_monthlyriskreport_nas_evidence",args=[obj.pk])
        return format_html('<a class="button" href="{}">Unggah / Kelola Eviden NAS</a>',url)
    def get_urls(self):
        return [path("<int:object_id>/nas-evidence/",self.admin_site.admin_view(self.nas_evidence_view),
            name="monthly_report_monthlyriskreport_nas_evidence")]+super().get_urls()
    def nas_evidence_view(self,request,object_id):
        report=self.get_object(request,str(object_id))
        if report is None or not self.has_view_permission(request,report): raise Http404
        if not can_access_report(request.user,report): raise PermissionDenied
        location=NASEvidenceLocation.objects.filter(report=report,enabled=True).first()
        working=report.status in {"draft","revision"} and not getattr(report,"is_locked",False)
        can_add=working and self.has_change_permission(request,report) and location is not None
        reviewer=working and can_verify(request.user)
        form=NASEvidenceForm()
        if request.method=="POST":
            action=request.POST.get("action","")
            if action=="register":
                if not can_add: raise PermissionDenied
                instance=NASEvidence(report=report,location=location,uploaded_by=request.user,
                    folder_snapshot=location.folder_path,upload_url_snapshot=location.upload_url)
                form=NASEvidenceForm(request.POST,instance=instance)
                if form.is_valid():
                    try:
                        with transaction.atomic():
                            evidence=form.save()
                            self.log_change(request,report,f"Eviden NAS #{evidence.pk} dicatat; menunggu verifikasi.")
                        self.message_user(request,"Eviden NAS dicatat; menunggu verifikasi petugas.",messages.SUCCESS)
                        return redirect(request.path)
                    except ValidationError as exc: form.add_error(None,exc)
            elif action in {"verify","revoke"}:
                if not reviewer: raise PermissionDenied
                try: evidence_id=int(request.POST.get("evidence_id",""))
                except ValueError: raise Http404
                if not NASEvidence.objects.filter(pk=evidence_id,report=report).exists(): raise Http404
                if action=="verify" and request.POST.get("confirmed")!="yes":
                    self.message_user(request,"Buka link baca dan konfirmasi isi berkas terlebih dahulu.",messages.ERROR)
                else:
                    try:
                        with transaction.atomic():
                            row=review_evidence(evidence_id,request.user,action,request.POST.get("note",""))
                            self.log_change(request,report,f"Eviden NAS #{row.pk}: {action}.")
                        self.message_user(request,"Status verifikasi eviden diperbarui.",messages.SUCCESS)
                        return redirect(request.path)
                    except ValidationError as exc:
                        self.message_user(request,"; ".join(exc.messages),messages.ERROR)
            else: raise PermissionDenied
        records=NASEvidence.objects.filter(report=report).select_related("uploaded_by","verified_by").prefetch_related("reviews__actor")
        from django.utils.text import slugify
        unit = str(report.reassessment.unit_bisnis)
        unit_code = slugify(unit).replace('-', '_').upper() or 'BIDANG'
        period_code = report.periode.tanggal_mulai.strftime('%Y-%m')
        upload_name = f"{unit_code}_{period_code}"
        upload_url = location.upload_url if location else 'https://brightbox.plnbatam.com:5001/sharing/PZ2vzmUoK'
        can_upload = working and self.has_change_permission(request, report)
        context={**self.admin_site.each_context(request),"opts":self.model._meta,
            "title":"Eviden NAS", "report":report,"location":location,"records":records,
            "upload_url":upload_url,"upload_name":upload_name,"can_upload":can_upload,"can_add":can_add,"can_verify":reviewer,"form":form,
            "back_url":reverse(f"{self.admin_site.name}:monthly_report_monthlyriskreport_change",args=[report.pk])}
        return TemplateResponse(request,"admin/monthly_report/nas_evidence.html",context)
