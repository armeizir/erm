import hashlib
import json
import uuid
from django import forms
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from .models import Document, Attachment
from .ai_service import AIReviewError, fingerprint
from .flow_service import generate_flow, validate_flow
from .flow_pdf import build_flow_pdf

SALT='smt.procedure.flow.v1'

def source_fingerprint(obj):
    return hashlib.sha256(json.dumps([obj.pk,obj.jenis,obj.nomor,obj.revisi,obj.judul,fingerprint(obj)]).encode()).hexdigest()

class SaveFlowForm(forms.Form):
    reviewed=forms.BooleanField(label='Saya telah memeriksa diagram dan akan menyimpannya sebagai lampiran Draft AI.')

class AIFlowAdminMixin:
    def ai_flow_view(self,request,object_id):
        if self.kind!='PI':raise Http404
        obj=get_object_or_404(self.get_queryset(request),pk=object_id)
        if not self.has_view_or_change_permission(request,obj):raise PermissionDenied
        graph=None;ticket='';error_message='';saved_name=None;saved_storage=None
        if request.method=='POST':
            action=request.POST.get('action')
            try:
                if action=='generate':
                    if not cache.add(f'smt-ai-flow:{request.user.pk}',True,timeout=30):
                        raise AIReviewError('Tunggu 30 detik sebelum membuat diagram lagi.')
                    graph=generate_flow(obj)
                    ticket=signing.dumps({'document':obj.pk,'user':request.user.pk,'source':source_fingerprint(obj),
                        'nonce':uuid.uuid4().hex,'graph':graph},salt=SALT,compress=True)
                elif action in {'preview','save'}:
                    ticket=request.POST.get('ticket','')
                    data=signing.loads(ticket,salt=SALT,max_age=900)
                    if data['document']!=obj.pk or data['user']!=request.user.pk:raise PermissionDenied
                    graph=validate_flow(data['graph'])
                    name=f"Diagram Alir AI - Rev {obj.revisi} - {data['nonce'][:12]} - DRAFT"
                    if action=='preview':
                        if source_fingerprint(obj)!=data['source']:raise AIReviewError('Isi PI berubah. Buat diagram ulang.')
                        response=HttpResponse(build_flow_pdf(obj,graph,data['source']),content_type='application/pdf')
                        response['Content-Disposition']='inline; filename="diagram-alir-draft-ai.pdf"'
                        response['Cache-Control']='private, no-store';response['X-Content-Type-Options']='nosniff'
                        return response
                    if not SaveFlowForm(request.POST).is_valid():raise AIReviewError('Centang konfirmasi pemeriksaan sebelum menyimpan lampiran.')
                    try:
                        with transaction.atomic():
                            current=Document.objects.select_for_update().get(pk=obj.pk)
                            if current.status not in {'draft','review'} or not self.has_change_permission(request,current):raise PermissionDenied
                            existing=Attachment.objects.filter(document=current,nama=name,jenis='alur').first()
                            if existing:
                                self.message_user(request,'Diagram ini sudah tersimpan. Tidak dibuat duplikat.')
                                return redirect(f'{self.admin_site.name}:smt_{self.model._meta.model_name}_change',obj.pk)
                            if source_fingerprint(current)!=data['source']:raise AIReviewError('Isi PI berubah. Buat diagram ulang.')
                            pdf=build_flow_pdf(current,graph,data['source'])
                            attachment=Attachment(document=current,nama=name,jenis='alur')
                            attachment.berkas.save('diagram-alir-ai.pdf',ContentFile(pdf),save=False)
                            saved_name=attachment.berkas.name;saved_storage=attachment.berkas.storage
                            attachment.full_clean();attachment.save()
                            if current.status=='review':
                                current.status='draft';current.verifikator_tanggal=None;current.pengesah_tanggal=None
                            current.save(update_fields=['status','verifikator_tanggal','pengesah_tanggal','diperbarui_pada'])
                            self.log_addition(request,attachment,'Diagram alir AI disimpan setelah konfirmasi pengguna; perlu verifikasi.')
                            self.log_change(request,current,f'Lampiran diagram alir AI ditambahkan, ID {attachment.pk}; verifikasi perlu diulang bila sebelumnya Dalam Review.')
                    except BaseException:
                        if saved_name and saved_storage:saved_storage.delete(saved_name)
                        raise
                    self.message_user(request,'Diagram disimpan sebagai lampiran Diagram Alir. Dokumen tetap perlu verifikasi/pengesahan.')
                    return redirect(f'{self.admin_site.name}:smt_{self.model._meta.model_name}_change',obj.pk)
            except signing.BadSignature:
                error_message='Pratinjau kedaluwarsa/tidak valid. Buat diagram ulang.'
            except (AIReviewError,ValueError) as exc:
                error_message=str(exc)
        can_save=obj.status in {'draft','review'} and self.has_change_permission(request,obj)
        response=TemplateResponse(request,'admin/smt/ai_flow.html',{
            **self.admin_site.each_context(request),'opts':self.model._meta,'original':obj,
            'title':'Buat Flow Prosedur AI','graph':graph,'ticket':ticket,'error_message':error_message,
            'can_save':can_save,'save_form':SaveFlowForm(),
            'change_url':reverse(f'{self.admin_site.name}:smt_{self.model._meta.model_name}_change',args=[obj.pk])})
        response['Cache-Control']='private, no-store'
        return response
