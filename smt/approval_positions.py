"""Current position holders, resolved from the existing employment history."""
from django.db.models import Q
from django.utils import timezone
from django.core.exceptions import ValidationError

def current_positions():
    from risk.models import RiwayatJabatanUser
    today = timezone.localdate()
    return RiwayatJabatanUser.objects.filter(
        user__is_active=True, tanggal_mulai__lte=today
    ).filter(Q(tanggal_selesai__isnull=True) | Q(tanggal_selesai__gte=today)).exclude(jabatan='')

def holds_position(actor, position):
    return bool(actor and actor.is_active and position and
                current_positions().filter(user_id=actor.pk, jabatan=position).exists())

def record_action(target, role, actor):
    position = getattr(target, role + '_jabatan')
    if not holds_position(actor, position):
        raise ValidationError('Proses hanya dapat dilakukan pemegang jabatan yang dipilih dan masih berlaku.')
    setattr(target, role + '_user', actor)
    setattr(target, role + '_nama', actor.get_full_name().strip() or actor.get_username())
    setattr(target, role + '_tanggal', timezone.localdate())


def approval_identity(document, role):
    """Saved actor for completed steps; current holders are only a draft preview."""
    name = getattr(document, role + '_nama', '')
    position = getattr(document, role + '_jabatan', '')
    processed = getattr(document, role + '_tanggal', None)
    if document.status in {'active', 'retired'}:
        return name or '-', position or '-'
    if role == 'penyusun':
        user = getattr(document, 'penyusun_user', None)
        if user:
            name = name or user.get_full_name().strip() or user.get_username()
            if not position:
                titles = list(current_positions().filter(user_id=user.pk).order_by('jabatan')
                              .values_list('jabatan', flat=True).distinct())
                position = '; '.join(titles)
    elif not processed:
        # An old actor snapshot must not imply this revision was verified again.
        users = current_positions().filter(jabatan=position).select_related('user').order_by('user_id') if position else []
        names = dict((row.user_id, row.user.get_full_name().strip() or row.user.get_username()) for row in users)
        name = '; '.join(names.values())
        if len(names) > 1:
            name += ' (beberapa pemegang jabatan)'
    return name or '-', position or '-'
