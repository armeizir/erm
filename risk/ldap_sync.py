from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.dispatch import receiver
from django_auth_ldap.backend import populate_user


def _first(value):
    if not value:
        return None
    if isinstance(value, (list, tuple)):
        return value[0]
    return value


@receiver(populate_user)
def sync_ldap_user(sender, user=None, ldap_user=None, **kwargs):
    attrs = ldap_user.attrs

    full_name = _first(attrs.get("name"))
    email = _first(attrs.get("mail"))
    employee_id = _first(attrs.get("employeeID"))
    title = _first(attrs.get("title"))
    department = _first(attrs.get("department"))

    if email:
        user.email = email

    if full_name:
        user.first_name = full_name
        user.last_name = ""

    user.is_active = True
    user.is_staff = True
    user.set_unusable_password()
    user.save()

    if not department:
        raise PermissionDenied("Akun LDAP tidak memiliki department.")

    try:
        bidang_group = Group.objects.get(name=department)
    except Group.DoesNotExist:
        raise PermissionDenied(
            f"Bidang / Unit Bisnis '{department}' belum terdaftar di aplikasi."
        )

    # Hapus semua group organisasi lama, lalu set sesuai LDAP
    excluded_groups = ["Super Admin", "Admin Sistem"]
    old_groups = user.groups.exclude(name__in=excluded_groups)
    user.groups.remove(*old_groups)
    user.groups.add(bidang_group)