from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction

from risk.access_policy import (
    SIMPLE_ACCESS_ROLES,
    is_organizational_group_name,
    permission_specs_for_level,
)
from risk.models import PenugasanUnitBisnis


class Command(BaseCommand):
    help = (
        "Sinkronisasi hak akses sederhana READ/EDIT/ADMIN "
        "untuk user Bidang dan Unit Bisnis."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Terapkan perubahan. Tanpa flag ini hanya DRY-RUN.",
        )

        parser.add_argument(
            "--clear-direct-permissions",
            action="store_true",
            help=(
                "Hapus direct user permissions pada user BID/UB. "
                "Gunakan hanya setelah audit."
            ),
        )

        parser.add_argument(
            "--remove-legacy-role-groups",
            action="store_true",
            help=(
                "Lepaskan ROLE lama selain ROLE - ACCESS - *. "
                "Gunakan hanya setelah audit."
            ),
        )

    def _resolve_permissions(self, level):
        permissions = []
        missing = []

        for app_label, codename in sorted(
            permission_specs_for_level(level)
        ):
            qs = Permission.objects.filter(
                content_type__app_label=app_label,
                codename=codename,
            )

            count = qs.count()

            if count == 1:
                permissions.append(qs.first())
            elif count == 0:
                missing.append(
                    f"{app_label}.{codename}"
                )
            else:
                raise RuntimeError(
                    f"Permission ambigu: "
                    f"{app_label}.{codename} "
                    f"({count} records)"
                )

        return permissions, missing

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        clear_direct = options[
            "clear_direct_permissions"
        ]
        remove_legacy = options[
            "remove_legacy_role_groups"
        ]

        User = get_user_model()

        mode = "APPLY" if apply_changes else "DRY-RUN"

        self.stdout.write("=" * 100)
        self.stdout.write(
            f"SIMPLE ACCESS ROLE SYNC - {mode}"
        )
        self.stdout.write("=" * 100)

        org_groups = [
            group
            for group in Group.objects.all().order_by("name")
            if is_organizational_group_name(group.name)
        ]

        self.stdout.write(
            f"Organization groups: "
            f"{len(org_groups)}"
        )

        for group in org_groups:
            self.stdout.write(
                f"  - {group.name}"
                f" | current_permissions="
                f"{group.permissions.count()}"
                f" | users={group.user_set.count()}"
            )

        role_objects = {}
        role_permissions = {}

        for level, role_name in SIMPLE_ACCESS_ROLES.items():
            permissions, missing = (
                self._resolve_permissions(level)
            )

            # DRY-RUN harus benar-benar read-only:
            # jangan membuat Group baru bila --apply tidak diberikan.
            if apply_changes:
                role, created = Group.objects.get_or_create(
                    name=role_name
                )
                role.permissions.set(permissions)
            else:
                role = Group.objects.filter(
                    name=role_name
                ).first()

                if role is None:
                    # Object sementara, tidak pernah disimpan ke DB.
                    role = Group(name=role_name)

                created = role.pk is None

            role_objects[level] = role
            role_permissions[level] = permissions

            self.stdout.write(
                f"\n{role_name}:"
                f" permissions={len(permissions)}"
                f" missing={len(missing)}"
                f" planned_create={created}"
            )

            for item in missing:
                self.stdout.write(
                    self.style.WARNING(
                        f"  MISSING: {item}"
                    )
                )

        org_group_ids = [
            group.pk
            for group in org_groups
        ]

        users = (
            User.objects
            .filter(groups__id__in=org_group_ids)
            .distinct()
            .order_by("username")
        )

        self.stdout.write(
            f"\nUsers in BID/UB groups: {users.count()}"
        )

        simple_role_names = set(
            SIMPLE_ACCESS_ROLES.values()
        )

        planned = {
            "READ": 0,
            "EDIT": 0,
            "SUPERUSER_SKIP": 0,
        }

        with transaction.atomic():
            # -------------------------------------------------
            # Group organisasi hanya untuk scope.
            # Permission langsung group organisasi dihapus.
            # -------------------------------------------------
            if apply_changes:
                for group in org_groups:
                    group.permissions.clear()

            for user in users:
                org_names = list(
                    user.groups.filter(
                        pk__in=org_group_ids
                    ).values_list(
                        "name",
                        flat=True,
                    )
                )

                current_simple_roles = list(
                    user.groups.filter(
                        name__in=simple_role_names
                    ).values_list(
                        "name",
                        flat=True,
                    )
                )

                legacy_roles = list(
                    user.groups.filter(
                        name__startswith="ROLE - "
                    )
                    .exclude(
                        name__in=simple_role_names
                    )
                    .values_list(
                        "name",
                        flat=True,
                    )
                )

                direct_permission_count = (
                    user.user_permissions.count()
                )

                if user.is_superuser:
                    planned["SUPERUSER_SKIP"] += 1

                    self.stdout.write(
                        f"\nSKIP SUPERUSER: "
                        f"{user.username}"
                        f" | org={org_names}"
                    )
                    continue

                # User yang punya penugasan MR aktif dianggap EDIT.
                # User biasa dalam BID/UB otomatis READ.
                has_active_assignment = (
                    PenugasanUnitBisnis.objects
                    .filter(
                        user=user,
                        aktif=True,
                        unit_bisnis_id__in=org_group_ids,
                    )
                    .exists()
                )

                target_level = (
                    "EDIT"
                    if has_active_assignment
                    else "READ"
                )

                planned[target_level] += 1

                self.stdout.write(
                    f"\nUSER: {user.username}"
                    f" | org={org_names}"
                    f" | target={target_level}"
                    f" | current_simple="
                    f"{current_simple_roles}"
                    f" | legacy_roles="
                    f"{legacy_roles}"
                    f" | direct_permissions="
                    f"{direct_permission_count}"
                )

                if not apply_changes:
                    continue

                # Hanya satu simple access role.
                user.groups.remove(
                    *role_objects.values()
                )

                user.groups.add(
                    role_objects[target_level]
                )

                if (
                    remove_legacy
                    and legacy_roles
                ):
                    legacy_group_objects = (
                        Group.objects.filter(
                            name__in=legacy_roles
                        )
                    )

                    user.groups.remove(
                        *legacy_group_objects
                    )

                if clear_direct:
                    user.user_permissions.clear()

            if not apply_changes:
                # Safety: DRY-RUN tidak boleh menyimpan role baru
                # yang tercipta lewat get_or_create.
                transaction.set_rollback(True)

        self.stdout.write("\n" + "=" * 100)
        self.stdout.write("SUMMARY")
        self.stdout.write("=" * 100)

        self.stdout.write(
            f"READ            : {planned['READ']}"
        )
        self.stdout.write(
            f"EDIT            : {planned['EDIT']}"
        )
        self.stdout.write(
            f"SUPERUSER SKIP  : "
            f"{planned['SUPERUSER_SKIP']}"
        )

        if apply_changes:
            self.stdout.write(
                self.style.SUCCESS(
                    "\nPERUBAHAN BERHASIL DITERAPKAN."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "\nDRY-RUN SAJA. "
                    "TIDAK ADA DATA YANG DIUBAH."
                )
            )
