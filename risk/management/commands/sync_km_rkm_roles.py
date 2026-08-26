from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from risk.models import ItemKontrakManajemen, KontrakManajemen, RKMItem, RKMSummary


ROLE_KM_ADMIN = "ROLE - KM ADMIN"
ROLE_RKM_ADMIN = "ROLE - RKM ADMIN"


@dataclass(frozen=True)
class RoleSpec:
    name: str
    models: tuple[type, ...]
    actions: tuple[str, ...] = ("view", "add", "change", "delete")


ROLE_SPECS = (
    RoleSpec(
        name=ROLE_KM_ADMIN,
        models=(KontrakManajemen, ItemKontrakManajemen),
    ),
    RoleSpec(
        name=ROLE_RKM_ADMIN,
        models=(RKMSummary, RKMItem),
    ),
)


def model_label(model):
    return f"{model._meta.app_label}.{model._meta.model_name}"


def resolve_permissions(spec):
    resolved = []
    missing = []

    for model in spec.models:
        ct = ContentType.objects.get_for_model(model)
        for action in spec.actions:
            codename = f"{action}_{model._meta.model_name}"
            perm = Permission.objects.filter(
                content_type=ct,
                codename=codename,
            ).first()
            if perm is None:
                missing.append(f"{model_label(model)}:{codename}")
            else:
                resolved.append(perm)

    if missing:
        raise CommandError(
            f"Permission tidak ditemukan untuk {spec.name}: "
            + ", ".join(missing)
        )

    return resolved


class Command(BaseCommand):
    help = (
        "Audit/sinkronisasi ROLE - KM ADMIN dan ROLE - RKM ADMIN. "
        "Default dry-run; gunakan --apply untuk menyimpan."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Buat/update Group dan permission.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        desired = {}

        self.stdout.write("=" * 78)
        self.stdout.write("SYNC ROLE KM / RKM ADMIN")
        self.stdout.write("=" * 78)
        self.stdout.write(f"Mode: {'APPLY' if apply else 'DRY RUN'}")

        for spec in ROLE_SPECS:
            perms = resolve_permissions(spec)
            desired[spec.name] = perms

            self.stdout.write("")
            self.stdout.write(f"[{spec.name}]")

            for model in spec.models:
                self.stdout.write(f"  Model: {model_label(model)}")

            for perm in perms:
                self.stdout.write(
                    f"  Permission: "
                    f"{perm.content_type.app_label}.{perm.codename}"
                )

            group = Group.objects.filter(name=spec.name).first()
            if group is None:
                self.stdout.write("  Status: group belum ada")
            else:
                current_ids = set(
                    group.permissions.values_list("pk", flat=True)
                )
                wanted_ids = {p.pk for p in perms}
                self.stdout.write(
                    f"  Status: existing group_id={group.pk}, "
                    f"permission_now={len(current_ids)}, "
                    f"add={len(wanted_ids-current_ids)}, "
                    f"remove={len(current_ids-wanted_ids)}"
                )

        if not apply:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING("DRY RUN: database tidak diubah.")
            )
            self.stdout.write(
                "Jika benar, jalankan: "
                "python manage.py sync_km_rkm_roles --apply"
            )
            return

        with transaction.atomic():
            for spec in ROLE_SPECS:
                group, created = Group.objects.get_or_create(name=spec.name)
                group.permissions.set(desired[spec.name])

                self.stdout.write(
                    self.style.SUCCESS(
                        f"{'CREATED' if created else 'UPDATED'} "
                        f"{spec.name}: group_id={group.pk}, "
                        f"permissions={group.permissions.count()}"
                    )
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS("SYNC ROLE KM/RKM BERHASIL")
        )
        self.stdout.write(
            "Role dapat diberikan ke lebih dari satu user RENKIN."
        )
