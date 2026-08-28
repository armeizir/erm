from collections import defaultdict

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from risk.models import PenugasanUnitBisnis


READ_GROUP = "ROLE - UNIT - READ"
EDIT_GROUP = "ROLE - ACCESS - EDIT"


class Command(BaseCommand):
    help = (
        "Sinkronisasi role akses untuk seluruh Risk Officer dan "
        "Risk Champion aktif. Default DRY-RUN."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Simpan perubahan group user.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]

        read_group = Group.objects.filter(
            name=READ_GROUP
        ).first()

        edit_group = Group.objects.filter(
            name=EDIT_GROUP
        ).first()

        if not read_group:
            raise CommandError(
                f"Group belum tersedia: {READ_GROUP}"
            )

        if not edit_group:
            raise CommandError(
                f"Group belum tersedia: {EDIT_GROUP}"
            )

        role_officer = PenugasanUnitBisnis.ROLE_RISK_OFFICER
        role_champion = PenugasanUnitBisnis.ROLE_RISK_CHAMPION

        assignments = (
            PenugasanUnitBisnis.objects
            .filter(
                aktif=True,
                peran__in=[
                    role_officer,
                    role_champion,
                ],
                user__is_active=True,
            )
            .select_related(
                "user",
                "unit_bisnis",
            )
            .order_by(
                "user__username",
                "unit_bisnis__name",
                "peran",
                "pk",
            )
        )

        by_user = defaultdict(
            lambda: {
                "user": None,
                "roles": set(),
                "units": set(),
            }
        )

        for assignment in assignments:
            row = by_user[assignment.user_id]
            row["user"] = assignment.user
            row["roles"].add(assignment.peran)
            row["units"].add(
                assignment.unit_bisnis.name
            )

        print("=" * 110)
        print(
            "SYNC RISK ROLE ACCESS "
            f"| MODE={'APPLY' if apply else 'DRY-RUN'}"
        )
        print("=" * 110)

        print()
        print("Kebijakan:")
        print(
            "Risk Champion -> ROLE - UNIT - READ"
        )
        print(
            "Risk Officer  -> ROLE - UNIT - READ "
            "+ ROLE - ACCESS - EDIT"
        )

        total = len(by_user)
        officer_count = 0
        champion_count = 0
        add_read = 0
        add_edit = 0
        non_staff = 0

        plans = []

        print()
        print("=== USER TARGET ===")

        for user_id in sorted(
            by_user,
            key=lambda uid: (
                by_user[uid]["user"].username
            ),
        ):
            row = by_user[user_id]
            user = row["user"]
            roles = row["roles"]
            units = sorted(row["units"])

            is_officer = role_officer in roles
            is_champion = role_champion in roles

            if is_officer:
                officer_count += 1

            if is_champion:
                champion_count += 1

            need_read = not user.groups.filter(
                pk=read_group.pk
            ).exists()

            # EDIT hanya untuk Risk Officer.
            need_edit = (
                is_officer
                and not user.groups.filter(
                    pk=edit_group.pk
                ).exists()
            )

            if need_read:
                add_read += 1

            if need_edit:
                add_edit += 1

            if not user.is_staff:
                non_staff += 1

            role_labels = []

            if is_officer:
                role_labels.append("RISK OFFICER")

            if is_champion:
                role_labels.append("RISK CHAMPION")

            changes = []

            if need_read:
                changes.append("+UNIT-READ")

            if need_edit:
                changes.append("+ACCESS-EDIT")

            if not changes:
                changes.append("SUDAH SESUAI")

            print(
                f"{user.username:30}"
                f" | {' + '.join(role_labels):27}"
                f" | unit={', '.join(units)}"
                f" | staff={user.is_staff}"
                f" | {' '.join(changes)}"
            )

            plans.append(
                (
                    user,
                    need_read,
                    need_edit,
                )
            )

        print()
        print("=" * 110)
        print("SUMMARY")
        print("=" * 110)
        print("Unique user target :", total)
        print("Risk Officer       :", officer_count)
        print("Risk Champion      :", champion_count)
        print("Tambah UNIT READ   :", add_read)
        print("Tambah ACCESS EDIT :", add_edit)
        print("Non-staff          :", non_staff)

        if not apply:
            print()
            print(
                "DRY-RUN SELESAI — database TIDAK diubah."
            )
            return

        with transaction.atomic():
            for user, need_read, need_edit in plans:
                if need_read:
                    user.groups.add(read_group)

                if need_edit:
                    user.groups.add(edit_group)

        # Post-check keras.
        errors = []

        for user_id, row in by_user.items():
            user = row["user"]
            roles = row["roles"]

            if not user.groups.filter(
                pk=read_group.pk
            ).exists():
                errors.append(
                    f"{user.username}: UNIT READ belum ada"
                )

            if (
                role_officer in roles
                and not user.groups.filter(
                    pk=edit_group.pk
                ).exists()
            ):
                errors.append(
                    f"{user.username}: ACCESS EDIT belum ada"
                )

        if errors:
            raise CommandError(
                "Post-check gagal:\n- "
                + "\n- ".join(errors)
            )

        print()
        print(
            "APPLY BERHASIL — seluruh Risk Officer "
            "dan Risk Champion aktif sudah disesuaikan."
        )
