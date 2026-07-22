import re
import unicodedata

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.utils import get_random_secret_key
from django.db import transaction

from risk.models import PenugasanUnitBisnis, ReAssessmentItem, ReAssessmentSummary


USERNAME_ALIASES = {
    "ARMEIZIR NURGUMALA": "armeizir",
    "DENY ROSITA": "deny",
    "MUKHLIS SUPRIYADI": "mukhlis",
    "RAFIKA": "rafika",
}


USER_IDENTITY_OVERRIDES = {
    (
        "BID BIS",
        "Risk Champion",
        "MAN PENGEMBANGAN BISNIS DAN ENTERPRISE",
        "ADE JUSTICIA PUTRA",
    ): {
        "username": "ade.iusticia",
        "email": "ade.iusticia@plnbatam.com",
    },
    (
        "BID STRADA",
        "Risk Officer",
        "SOF PELAKSANA PENGADAAN",
        "SUPRIANTO",
    ): {
        "username": "suprianto",
        "email": "suprianto_dist@plnbatam.com",
    },
    (
        "BID BIS",
        "Risk Officer",
        "SOF MODEL BISNIS DAN DESAIN BISNIS BARU",
        "SUPRIANTO",
    ): {
        "username": "Suprianto_kit",
        "email": "suprianto_kit@plnbatam.com",
    },
}


PAIRING_BY_UNIT = {
    "KSPI": "ARMEIZIR NURGUMALA",
    "SETPER": "ARMEIZIR NURGUMALA",
    "BID RENKIN": "MUKHLIS SUPRIYADI",
    "BID KEU": "DENY ROSITA",
    "BID HCGA": "DENY ROSITA",
    "BID MANPRO": "DENY ROSITA",
    "BID OPS": "DENY ROSITA",
    "BID STRADA": "DENY ROSITA",
    "BID BIS": "ARMEIZIR NURGUMALA",
    "BID AGA": "ARMEIZIR NURGUMALA",
    "UB INFRA": "ARMEIZIR NURGUMALA",
    "UB KITRAN": "MUKHLIS SUPRIYADI",
    "UB DISYAN": "MUKHLIS SUPRIYADI",
    "UB BES": "MUKHLIS SUPRIYADI",
}


