from django.db import migrations


def normalize_organization_names_and_mappings(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    OrganizationUnit = apps.get_model("masterdata", "OrganizationUnit")
    Mapping = apps.get_model("masterdata", "OrganizationUnitAccessGroup")

    # SETPER is the official name. Rename the legacy access group when doing
    # so cannot collide with an already existing canonical group.
    setper_group = Group.objects.filter(name="SETPER").first()
    legacy_setper_group = Group.objects.filter(name="SEKPER").first()
    if setper_group is None and legacy_setper_group is not None:
        legacy_setper_group.name = "SETPER"
        legacy_setper_group.save(update_fields=["name"])
        setper_group = legacy_setper_group

    setper_unit = OrganizationUnit.objects.filter(name="SETPER").first()
    if setper_group and setper_unit:
        Mapping.objects.get_or_create(
            group=setper_group,
            organization_unit=setper_unit,
            defaults={"utama": True, "aktif": True},
        )

    # Org code 10091868 is the canonical BID RENKIN unit. Keeping the code
    # stable preserves its hierarchy and every existing master-data relation.
    renkin_unit = OrganizationUnit.objects.filter(code="10091868").first()
    if renkin_unit and renkin_unit.name != "BID RENKIN":
        renkin_unit.name = "BID RENKIN"
        renkin_unit.save(update_fields=["name"])

    renkin_group = Group.objects.filter(name="BID RENKIN").first()
    if renkin_group and renkin_unit:
        Mapping.objects.get_or_create(
            group=renkin_group,
            organization_unit=renkin_unit,
            defaults={"utama": True, "aktif": True},
        )


def reverse_normalization(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    OrganizationUnit = apps.get_model("masterdata", "OrganizationUnit")
    Mapping = apps.get_model("masterdata", "OrganizationUnitAccessGroup")

    Mapping.objects.filter(
        group__name="BID RENKIN",
        organization_unit__code="10091868",
    ).delete()
    renkin_unit = OrganizationUnit.objects.filter(code="10091868").first()
    if renkin_unit and renkin_unit.name == "BID RENKIN":
        renkin_unit.name = "BID REN"
        renkin_unit.save(update_fields=["name"])

    Mapping.objects.filter(
        group__name="SETPER",
        organization_unit__name="SETPER",
    ).delete()
    setper_group = Group.objects.filter(name="SETPER").first()
    if setper_group and not Group.objects.filter(name="SEKPER").exists():
        setper_group.name = "SEKPER"
        setper_group.save(update_fields=["name"])


class Migration(migrations.Migration):
    dependencies = [
        ("masterdata", "0006_map_organization_access_groups"),
    ]

    operations = [
        migrations.RunPython(
            normalize_organization_names_and_mappings,
            reverse_normalization,
        ),
    ]
