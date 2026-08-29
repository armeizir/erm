from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


ROLE_NAME = "ROLE - UNIT - READ"


# ============================================================
# MODEL UTAMA YANG BOLEH DIBACA USER BIDANG / UNIT
# ============================================================

CORE_MODELS = (
    # KM canonical
    "risk.KontrakManajemen",
    "risk.BagianKontrakManajemen",
    "risk.ItemKontrakManajemen",

    # RKM
    "risk.RKMSummary",
    "risk.RKMItem",

    # Profil Risiko
    "risk.ReAssessmentSummary",
    "risk.ReAssessmentItem",

    # Laporan bulanan
    "monthly_report.MonthlyRiskReport",
    "monthly_report.MonthlyRiskReportItem",
    "monthly_report.MonthlyRiskReportChange",
    "monthly_report.MonthlyRiskReportKMAlignment",
    "monthly_report.MonthlyRiskReportLossEvent",
    "monthly_report.MonthlyRiskReportEvidence",
    "monthly_report.MonthlyRiskReportSubmissionLog",
    "monthly_report.MonthlyRiskReportImportBatch",
    "monthly_report.MonthlyRiskReportImportRow",
)


# ============================================================
# FIELD REFERENCE PROFIL RISIKO
#
# Permission VIEW model tujuan diperlukan agar dropdown /
# autocomplete Django Admin dapat dibaca.
# ============================================================

REASSESSMENT_REFERENCE_FIELDS = (
    "km_item",
    "sasaran_kbumn",
    "taksonomi_t3",
    "kategori_risiko",
    "jenis_existing_control",
    "penilaian_efektivitas_kontrol",
    "kategori_dampak",
    "skala_dampak_q1",
    "skala_dampak_q2",
    "skala_dampak_q3",
    "skala_dampak_q4",
    "skala_probabilitas",
    "skala_probabilitas_q1",
    "skala_probabilitas_q2",
    "skala_probabilitas_q3",
    "skala_probabilitas_q4",
    "opsi_perlakuan_risiko",
    "pos_anggaran",
    "jenis_program_dalam_rkap",
    "pic_organization_unit",
    "pic_user_assignment",
    "jenis_rencana_perlakuan_risiko",
)


# Master tambahan yang digunakan langsung oleh form/admin.
EXTRA_MODELS = (
    "risk.RiskMatrix",
    "risk.RiskMatrixCell",
    "risk.MasterKategoriDampak",
    "risk.MasterSkalaDampak",
    "risk.MasterSkalaProbabilitas",
)


SAFE_REFERENCE_APPS = {
    "risk",
    "masterdata",
    "monthly_report",
    "km",
    "reassessment",
}


def resolve_model(label):
    try:
        model = apps.get_model(label)
    except (LookupError, ValueError):
        model = None

    if model is None:
        raise CommandError(
            f"Model wajib tidak ditemukan: {label}"
        )

    return model


def view_permission_for_model(model):
    codename = f"view_{model._meta.model_name}"

    permission = (
        Permission.objects
        .select_related("content_type")
        .filter(
            content_type__app_label=model._meta.app_label,
            content_type__model=model._meta.model_name,
            codename=codename,
        )
        .first()
    )

    if permission is None:
        raise CommandError(
            "Permission tidak ditemukan: "
            f"{model._meta.app_label}.{codename}"
        )

    return permission


def reference_models():
    item_model = resolve_model("risk.ReAssessmentItem")

    result = set()

    for field_name in REASSESSMENT_REFERENCE_FIELDS:
        try:
            field = item_model._meta.get_field(field_name)
        except Exception as exc:
            raise CommandError(
                f"Field ReAssessmentItem tidak ditemukan: "
                f"{field_name}: {exc}"
            )

        remote = getattr(
            getattr(field, "remote_field", None),
            "model",
            None,
        )

        if remote is None:
            raise CommandError(
                f"Field {field_name} bukan relation."
            )

        # Jangan pernah memberi auth.User/auth.Group
        # melalui baseline role.
        if remote._meta.app_label not in SAFE_REFERENCE_APPS:
            continue

        result.add(remote)

    return result


