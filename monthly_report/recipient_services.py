from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Q
from django.utils import timezone

from masterdata.models import OrganizationUnitUserAssignment
from risk.models import PenugasanUnitBisnis


@dataclass
class ApprovedReportRecipients:
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    to_users: list = field(default_factory=list)
    cc_users: list = field(default_factory=list)
    reason: str = ""
    excluded: list[str] = field(default_factory=list)


def _effective_assignments(on_date):
    return OrganizationUnitUserAssignment.objects.filter(
        aktif=True,
        user__is_active=True,
        tanggal_mulai__lte=on_date,
    ).filter(Q(tanggal_selesai__isnull=True) | Q(tanggal_selesai__gte=on_date))


def _valid_email(user):
    email = (user.email or "").strip()
    if not email:
        return None
    try:
        validate_email(email)
    except ValidationError:
        return None
    return email


def resolve_pairing_officers(report, on_date=None):
    if not report.reassessment_id or not report.reassessment.unit_bisnis_id:
        return []
    assignment = (
        PenugasanUnitBisnis.objects.filter(
            unit_bisnis=report.reassessment.unit_bisnis,
            peran=PenugasanUnitBisnis.ROLE_PAIRING_OFFICER,
            aktif=True,
            user__is_active=True,
        )
        .select_related("user")
        .order_by("user__first_name", "user__last_name", "user__username", "id")
        .first()
    )
    return [assignment.user] if assignment else []


def resolve_pairing_organization_unit(user, on_date=None):
    on_date = on_date or timezone.localdate()
    assignment = (
        _effective_assignments(on_date)
        .filter(user=user)
        .select_related("organization_unit", "organization_unit__parent")
        .order_by("-utama", "-tanggal_mulai", "organization_unit__code", "id")
        .first()
    )
    return assignment.organization_unit if assignment else None


def resolve_organization_head_chain(organization_unit, on_date=None):
    """Resolve one deterministic active head per level, nearest unit first."""
    on_date = on_date or timezone.localdate()
    result = []
    seen_organizations = set()
    organization = organization_unit
    while organization and organization.pk not in seen_organizations:
        seen_organizations.add(organization.pk)
        assignment = (
            _effective_assignments(on_date)
            .filter(organization_unit=organization, is_unit_head=True)
            .select_related("user")
            .order_by(
                "-utama",
                "-tanggal_mulai",
                "user__first_name",
                "user__last_name",
                "user__username",
                "id",
            )
            .first()
        )
        if assignment:
            result.append(assignment.user)
        organization = organization.parent
    return result


def build_approved_report_recipients(report, on_date=None):
    pairing_users = resolve_pairing_officers(report, on_date=on_date)
    result = ApprovedReportRecipients(to_users=pairing_users)
    seen = set()

    for user in pairing_users:
        email = _valid_email(user)
        if not email:
            result.excluded.append(f"{user.get_username()}: email kosong/tidak valid")
            continue
        key = email.casefold()
        if key in seen:
            result.excluded.append(f"{email}: duplikat TO")
            continue
        seen.add(key)
        result.to.append(email)

    if not result.to:
        result.reason = "Pairing Officer aktif tidak memiliki email valid."
        return result

    pairing = pairing_users[0]
    organization = resolve_pairing_organization_unit(pairing, on_date=on_date)
    if organization is None:
        result.reason = "Pemetaan Organization Unit Pairing belum tersedia; Pairing-only."
        return result

    for user in resolve_organization_head_chain(organization, on_date=on_date):
        email = _valid_email(user)
        if not email:
            result.excluded.append(f"{user.get_username()}: email kosong/tidak valid")
            continue
        key = email.casefold()
        if key in seen:
            result.excluded.append(f"{email}: duplikat/terdapat di TO")
            continue
        seen.add(key)
        result.cc.append(email)
        result.cc_users.append(user)

    result.reason = "Penerima disusun dari Pairing Officer dan rantai kepala organisasi."
    return result