PEOPLE = [
    ("KSPI", "Risk Champion", "MAN AUDIT", "WARDONO"),
    ("KSPI", "Risk Officer", "ASMAN AUDIT GRUP 2", "INDAH AMALIA"),
    ("KSPI", "Risk Officer", "OF OPERASI DAN MANAJEMEN AUDIT GRUP 1", "ANNISA NUR HIDAYAH"),
    ("SETPER", "Risk Champion", "MAN KOMUNIKASI DAN HUBUNGAN MASYARAKAT", "YOGA PERDANA SULASTAMA"),
    ("SETPER", "Risk Officer", "ASMAN KESEKRETARIATAN DAN DOCUMENT CONTROL", "DINA SAFRINA"),
    ("SETPER", "Risk Officer", "SOF PERUSAHAAN DAN REG PEMERINTAH", "SRI MURNIYANTI"),
    ("BID RENKIN", "Risk Champion", "MAN PERENCANAAN", "DONI KURNIAWAN"),
    ("BID RENKIN", "Risk Officer", "ASMAN PERENCANAAN SISTEM", "MARLEN SIAGIAN"),
    ("BID RENKIN", "Risk Officer", "STC REN SIS TRANS DAN DIST", "LENI SULASTRI"),
    ("BID KEU", "Risk Champion", "MAN ANGGARAN DAN PENDANAAN", "PRISKA BAYU ANUGRAH"),
    ("BID KEU", "Risk Officer", "JOF PENGELOLAAN PAJAK", "FATIMAH KASIM"),
    ("BID KEU", "Risk Officer", "JOF PENGOLAHAN AKUNTANSI AT DAN PDP", "KARIANI"),
    ("BID HCGA", "Risk Champion", "MAN PELAYANAN HUMAN CAPITAL", "WIJAYATI"),
    ("BID HCGA", "Risk Officer", "JOF KNOWLEDGE MANAGEMENT", "IRFAN FIKRI EFENDI"),
    ("BID HCGA", "Risk Officer", "OF ADMINISTRASI DAN GENERAL AFFAIR", "AGRECIA ROMEL"),
    ("BID MANPRO", "Risk Champion", "ASMAN MANAJEMEN PROYEK PEMBANGKIT", "GHUFRAN FAUZAN"),
    ("BID MANPRO", "Risk Officer", "STC PENGENDALIAN KONSTRUKSI TRANSMISI", "DEDY KURNIAWAN WIBOWO"),
    ("BID MANPRO", "Risk Officer", "TC PENGENDALIAN KONSTRUKSI PEMBANGKIT", "MUHAMMAD IZZATUL HAMDI"),
    ("BID OPS", "Risk Champion", "SP DAL KIT DAN TRANS", "M. ERIK ERDIANA"),
    ("BID OPS", "Risk Officer", "TC PENGENDALIAN KINERJA OPERASI", "WINDY LUSIA SAMOSIR"),
    ("BID OPS", "Risk Officer", "OF MON, EVALUASI DAN ASURANSI ASET", "ARIVIN ZEBUA"),
    ("BID STRADA", "Risk Champion", "MAN PELAKSANA PENGADAAN", "DIAN HANDAYANI"),
    ("BID STRADA", "Risk Officer", "SOF PELAKSANA PENGADAAN", "SUPRIANTO"),
    ("BID STRADA", "Risk Officer", "OF PERENCANA PENGADAAN", "DHANNY IRAWAN"),
    ("BID BIS", "Risk Champion", "MAN PENGEMBANGAN BISNIS DAN ENTERPRISE", "ADE JUSTICIA PUTRA"),
    ("BID BIS", "Risk Officer", "OF PENGEMBANGAN PRODUK", "ATHALLA KHADI MUSYAFFA"),
    ("BID BIS", "Risk Officer", "SOF MODEL BISNIS DAN DESAIN BISNIS BARU", "SUPRIANTO"),
    ("BID AGA", "Risk Champion", "MAN REVENUE ASSURANCE", "NITA RIANY SITIO"),
    ("BID AGA", "Risk Officer", "ASMAN QUALITY ASSURANCE", "AHMAD KHUDHOIBI"),
    ("BID AGA", "Risk Officer", "SP NIAGA DAN YAN GAN", "NORA GUSTI"),
    ("UB INFRA", "Risk Champion", "MAN ADM DAN PELAYANAN MULTIMEDIA", "TETTY SITUMORANG"),
    ("UB INFRA", "Risk Officer", "ASMAN OPERASI DAN PEMELIHARAAN DATA CENTER", "WIELY YAZID PRADANA"),
    ("UB INFRA", "Risk Officer", "OF MARKETING MUL DAN PARTNERSHIP MANAGEMENT", "RINA YULIANA"),
    ("UB INFRA", "Risk Officer", "OF PERENCANAAN DAN PENGEMBANGAN APLIKASI", "MUHAMMAD AKMAL JOEDHIAWAN"),
    ("UB KITRAN", "Risk Champion", "MUP PEMBANGKIT PLTGU TANJUNG UNCANG", "ARIF BUDIMAN"),
    ("UB KITRAN", "Risk Officer", "ASMAN OPERASI SISTEM", "MUHAMMAD ARIEF AULIA HENDRAWAN"),
    ("UB KITRAN", "Risk Officer", "TC PENGELOLAAN ENERGI PRIMER", "BENI FERNANDA"),
    ("UB DISYAN", "Risk Champion", "MUP3 TIBAN", "HERU SUSANTO"),
    ("UB DISYAN", "Risk Officer", "ASMAN PEMELIHARAAN PREVENTIF", "DASMER HUTAGAOL"),
    ("UB DISYAN", "Risk Officer", "TL ADMINISTRASI", "RAKHMAD FAUZAN"),
    ("UB BES", "Risk Champion", "MAN ADMINISTRASI DAN BUSINESS RELATION", "LINDRI ULFA KHARISMAWATI"),
    ("UB BES", "Risk Officer", "TC MANAJEMEN OPERASI PEMBANGKIT", "MUHAMMAD REZA PERMANA"),
    ("UB BES", "Risk Officer", "OF BUSINESS RELATION", "WULAN PURNAMA DEWI"),
    ("UB BES", "Risk Officer", "OF KINERJA DAN ADMINISTRASI", "EVIYAN FAJAR ANGGARA"),
]


