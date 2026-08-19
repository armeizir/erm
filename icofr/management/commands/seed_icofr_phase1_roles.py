from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create/update Phase 1 ICoFR administrator role with model permissions."

    def handle(self, *args, **options):
        group, _ = Group.objects.get_or_create(name="ROLE - ICOFR ADMIN")
        permissions = Permission.objects.filter(content_type__app_label="icofr")
        group.permissions.set(permissions)
        self.stdout.write(self.style.SUCCESS(f"{group.name}: {permissions.count()} permissions assigned."))
