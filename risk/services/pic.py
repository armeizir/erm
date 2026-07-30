import re
import unicodedata
from datetime import date

from django.db.models import Q
from django.utils import timezone

from masterdata.models import (
    OrganizationUnit,
    OrganizationUnitAccessGroup,
    OrganizationUnitUserAssignment,
)
from risk.access_policy import organizational_groups_for_user


def normalize_pic_text(value):
    value = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    value = re.sub(r"[./_–—-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def profile_reference_date(summary):
    today = timezone.localdate()
    if not summary or not getattr(summary, "tahun", None):
        return today
    if summary.tahun < today.year:
        return date(summary.tahun, 12, 31)
    if summary.tahun > today.year:
        return date(summary.tahun, 1, 1)
    return today


def owner_organization_unit(summary, include_inactive=False):
    if not summary or not summary.unit_bisnis_id:
        return None
    queryset = OrganizationUnit.objects.filter(
        access_group_mappings__group_id=summary.unit_bisnis_id,
        access_group_mappings__aktif=True,
    )
    if not include_inactive:
        queryset = queryset.filter(aktif=True)
    return queryset.order_by(
        "-access_group_mappings__utama",
        "code",
        "pk",
    ).first()


def permitted_organization_units(user, include_inactive_ids=()):
    if getattr(user, "is_superuser", False):
        query = Q(aktif=True)
    else:
        groups = organizational_groups_for_user(user)
        query = Q(
            aktif=True,
            access_group_mappings__aktif=True,
            access_group_mappings__group__in=groups,
        )
    if include_inactive_ids:
        query |= Q(pk__in=include_inactive_ids)
    return OrganizationUnit.objects.filter(query).distinct().order_by("name", "code")


def effective_assignments(
    organization_unit,
    on_date=None,
    *,
    permitted_organizations=None,
    include_assignment_ids=(),
):
    on_date = on_date or timezone.localdate()
    query = Q(
        organization_unit=organization_unit,
        aktif=True,
        user__is_active=True,
        tanggal_mulai__lte=on_date,
    ) & (Q(tanggal_selesai__isnull=True) | Q(tanggal_selesai__gte=on_date))
    if include_assignment_ids:
        query |= Q(pk__in=include_assignment_ids)
    queryset = OrganizationUnitUserAssignment.objects.filter(query)
    if permitted_organizations is not None:
        queryset = queryset.filter(
            organization_unit__in=permitted_organizations
        )
    return queryset.select_related("user", "organization_unit").order_by(
        "-is_unit_head",
        "-utama",
        "user__first_name",
        "user__last_name",
        "user__username",
        "pk",
    )


def assignment_label(assignment, on_date=None):
    user = assignment.user
    name = user.get_full_name().strip() or user.username
    nip = getattr(user, "nip", None) or user.username
    on_date = on_date or timezone.localdate()
    position = (
        user.riwayat_jabatan.filter(tanggal_mulai__lte=on_date)
        .filter(Q(tanggal_selesai__isnull=True) | Q(tanggal_selesai__gte=on_date))
        .order_by("-tanggal_mulai", "-pk")
        .values_list("jabatan", flat=True)
        .first()
    )
    return " — ".join(part for part in (name, nip, position) if part)


def match_organization(value, *, active_only=False):
    raw = str(value or "").strip()
    normalized = normalize_pic_text(raw)
    if not normalized:
        return "blank", []

    queryset = OrganizationUnit.objects.all()
    if active_only:
        queryset = queryset.filter(aktif=True)
    organizations = list(queryset.order_by("code", "pk"))

    exact = [
        organization
        for organization in organizations
        if raw.casefold() in {
            organization.code.strip().casefold(),
            organization.name.strip().casefold(),
        }
    ]
    if exact:
        return ("exact" if len(exact) == 1 else "ambiguous"), exact

    normalized_matches = [
        organization
        for organization in organizations
        if normalized
        in {
            normalize_pic_text(organization.code),
            normalize_pic_text(organization.name),
        }
    ]
    if normalized_matches:
        return (
            "normalized" if len(normalized_matches) == 1 else "ambiguous"
        ), normalized_matches
    return "unmatched", []


def resolve_import_pic(
    *,
    organization_id=None,
    organization_code=None,
    organization_name=None,
    assignment_id=None,
    user_nip=None,
    user_email=None,
):
    organization = None
    if organization_id:
        organization = OrganizationUnit.objects.filter(
            pk=organization_id,
            aktif=True,
        ).first()
    elif organization_code:
        organization = OrganizationUnit.objects.filter(
            code__iexact=str(organization_code).strip(),
            aktif=True,
        ).first()
    elif organization_name:
        status, matches = match_organization(
            organization_name,
            active_only=True,
        )
        if status in {"exact", "normalized"}:
            organization = matches[0]
    if not organization:
        return None, None

    assignments = effective_assignments(organization)
    assignment = None
    if assignment_id:
        assignment = assignments.filter(pk=assignment_id).first()
    elif user_nip:
        assignment = assignments.filter(user__username__iexact=user_nip).first()
    elif user_email:
        assignment = assignments.filter(user__email__iexact=user_email).first()
    return organization, assignment
