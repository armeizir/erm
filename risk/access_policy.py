from django.db.models import Q

"""
Kebijakan hak akses sederhana ERM PLN Batam.

Prinsip:
1. Group BID/UB = scope organisasi/data.
2. ROLE - ACCESS - READ/EDIT/ADMIN = aksi yang boleh dilakukan.
3. Risk Champion/Risk Officer/Pairing Officer = workflow, bukan permission.
"""

ROLE_READ = "ROLE - ACCESS - READ"
ROLE_EDIT = "ROLE - ACCESS - EDIT"
ROLE_ADMIN = "ROLE - ACCESS - ADMIN"

SIMPLE_ACCESS_ROLES = {
    "READ": ROLE_READ,
    "EDIT": ROLE_EDIT,
    "ADMIN": ROLE_ADMIN,
}

ORG_GROUP_PREFIXES = (
    "BID ",
    "UB ",
)

ORG_GROUP_EXACT_NAMES = (
    "KSPI",
    "SETPER",
)


def organizational_groups_for_user(user):
    """
    Group BID/UB adalah sumber authoritative untuk scope data user.

    PenugasanUnitBisnis tidak dipakai untuk menentukan scope baca data.
    Penugasan tetap digunakan untuk workflow Risk Champion/Risk Officer.
    """
    if not getattr(user, "is_authenticated", False):
        from django.contrib.auth.models import Group
        return Group.objects.none()

    if getattr(user, "is_superuser", False):
        from django.contrib.auth.models import Group
        return Group.objects.all()

    query = Q()

    for prefix in ORG_GROUP_PREFIXES:
        query |= Q(name__startswith=prefix)

    query |= Q(name__in=ORG_GROUP_EXACT_NAMES)
    query |= Q(organization_unit_mappings__aktif=True)

    return user.groups.filter(query).distinct()


def user_has_organizational_scope(user):
    """
    True hanya untuk user non-superuser yang menjadi anggota BID/UB.

    Superuser sengaja False agar tidak terkena pembatasan menu BID/UB.
    """
    if not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "is_superuser", False):
        return False

    return organizational_groups_for_user(user).exists()


def is_organizational_group_name(name):
    name = str(name or "").strip().upper()
    return name in ORG_GROUP_EXACT_NAMES or any(
        name.startswith(prefix) for prefix in ORG_GROUP_PREFIXES
    )


# Hanya model yang termasuk dalam 5 kelompok menu:
#
# 1. Kontrak Manajemen
# 2. RKM
# 3. Profil Risiko Bidang/Unit Bisnis
# 4. Laporan Risiko Bulanan
# 5. KPMR
ACCESS_MODELS = {
    # ---------------------------------------------------------
    # 1. KONTRAK MANAJEMEN
    # ---------------------------------------------------------
    ("km", "kontrakmanajemen"),
    ("km", "kontrakmanajemenbagian"),
    ("km", "kontrakmanajemenitem"),
    ("km", "kontrakmanajementargetperiode"),

    # ---------------------------------------------------------
    # 2. RKM
    # ---------------------------------------------------------
    ("risk", "rkmsummary"),
    ("risk", "rkmitem"),

    # ---------------------------------------------------------
    # 3. PROFIL RISIKO BIDANG / UNIT BISNIS
    # ---------------------------------------------------------
    ("risk", "reassessmentsummary"),
    ("risk", "reassessmentitem"),

    # Model detail yang dipakai proses Re-Assessment.
    ("reassessment", "existingcontrol"),
    ("reassessment", "reassessment"),
    ("reassessment", "reassessmentworkflowlog"),
    ("reassessment", "riskassessment"),
    ("reassessment", "riskcause"),
    ("reassessment", "riskevent"),
    ("reassessment", "riskindicator"),
    ("reassessment", "treatmentplan"),
    ("reassessment", "treatmentprogress"),
    ("reassessment", "treatmenttimeline"),

    # ---------------------------------------------------------
    # 4. LAPORAN RISIKO BULANAN
    # ---------------------------------------------------------
    ("monthly_report", "monthlyriskreport"),
    ("monthly_report", "monthlyriskreportitem"),
    ("monthly_report", "monthlyriskreportkmalignment"),
    ("monthly_report", "monthlyriskreportchange"),
    ("monthly_report", "monthlyriskreportlossevent"),
    ("monthly_report", "monthlyriskreportsubmissionlog"),

    # ---------------------------------------------------------
    # 5. KPMR
    # ---------------------------------------------------------
    ("risk", "kpmrsummary"),
    ("risk", "kpmrperiode"),
    ("risk", "kpmritem"),
    ("risk", "kpmrindikatorresmi"),
    ("risk", "kpmrsubindikatorresmi"),

    ("kpmr", "kpmranswer"),
    ("kpmr", "kpmrreview"),
    ("kpmr", "kpmrriskreview"),
    ("kpmr", "kpmrsupportingdocument"),

    # Parameter KPMR hanya perlu dibaca oleh user unit.
    ("masterdata", "kpmrparameter"),
    ("masterdata", "kpmrparameteropsi"),
}


# Model yang TIDAK boleh diedit/delete walaupun ROLE ADMIN.
# Contoh:
# - log submit/approval harus menjadi audit trail.
# - master parameter KPMR bukan kewenangan user Bidang/Unit.
READ_ONLY_MODELS = {
    ("monthly_report", "monthlyriskreportsubmissionlog"),
    ("masterdata", "kpmrparameter"),
    ("masterdata", "kpmrparameteropsi"),
}


def allowed_actions_for_model(level, app_label, model):
    """
    Return action Django yang diperbolehkan:
    view/add/change/delete.
    """
    level = str(level or "").strip().upper()
    key = (app_label, model)

    if key not in ACCESS_MODELS:
        return set()

    if key in READ_ONLY_MODELS:
        return {"view"}

    if level == "READ":
        return {"view"}

    if level == "EDIT":
        return {"view", "add", "change"}

    if level == "ADMIN":
        return {"view", "add", "change", "delete"}

    raise ValueError(f"Level akses tidak dikenal: {level!r}")


def permission_specs_for_level(level):
    """
    Menghasilkan:
        {("app_label", "codename"), ...}
    """
    specs = set()

    for app_label, model in ACCESS_MODELS:
        actions = allowed_actions_for_model(
            level,
            app_label,
            model,
        )

        for action in actions:
            specs.add(
                (
                    app_label,
                    f"{action}_{model}",
                )
            )

    return specs
