from django.db import migrations


# Mappings are intentionally limited to names that are exact matches or have
# one unambiguous legacy alias. Combined/uncertain scopes are completed in the
# admin after the responsible organization owner confirms them.
EXACT_GROUP_NAMES = (
    "BID AGA",
    "BID BIS",
    "BID HCGA",
    "BID KEU",
    "BID MANPRO",
    "BID MRK",
    "BID OPS",
    "BID STRADA",
    "UB BES",
    "UB DISYAN",
    "UB INFRA",
)

LEGACY_ALIASES = {
    "KSPI": "SPI",
    "UB KITRAN": "UB KITRANS",
}


def map_organization_access_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    OrganizationUnit = apps.get_model("masterdata", "OrganizationUnit")
    Mapping = apps.get_model("masterdata", "OrganizationUnitAccessGroup")

    mappings = {name: name for name in EXACT_GROUP_NAMES}
    mappings.update(LEGACY_ALIASES)

    for group_name, organization_name in mappings.items():
        group = Group.objects.filter(name=group_name).first()
        organization_unit = OrganizationUnit.objects.filter(
            name=organization_name
        ).first()
        if not group or not organization_unit:
            continue
        Mapping.objects.get_or_create(
            group=group,
            organization_unit=organization_unit,
            defaults={"utama": True, "aktif": True},
        )


def unmap_seeded_organization_access_groups(apps, schema_editor):
    Mapping = apps.get_model("masterdata", "OrganizationUnitAccessGroup")
    pairs = list((name, name) for name in EXACT_GROUP_NAMES)
    pairs.extend(LEGACY_ALIASES.items())
    for group_name, organization_name in pairs:
        Mapping.objects.filter(
            group__name=group_name,
            organization_unit__name=organization_name,
        ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("masterdata", "0005_organizationunitaccessgroup"),
    ]

    operations = [
        migrations.RunPython(
            map_organization_access_groups,
            unmap_seeded_organization_access_groups,
        ),
    ]
