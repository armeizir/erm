"""Report-scoped PIC choices and signed browser baselines for inline edits."""
from django import forms
from django.core import signing
from django.db.models import Q
from masterdata.models import OrganizationUnit, OrganizationUnitAccessGroup

SALT = 'monthly-report.pic-scope.v1'
ALIASES = {
    'UB KITRAN': {'UB KITRANS'},
    'UB KITRANS': {'UB KITRAN'},
    'SETPER': {'SEKPER'},
    'SEKPER': {'SETPER'},
}


def organization_choices(report, current_id=None):
    """Use explicit group mappings, otherwise exact unit names; never all units."""
    roots = set()
    if report is not None and report.reassessment_id:
        group = report.reassessment.unit_bisnis
        if group is not None:
            roots.update(OrganizationUnitAccessGroup.objects.filter(
                group_id=group.pk, aktif=True,
            ).values_list('organization_unit_id', flat=True))
            if not roots:
                names = {group.name.strip(), *ALIASES.get(group.name.strip(), set())}
                query = Q(pk__in=[])
                for name in names:
                    query |= Q(name__iexact=name)
                roots.update(OrganizationUnit.objects.filter(query).values_list('pk', flat=True))
    visited = set(roots)
    frontier = set(roots)
    while frontier:
        children = set(OrganizationUnit.objects.filter(
            parent_id__in=frontier,
        ).values_list('pk', flat=True)) - visited
        visited.update(children)
        frontier = children
    query = Q(pk__in=visited, aktif=True)
    # Preserve a historical current value, but do not offer other out-of-scope units.
    if current_id:
        query |= Q(pk=current_id)
    return OrganizationUnit.objects.filter(query).order_by('code', 'pk')


def configure_pic_field(form, report):
    name = 'realisasi_pic_organization_unit'
    if name not in form.fields:
        return
    current = getattr(form.instance, name + '_id', None)
    form._pic_original_id = current
    field = form.fields[name]
    field.label = 'PIC pelaksanaan — unit organisasi'
    field.queryset = organization_choices(report, current)
    # A plain scoped select prevents Django's global autocomplete endpoint
    # from ignoring this form's queryset. Search is initialized locally.
    field.widget = forms.Select(attrs={'class': 'mrr-pic-scope', 'data-pic-scope': '1'})
    field.widget.choices = field.choices
    field.help_text = 'Pilih bidang/unit pelaksana atau subbidangnya, lalu klik Save.'
    if not current and getattr(form.instance, 'realisasi_pic', None):
        legacy = form.instance.realisasi_pic.strip()
        matches = list(field.queryset.filter(Q(code__iexact=legacy) | Q(name__iexact=legacy))[:2])
        if len(matches) == 1:
            form.initial[name] = matches[0].pk
    if not field.queryset.exists():
        field.help_text = ('Cakupan organisasi bidang ini belum terdaftar. '
                           'Administrator perlu memeriksa mapping organisasi; pilihan tidak diperluas ke seluruh perusahaan.')


def pic_baseline(form):
    if form.is_bound:
        return form.data.get(form.add_prefix('_row_pic_baseline'), '')
    item = form.instance
    if not item or not item.pk or 'realisasi_pic_organization_unit' not in form.fields:
        return ''
    selected = form.initial.get('realisasi_pic_organization_unit', item.realisasi_pic_organization_unit_id)
    selected = getattr(selected, 'pk', selected)
    return signing.dumps({'item': item.pk, 'version': form.concurrency_token,
                          'selected': str(selected or '')}, salt=SALT, compress=True)


def pic_selection_changed(form):
    if not form.is_bound or not form.instance or not form.instance.pk:
        return False
    token = form.data.get(form.add_prefix('_row_pic_baseline'), '')
    if not token:
        return False
    try:
        payload = signing.loads(token, salt=SALT)
    except (signing.BadSignature, ValueError, TypeError):
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get('item') != form.instance.pk:
        return False
    if payload.get('version') != form.data.get(form.add_prefix('_row_version'), ''):
        return False
    name = form.add_prefix('realisasi_pic_organization_unit')
    if name not in form.data:
        return False
    return str(form.data.get(name) or '') != payload.get('selected')


def sync_pic_text(form, obj):
    name = 'realisasi_pic_organization_unit'
    if name not in form.cleaned_data:
        return
    organization = form.cleaned_data[name]
    if organization is not None:
        obj.realisasi_pic = str(organization)
    elif getattr(form, '_pic_original_id', None) is not None:
        obj.realisasi_pic = None
