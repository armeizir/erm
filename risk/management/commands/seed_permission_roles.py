from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction


ROLE_DEFINITIONS = [
    {
        "name": "ROLE - Profil Risiko Unit - Lihat",
        "permissions": [
            ("risk", "view_reassessmentsummary"),
            ("risk", "view_reassessmentitem"),
        ],
    },
    {
        "name": "ROLE - KM - Lihat",
        "permissions": [
            ("km", "view_kontrakmanajemen"),
            ("km", "view_kontrakmanajemenbagian"),
            ("km", "view_kontrakmanajemenitem"),
            ("km", "view_kontrakmanajementargetperiode"),
        ],
    },
    {
        "name": "ROLE - RKM - Lihat",
        "permissions": [
            ("risk", "view_rkmsummary"),
            ("risk", "view_rkmitem"),
        ],
    },
    {
        "name": "ROLE - Laporan Risiko Bulanan - Lihat",
        "permissions": [
            ("monthly_report", "view_monthlyriskreport"),
            ("monthly_report", "view_monthlyriskreportitem"),
            ("monthly_report", "view_monthlyriskreportkmalignment"),
            ("monthly_report", "view_monthlyriskreportchange"),
            ("monthly_report", "view_monthlyriskreportlossevent"),
            ("monthly_report", "view_monthlyriskreportsubmissionlog"),
        ],
    },
    {
        "name": "ROLE - Laporan Risiko Bulanan - Editor",
        "permissions": [
            ("monthly_report", "add_monthlyriskreport"),
            ("monthly_report", "change_monthlyriskreport"),
            ("monthly_report", "delete_monthlyriskreport"),
            ("monthly_report", "view_monthlyriskreport"),
            ("monthly_report", "add_monthlyriskreportitem"),
            ("monthly_report", "change_monthlyriskreportitem"),
            ("monthly_report", "delete_monthlyriskreportitem"),
            ("monthly_report", "view_monthlyriskreportitem"),
            ("monthly_report", "add_monthlyriskreportkmalignment"),
            ("monthly_report", "change_monthlyriskreportkmalignment"),
            ("monthly_report", "delete_monthlyriskreportkmalignment"),
            ("monthly_report", "view_monthlyriskreportkmalignment"),
            ("monthly_report", "add_monthlyriskreportchange"),
            ("monthly_report", "change_monthlyriskreportchange"),
            ("monthly_report", "delete_monthlyriskreportchange"),
            ("monthly_report", "view_monthlyriskreportchange"),
            ("monthly_report", "add_monthlyriskreportlossevent"),
            ("monthly_report", "change_monthlyriskreportlossevent"),
            ("monthly_report", "delete_monthlyriskreportlossevent"),
            ("monthly_report", "view_monthlyriskreportlossevent"),
            ("monthly_report", "add_monthlyriskreportsubmissionlog"),
            ("monthly_report", "change_monthlyriskreportsubmissionlog"),
            ("monthly_report", "delete_monthlyriskreportsubmissionlog"),
            ("monthly_report", "view_monthlyriskreportsubmissionlog"),
        ],
    },
    {
        "name": "ROLE - Master Organisasi - Lihat",
        "permissions": [
            ("masterdata", "view_companycode"),
            ("masterdata", "view_businessarea"),
            ("masterdata", "view_personnelarea"),
            ("masterdata", "view_personnelsubarea"),
            ("masterdata", "view_directorate"),
            ("masterdata", "view_division"),
            ("masterdata", "view_organizationunit"),
        ],
    },
]


class Command(BaseCommand):
    help = "Create standard permission role groups for ERM admin users."

    def add_arguments(self, parser):
        parser.add_argument(
            "--assign-user",
            action="append",
            default=[],
            help="Optional username to assign selected role groups to. Can be repeated.",
        )
        parser.add_argument(
            "--role",
            action="append",
            default=[],
            help="Role group name to assign when --assign-user is used. Can be repeated.",
        )

    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model

        created_count = 0
        updated_count = 0

        with transaction.atomic():
            for role in ROLE_DEFINITIONS:
                group, created = Group.objects.get_or_create(name=role["name"])
                permissions = self._resolve_permissions(role["permissions"])
                group.permissions.set(permissions)
                created_count += int(created)
                updated_count += int(not created)
                self.stdout.write(
                    f"{'Created' if created else 'Updated'} {group.name}: "
                    f"{len(permissions)} permissions"
                )

            if options["assign_user"]:
                if not options["role"]:
                    raise RuntimeError("--assign-user requires at least one --role")

                User = get_user_model()
                role_groups = Group.objects.filter(name__in=options["role"])
                missing_roles = sorted(set(options["role"]) - set(role_groups.values_list("name", flat=True)))
                if missing_roles:
                    raise RuntimeError(f"Unknown roles: {', '.join(missing_roles)}")

                for username in options["assign_user"]:
                    user = User.objects.get(username=username)
                    user.groups.add(*role_groups)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Assigned {role_groups.count()} role groups to {username}"
                        )
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created groups: {created_count}. Updated groups: {updated_count}."
            )
        )

    def _resolve_permissions(self, permission_specs):
        permissions = []
        missing = []
        for app_label, codename in permission_specs:
            permission = Permission.objects.filter(
                content_type__app_label=app_label,
                codename=codename,
            ).first()
            if permission:
                permissions.append(permission)
            else:
                missing.append(f"{app_label}.{codename}")

        if missing:
            raise RuntimeError(f"Missing permissions: {', '.join(missing)}")
        return permissions