def desired_permissions():
    models = set()

    for label in CORE_MODELS:
        models.add(resolve_model(label))

    for label in EXTRA_MODELS:
        models.add(resolve_model(label))

    models.update(reference_models())

    permissions = {
        view_permission_for_model(model)
        for model in models
    }

    return sorted(
        permissions,
        key=lambda p: (
            p.content_type.app_label,
            p.content_type.model,
            p.codename,
        ),
    )


class Command(BaseCommand):
    help = (
        "Sinkronisasi ROLE - UNIT - READ. "
        "Default DRY-RUN; gunakan --apply untuk menyimpan."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Simpan perubahan role.",
        )

        parser.add_argument(
            "--add-user",
            action="append",
            default=[],
            metavar="USERNAME",
            help=(
                "Tambahkan role kepada user tertentu. "
                "Dapat diulang."
            ),
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        usernames = options["add_user"]

        permissions = desired_permissions()

        existing = Group.objects.filter(
            name=ROLE_NAME
        ).first()

        current_ids = (
            set(
                existing.permissions.values_list(
                    "pk",
                    flat=True,
                )
            )
            if existing
            else set()
        )

        desired_ids = {p.pk for p in permissions}

        add_ids = desired_ids - current_ids
        remove_ids = current_ids - desired_ids

        self.stdout.write("=" * 90)
        self.stdout.write(
            "SYNC ROLE - UNIT - READ "
            f"| MODE={'APPLY' if apply else 'DRY-RUN'}"
        )
        self.stdout.write("=" * 90)

        self.stdout.write(
            f"\nGroup existing : "
            f"{'YA / ID=' + str(existing.pk) if existing else 'BELUM ADA'}"
        )

        self.stdout.write(
            f"Permission target: {len(permissions)}"
        )

        self.stdout.write(
            f"Would add       : {len(add_ids)}"
        )

        self.stdout.write(
            f"Would remove    : {len(remove_ids)}"
        )

        self.stdout.write(
            "\n=== PERMISSION TARGET ==="
        )

        for p in permissions:
            marker = (
                "+"
                if p.pk in add_ids
                else "="
            )

            self.stdout.write(
                f"{marker} "
                f"{p.content_type.app_label}."
                f"{p.codename}"
            )

        if remove_ids and existing:
            self.stdout.write(
                "\n=== PERMISSION YANG AKAN DIHAPUS "
                "DARI ROLE INI ==="
            )

            for p in existing.permissions.filter(
                pk__in=remove_ids
            ).select_related("content_type"):
                self.stdout.write(
                    "- "
                    f"{p.content_type.app_label}."
                    f"{p.codename}"
                )

        User = get_user_model()

        users = []

        for username in usernames:
            try:
                user = User.objects.get(
                    username=username
                )
            except User.DoesNotExist:
                raise CommandError(
                    f"User tidak ditemukan: {username}"
                )

            users.append(user)

        if users:
            self.stdout.write(
                "\n=== USER PILOT ==="
            )

            for user in users:
                current_groups = ", ".join(
                    user.groups.order_by("name")
                    .values_list("name", flat=True)
                )

                self.stdout.write(
                    f"{user.username}"
                    f" | current={current_groups or '-'}"
                )

        if not apply:
            self.stdout.write("")
            self.stdout.write(
                "DRY-RUN SELESAI — database "
                "TIDAK diubah."
            )
            return

        with transaction.atomic():
            group, created = Group.objects.get_or_create(
                name=ROLE_NAME
            )

            # Role ini dikelola secara deklaratif:
            # permission selalu persis sesuai baseline.
            group.permissions.set(permissions)

            for user in users:
                user.groups.add(group)

        group.refresh_from_db()

        actual_ids = set(
            group.permissions.values_list(
                "pk",
                flat=True,
            )
        )

        if actual_ids != desired_ids:
            raise CommandError(
                "Post-check permission ROLE - UNIT - READ "
                "tidak sesuai target."
            )

        for user in users:
            if not user.groups.filter(
                pk=group.pk
            ).exists():
                raise CommandError(
                    f"Post-check group user gagal: "
                    f"{user.username}"
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"APPLY BERHASIL — {ROLE_NAME}"
                f" | ID={group.pk}"
                f" | permissions="
                f"{group.permissions.count()}"
            )
        )

        if users:
            self.stdout.write(
                "User ditambahkan: "
                + ", ".join(
                    u.username for u in users
                )
            )
