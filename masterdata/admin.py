from django.contrib import admin
from django.utils.html import format_html, format_html_join

from riskproject.admin_site import risk_admin_site
from masterdata.models import (
    BusinessArea,
    CompanyCode,
    Directorate,
    Division,
    OrganizationUnit,
    OrganizationUnitAccessGroup,
    PeriodeLaporan,
    PersonnelArea,
    PersonnelSubArea,
    TahunBuku,
)


def blue_badges(items):
    items = list(items)
    if not items:
        return "-"
    return format_html_join(
        " ",
        '<span style="display:inline-block; margin:2px; padding:3px 8px; '
        'border-radius:4px; background:#1976d2; color:white; font-weight:600;">{} - {}</span>',
        ((item.code, item.description if hasattr(item, "description") else item.name) for item in items),
    )


class StaffCanViewAdminMixin:
    def has_module_permission(self, request):
        return super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj)


class BusinessAreaInline(admin.TabularInline):
    model = BusinessArea
    extra = 0
    fields = ("code", "description", "aktif")
    ordering = ("code",)


class PersonnelSubAreaInline(admin.TabularInline):
    model = PersonnelSubArea
    extra = 0
    fields = ("code", "description", "aktif")
    ordering = ("code",)


class OrganizationUnitInline(admin.TabularInline):
    model = OrganizationUnit
    fk_name = "parent"
    extra = 0
    fields = ("code", "name", "business_area", "personnel_sub_area", "aktif")
    ordering = ("code",)


class OrganizationUnitAccessGroupInline(admin.TabularInline):
    model = OrganizationUnitAccessGroup
    fk_name = "organization_unit"
    extra = 0
    fields = ("group", "utama", "aktif")
    autocomplete_fields = ("group",)
    verbose_name = "Grup Bidang / Unit Bisnis"
    verbose_name_plural = "Grup Bidang / Unit Bisnis (cakupan akses)"


@admin.register(CompanyCode)
class CompanyCodeAdmin(StaffCanViewAdminMixin, admin.ModelAdmin):
    list_display = ("code", "description", "business_area_badges", "aktif")
    search_fields = ("code", "description", "business_areas__code", "business_areas__description")
    list_filter = ("aktif",)
    inlines = [BusinessAreaInline]

    @admin.display(description="Business Area")
    def business_area_badges(self, obj):
        return blue_badges(obj.business_areas.order_by("code"))


@admin.register(BusinessArea)
class BusinessAreaAdmin(StaffCanViewAdminMixin, admin.ModelAdmin):
    list_display = ("code", "description", "company", "aktif")
    search_fields = ("code", "description", "company__code", "company__description")
    list_filter = ("company", "aktif")
    autocomplete_fields = ("company",)


@admin.register(PersonnelArea)
class PersonnelAreaAdmin(StaffCanViewAdminMixin, admin.ModelAdmin):
    list_display = ("code", "description", "personnel_sub_area_badges", "aktif")
    search_fields = ("code", "description", "sub_areas__code", "sub_areas__description")
    list_filter = ("aktif",)
    autocomplete_fields = ("company",)
    inlines = [PersonnelSubAreaInline]

    @admin.display(description="Personnel Sub Area")
    def personnel_sub_area_badges(self, obj):
        return blue_badges(obj.sub_areas.order_by("code"))


@admin.register(PersonnelSubArea)
class PersonnelSubAreaAdmin(StaffCanViewAdminMixin, admin.ModelAdmin):
    list_display = ("code", "description", "personnel_area", "aktif")
    search_fields = ("code", "description", "personnel_area__code", "personnel_area__description")
    list_filter = ("personnel_area", "aktif")
    autocomplete_fields = ("personnel_area",)


@admin.register(Directorate)
class DirectorateAdmin(StaffCanViewAdminMixin, admin.ModelAdmin):
    list_display = ("code", "description", "child_badges", "aktif")
    search_fields = ("code", "description", "organization_units__code", "organization_units__name")
    list_filter = ("aktif",)

    @admin.display(description="Child")
    def child_badges(self, obj):
        return blue_badges(obj.organization_units.order_by("code"))


@admin.register(Division)
class DivisionAdmin(StaffCanViewAdminMixin, admin.ModelAdmin):
    list_display = ("code", "description", "child_badges", "aktif")
    search_fields = ("code", "description", "organization_units__code", "organization_units__name")
    list_filter = ("directorate", "aktif")
    autocomplete_fields = ("directorate",)

    @admin.display(description="Child")
    def child_badges(self, obj):
        return blue_badges(obj.organization_units.order_by("code"))


@admin.register(OrganizationUnit)
class OrganizationUnitAdmin(StaffCanViewAdminMixin, admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "business_area",
        "personnel_sub_area",
        "parent",
        "access_groups",
        "aktif",
    )
    search_fields = (
        "code",
        "name",
        "business_area__description",
        "personnel_sub_area__description",
        "parent__code",
        "parent__name",
    )
    list_filter = ("company", "business_area", "personnel_area", "directorate", "division", "aktif")
    autocomplete_fields = (
        "company",
        "business_area",
        "personnel_area",
        "personnel_sub_area",
        "directorate",
        "division",
        "parent",
    )
    inlines = [OrganizationUnitAccessGroupInline, OrganizationUnitInline]

    @admin.display(description="Bidang / Unit Bisnis")
    def access_groups(self, obj):
        return ", ".join(
            obj.access_group_mappings.filter(aktif=True)
            .order_by("group__name")
            .values_list("group__name", flat=True)
        ) or "-"


@admin.register(TahunBuku)
class TahunBukuAdmin(admin.ModelAdmin):
    list_display = ("tahun", "aktif")
    list_filter = ("aktif",)
    ordering = ("-tahun",)

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        try:
            if search_term:
                queryset |= self.model.objects.filter(tahun=int(search_term))
        except ValueError:
            pass
        return queryset, use_distinct


@admin.register(PeriodeLaporan)
class PeriodeLaporanAdmin(admin.ModelAdmin):
    list_display = (
        "nama_periode",
        "tahun_buku",
        "kode_periode",
        "jenis_periode",
        "tanggal_mulai",
        "tanggal_selesai",
        "is_locked",
    )
    list_filter = ("jenis_periode", "tahun_buku", "is_locked")
    search_fields = ("nama_periode", "kode_periode", "tahun_buku__tahun")
    ordering = ("tahun_buku__tahun", "tanggal_mulai")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "tahun_buku":
            kwargs["queryset"] = TahunBuku.objects.order_by('-tahun')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


for model, model_admin in (
    (CompanyCode, CompanyCodeAdmin),
    (BusinessArea, BusinessAreaAdmin),
    (PersonnelArea, PersonnelAreaAdmin),
    (PersonnelSubArea, PersonnelSubAreaAdmin),
    (Directorate, DirectorateAdmin),
    (Division, DivisionAdmin),
    (OrganizationUnit, OrganizationUnitAdmin),
):
    try:
        risk_admin_site.register(model, model_admin)
    except admin.sites.AlreadyRegistered:
        pass