ROLE_MAP = {
    "Risk Champion": PenugasanUnitBisnis.ROLE_RISK_CHAMPION,
    "Risk Officer": PenugasanUnitBisnis.ROLE_RISK_OFFICER,
}


def normalize_name(value):
    return re.sub(r"\s+", " ", str(value or "").strip()).upper()


def username_from_name(name):
    ascii_name = (
        unicodedata.normalize("NFKD", name)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    username = re.sub(r"[^a-z0-9]+", ".", ascii_name.lower()).strip(".")
    return username[:150]


def split_name(name):
    parts = normalize_name(name).split()
    if len(parts) == 1:
        return parts[0].title(), ""
    return parts[0].title(), " ".join(parts[1:]).title()


def permissions_for_profile_access():
    permissions = []
    for model in (ReAssessmentSummary, ReAssessmentItem):
        content_type = ContentType.objects.get_for_model(model)
        permissions.extend(
            Permission.objects.filter(
                content_type=content_type,
                codename=f"view_{model._meta.model_name}",
            )
        )
    return permissions


def permissions_for_profile_change():
    permissions = []
    for model in (ReAssessmentSummary, ReAssessmentItem):
        content_type = ContentType.objects.get_for_model(model)
        permissions.extend(
            Permission.objects.filter(
                content_type=content_type,
                codename=f"change_{model._meta.model_name}",
            )
        )
    return permissions


def _apply_seed_password(user, *, created, use_ldap, temporary_password=None, force_reset=False):
    if use_ldap:
        if created or force_reset or user.has_usable_password():
            user.set_unusable_password()
        return

    if not (created or force_reset):
        return

    password = temporary_password or get_random_secret_key()
    user.set_password(password)


def _get_single_user(queryset, *, identity_label):
    count = queryset.count()

    if count > 1:
        raise RuntimeError(
            f"Identitas ambigu untuk {identity_label}: "
            f"ditemukan {count} user."
        )

    return queryset.first()


def get_or_create_user(
    name,
    role_label=None,
    jabatan=None,
    *,
    unit_name=None,
    use_ldap=True,
    temporary_password=None,
    force_reset=False,
):
    User = get_user_model()

    normalized = normalize_name(name)

    identity_key = (
        unit_name,
        role_label,
        jabatan,
        normalized,
    )

    identity = USER_IDENTITY_OVERRIDES.get(identity_key)

    user = None
    created = False

    # --------------------------------------------------------------
    # PRIORITAS 1:
    # Identitas eksplisit/authoritative berdasarkan unit + role +
    # jabatan + nama.
    #
    # Cocokkan EMAIL terlebih dahulu, lalu USERNAME.
    # Jangan pernah memilih user secara sembarang jika konflik.
    # --------------------------------------------------------------
    if identity:
        explicit_username = str(
            identity.get("username") or ""
        ).strip()

        explicit_email = str(
            identity.get("email") or ""
        ).strip().lower()

        if not explicit_username or not explicit_email:
            raise RuntimeError(
                f"Identity override tidak lengkap untuk "
                f"{unit_name} / {role_label} / {name}."
            )

        email_user = _get_single_user(
            User.objects.filter(
                email__iexact=explicit_email
            ).order_by("id"),
            identity_label=f"email {explicit_email}",
        )

        username_user = _get_single_user(
            User.objects.filter(
                username__iexact=explicit_username
            ).order_by("id"),
            identity_label=f"username {explicit_username}",
        )

        if (
            email_user is not None
            and username_user is not None
            and email_user.pk != username_user.pk
        ):
            raise RuntimeError(
                f"Konflik identitas untuk {name}: "
                f"email {explicit_email!r} dimiliki user "
                f"ID {email_user.pk}, sedangkan username "
                f"{explicit_username!r} dimiliki user "
                f"ID {username_user.pk}."
            )

        user = email_user or username_user

        if user is None:
            first_name, last_name = split_name(name)

            user = User.objects.create_user(
                username=explicit_username,
                first_name=first_name,
                last_name=last_name,
                email=explicit_email,
                is_staff=True,
            )

            created = True

        else:
            existing_email = (
                user.email or ""
            ).strip().lower()

            if (
                existing_email
                and existing_email != explicit_email
            ):
                raise RuntimeError(
                    f"Konflik email untuk user ID {user.pk} "
                    f"({user.username!r}): "
                    f"existing={existing_email!r}, "
                    f"expected={explicit_email!r}."
                )

            # Isi/normalisasi email authoritative.
            user.email = explicit_email

    # --------------------------------------------------------------
    # PRIORITAS 2:
    # Alias eksplisit, kemudian exact normalized full-name.
    #
    # Full-name hanya boleh dipakai jika tepat SATU user.
    # --------------------------------------------------------------
    else:
        alias_username = USERNAME_ALIASES.get(
            normalized
        )

        if alias_username:
            user = _get_single_user(
                User.objects.filter(
                    username__iexact=alias_username
                ).order_by("id"),
                identity_label=f"alias username {alias_username}",
            )

        if user is None:
            name_matches = [
                candidate
                for candidate in User.objects.all().order_by("id")
                if normalize_name(
                    candidate.get_full_name()
                ) == normalized
            ]

            if len(name_matches) > 1:
                raise RuntimeError(
                    f"Nama {name!r} ambigu: ditemukan "
                    f"{len(name_matches)} user. "
                    f"Tambahkan USER_IDENTITY_OVERRIDES "
                    f"berdasarkan unit/role/jabatan."
                )

            if len(name_matches) == 1:
                user = name_matches[0]

        # ----------------------------------------------------------
        # Untuk LDAP:
        # Jangan membuat user baru tanpa email authoritative.
        #
        # Ini menutup akar masalah akun seed email kosong yang
        # kemudian diduplikasi saat user pertama kali login LDAP.
        # ----------------------------------------------------------
        if user is None and use_ldap:
            raise RuntimeError(
                f"Menolak membuat LDAP seed user {name!r} "
                f"tanpa identitas authoritative. "
                f"Tambahkan USER_IDENTITY_OVERRIDES dengan "
                f"username dan email resmi."
            )

        # Legacy/non-LDAP seed masih boleh membuat local user.
        if user is None:
            username = username_from_name(name)
            original = username
            counter = 2

            while User.objects.filter(
                username__iexact=username
            ).exists():
                username = f"{original}.{counter}"
                counter += 1

            first_name, last_name = split_name(name)

            user = User.objects.create_user(
                username=username,
                first_name=first_name,
                last_name=last_name,
                email="",
                is_staff=True,
            )

            created = True

    # --------------------------------------------------------------
    # COMMON USER UPDATE
    # --------------------------------------------------------------
    if not user.first_name:
        user.first_name, user.last_name = split_name(
            name
        )

    user.is_staff = True
    user.is_superuser = False

    _apply_seed_password(
        user,
        created=created,
        use_ldap=use_ldap,
        temporary_password=temporary_password,
        force_reset=force_reset,
    )

    user.save()

    user.user_permissions.set(
        permissions_for_profile_access()
    )

    if role_label or jabatan:
        profile = " / ".join(
            part
            for part in [role_label, jabatan]
            if part
        )

        user.riwayat_jabatan.get_or_create(
            jabatan=profile,
            tanggal_mulai="2026-01-01",
        )

    return user, created


def deactivate_obsolete_mukhlis_user():
    User = get_user_model()
    obsolete_user = User.objects.filter(username="mukhlis.supriadi").first()
    target_user = User.objects.filter(username="mukhlis").first()
    if not obsolete_user or not target_user:
        return

    for assignment in PenugasanUnitBisnis.objects.filter(
        user=obsolete_user,
        unit_bisnis__name__in=["UB KITRAN", "UB DISYAN", "UB BES"],
        peran=PenugasanUnitBisnis.ROLE_PAIRING_OFFICER,
        aktif=True,
    ):
        if PenugasanUnitBisnis.objects.filter(
            user=target_user,
            unit_bisnis=assignment.unit_bisnis,
            peran=assignment.peran,
            aktif=True,
        ).exists():
            assignment.aktif = False
            assignment.save(update_fields=["aktif"])

    obsolete_user.is_active = False
    obsolete_user.is_staff = False
    obsolete_user.is_superuser = False
    obsolete_user.set_unusable_password()
    obsolete_user.save()


def upsert_assignment(user, unit_name, role):
    unit = Group.objects.get(name=unit_name)
    if role == PenugasanUnitBisnis.ROLE_PAIRING_OFFICER:
        PenugasanUnitBisnis.objects.filter(
            unit_bisnis=unit,
            peran=role,
            aktif=True,
        ).exclude(user=user).update(aktif=False)
    assignment, created = PenugasanUnitBisnis.objects.get_or_create(
        user=user,
        unit_bisnis=unit,
        peran=role,
        defaults={"aktif": True},
    )
    if not assignment.aktif:
        assignment.aktif = True
        assignment.save(update_fields=["aktif"])
    return assignment, created


def run(*, use_ldap=True, temporary_password=None, force_reset=False, stdout=None):
    created_users = 0
    created_assignments = 0
    with transaction.atomic():
        for unit_name, pairing_name in PAIRING_BY_UNIT.items():
            user, created = get_or_create_user(
                pairing_name,
                "Pairing Officer",
                None,
                unit_name=unit_name,
                use_ldap=use_ldap,
                temporary_password=temporary_password,
                force_reset=force_reset,
            )
            created_users += int(created)
            _, assignment_created = upsert_assignment(
                user,
                unit_name,
                PenugasanUnitBisnis.ROLE_PAIRING_OFFICER,
            )
            created_assignments += int(assignment_created)

        for unit_name, role_label, jabatan, name in PEOPLE:
            user, created = get_or_create_user(
                name,
                role_label,
                jabatan,
                unit_name=unit_name,
                use_ldap=use_ldap,
                temporary_password=temporary_password,
                force_reset=force_reset,
            )
            created_users += int(created)
            _, assignment_created = upsert_assignment(user, unit_name, ROLE_MAP[role_label])
            created_assignments += int(assignment_created)

        deactivate_obsolete_mukhlis_user()

    output = stdout.write if stdout is not None else print
    output(f"Created users: {created_users}")
    output(f"Created assignments: {created_assignments}")
    output("Seed completed without printing passwords.")
    output("Summary by unit:")
    for unit in Group.objects.filter(name__in=PAIRING_BY_UNIT).order_by("name"):
        assignments = PenugasanUnitBisnis.objects.filter(unit_bisnis=unit, aktif=True)
        output(f"- {unit.name}: {assignments.count()} active assignments")


if __name__ == "__main__":
    run()
