from django.db.models import Q

from risk.access_policy import organizational_groups_for_user
from risk.models import (
    KPMRItem,
    PenugasanUnitBisnis,
    ProfilRisikoKorporatItem,
    ReAssessmentItem,
    ReAssessmentSummary,
)


RISK_ADMIN_GROUPS = {"Risk Admin", "Risk Administrator", "Admin Risiko"}


def _is_authenticated(user) -> bool:
    return bool(user and user.is_authenticated and user.is_active)


def _in_groups(user, names) -> bool:
    if not _is_authenticated(user):
        return False
    return user.groups.filter(name__in=names).exists()


def is_risk_admin(user) -> bool:
    if not _is_authenticated(user):
        return False
    return user.is_superuser or _in_groups(user, RISK_ADMIN_GROUPS)


def is_risk_officer(user) -> bool:
    if not _is_authenticated(user):
        return False
    if user.is_superuser:
        return True
    return _has_assignment_role(user, PenugasanUnitBisnis.ROLE_RISK_OFFICER)


def _has_assignment_role(user, role) -> bool:
    if not _is_authenticated(user):
        return False
    return PenugasanUnitBisnis.objects.filter(
        user=user,
        peran=role,
        aktif=True,
    ).exists()


def is_pairing_officer(user) -> bool:
    return _has_assignment_role(user, PenugasanUnitBisnis.ROLE_PAIRING_OFFICER)


def is_risk_champion(user) -> bool:
    return _has_assignment_role(user, PenugasanUnitBisnis.ROLE_RISK_CHAMPION)


def get_assigned_business_units(user):
    return organizational_groups_for_user(user)


def _has_global_risk_scope(user) -> bool:
    return is_risk_admin(user)


def can_view_business_unit(user, unit) -> bool:
    if not _is_authenticated(user) or unit is None:
        return False
    if user.is_superuser or _has_global_risk_scope(user):
        return True
    return get_assigned_business_units(user).filter(pk=unit.pk).exists()


def can_edit_business_unit(user, unit) -> bool:
    if not _is_authenticated(user) or unit is None:
        return False
    if user.is_superuser or is_risk_admin(user):
        return True
    return organizational_groups_for_user(user).filter(pk=unit.pk).exists()


def can_view_risk_profile(user, profile) -> bool:
    if not _is_authenticated(user) or profile is None:
        return False
    if not user.has_perm("risk.view_reassessmentsummary"):
        return False
    return can_view_business_unit(user, profile.unit_bisnis)


def can_edit_risk_profile(user, profile) -> bool:
    if not _is_authenticated(user) or profile is None:
        return False
    if not user.has_perm("risk.change_reassessmentsummary"):
        return False
    return can_edit_business_unit(user, profile.unit_bisnis)


def can_view_kpmr_summary(user, summary) -> bool:
    if not _is_authenticated(user) or summary is None:
        return False
    if not user.has_perm("risk.view_kpmrsummary"):
        return False
    return can_view_business_unit(user, summary.unit_bisnis)


def can_edit_kpmr_summary(user, summary) -> bool:
    if not _is_authenticated(user) or summary is None:
        return False
    if not user.has_perm("risk.change_kpmrsummary"):
        return False
    return can_edit_business_unit(user, summary.unit_bisnis)


def can_export_rcc(user) -> bool:
    if not _is_authenticated(user):
        return False
    return user.is_superuser or user.has_perm("risk.view_profilrisikokorporatitem")


def _unit_scope_filter(user, field_name="unit_bisnis"):
    if not _is_authenticated(user):
        return Q(pk__isnull=True)
    if user.is_superuser or _has_global_risk_scope(user):
        return Q()
    return Q(**{f"{field_name}__in": get_assigned_business_units(user)})


def get_accessible_kpmr_items(user):
    queryset = KPMRItem.objects.select_related(
        "summary",
        "summary__unit_bisnis",
        "reassessment_item",
        "reassessment_item__km_item",
    )
    if not _is_authenticated(user) or not (
        user.has_perm("risk.view_kpmritem") or user.has_perm("risk.change_kpmritem")
    ):
        return queryset.none()
    return queryset.filter(_unit_scope_filter(user, "summary__unit_bisnis"))


def get_accessible_risk_profiles(user):
    queryset = ReAssessmentSummary.objects.select_related("unit_bisnis", "kontrak_manajemen")
    if not _is_authenticated(user) or not user.has_perm("risk.view_reassessmentsummary"):
        return queryset.none()
    return queryset.filter(_unit_scope_filter(user, "unit_bisnis"))


def get_accessible_reassessment_items(user):
    queryset = ReAssessmentItem.objects.select_related(
        "summary",
        "summary__unit_bisnis",
        "unit_bisnis",
        "km_item",
    )
    if not _is_authenticated(user) or not user.has_perm("risk.view_reassessmentitem"):
        return queryset.none()
    return queryset.filter(_unit_scope_filter(user, "unit_bisnis"))


def get_accessible_corporate_risk_items(user):
    queryset = ProfilRisikoKorporatItem.objects.select_related("summary")
    if not _is_authenticated(user) or not user.has_perm("risk.view_profilrisikokorporatitem"):
        return queryset.none()
    return queryset
