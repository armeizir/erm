from django import forms
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from .models import Document
from .richtext import RICH_FIELDS
from .ai_service import AIReviewError, fingerprint, review, corrected_value

SALT = 'smt.spelling.review.v1'

class AIReviewForm(forms.Form):
    fields = forms.MultipleChoiceField(label='Bagian yang diperiksa',
        choices=[(name, Document._meta.get_field(name).verbose_name) for name in RICH_FIELDS],
        widget=forms.CheckboxSelectMultiple)

class AIReviewAdminMixin:
    def ai_review_view(self, request, object_id):
        obj = get_object_or_404(self.get_queryset(request), pk=object_id)
        if not self.has_view_or_change_permission(request, obj):raise PermissionDenied
        form = AIReviewForm(request.POST if request.method == 'POST' and request.POST.get('action') == 'review' else None)
        suggestions, token, error_message = None, '', ''
        if request.method == 'POST':
            try:
                if request.POST.get('action') == 'review' and form.is_valid():
                    if not cache.add(f'smt-ai-review:{request.user.pk}', True, timeout=30):
                        raise AIReviewError('Tunggu 30 detik sebelum memeriksa lagi.')
                    suggestions = review(obj, form.cleaned_data['fields'])
                    token = signing.dumps({'document': obj.pk, 'user': request.user.pk,
                        'fingerprint': fingerprint(obj), 'suggestions': suggestions}, salt=SALT, compress=True)
                elif request.POST.get('action') == 'apply':
                    data = signing.loads(request.POST.get('token', ''), salt=SALT, max_age=900)
                    if data['document'] != obj.pk or data['user'] != request.user.pk:raise PermissionDenied
                    indices = request.POST.getlist('selected')
                    if not indices:raise AIReviewError('Pilih minimal satu saran.')
                    if any(not i.isdigit() or int(i) >= len(data['suggestions']) for i in indices):
                        raise AIReviewError('Pilihan saran tidak valid.')
                    selected = [data['suggestions'][i] for i in sorted({int(i) for i in indices})]
                    with transaction.atomic():
                        current = Document.objects.select_for_update().get(pk=obj.pk)
                        if current.status not in {'draft', 'review'} or not self.has_change_permission(request, current):raise PermissionDenied
                        if fingerprint(current) != data['fingerprint']:
                            raise AIReviewError('Dokumen berubah sejak diperiksa. Jalankan pemeriksaan ulang.')
                        changed = []
                        for field in RICH_FIELDS:
                            items = [item for item in selected if item['field'] == field]
                            if items:
                                setattr(current, field, corrected_value(getattr(current, field), items))
                                changed.append(field)
                        current.save(update_fields=changed + ['diperbarui_pada'])
                        self.log_change(request, current, 'Saran ejaan AI dipilih dan diterapkan: ' + ', '.join(changed))
                    self.message_user(request, 'Saran terpilih diterapkan. Perubahan isi perlu diverifikasi kembali.')
                    return redirect(f'{self.admin_site.name}:smt_{self.model._meta.model_name}_change', obj.pk)
            except signing.BadSignature:
                error_message = 'Hasil pemeriksaan kedaluwarsa/tidak valid. Jalankan pemeriksaan ulang.'
            except AIReviewError as exc:
                error_message = str(exc)
        return TemplateResponse(request, 'admin/smt/ai_review.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta, 'original': obj,
            'title': 'Periksa Ejaan AI', 'form': form, 'suggestions': suggestions, 'token': token,
            'error_message': error_message, 'can_apply': obj.status in {'draft', 'review'} and self.has_change_permission(request, obj),
            'change_url': __import__('django.urls', fromlist=['reverse']).reverse(
                f'{self.admin_site.name}:smt_{self.model._meta.model_name}_change', args=[obj.pk])})
