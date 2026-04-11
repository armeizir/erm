from django.contrib import admin

from riskproject.admin_site import risk_admin_site
from .models import (
    MonthlyRiskReport,
    MonthlyRiskReportItem,
    MonthlyRiskReportKMAlignment,
    MonthlyRiskReportSubmissionLog,
)


class MonthlyRiskReportItemInline(admin.TabularInline):
    model = MonthlyRiskReportItem
    extra = 0
    raw_id_fields = ["risk_event", "km_item"]
    readonly_fields = [
        "inherent_level",
        "residual_level",
        "target_residual_level",
        "mitigation_progress_percent",
        "mitigation_status",
    ]


@admin.register(MonthlyRiskReport, site=risk_admin_site)
class MonthlyRiskReportAdmin(admin.ModelAdmin):
    list_display = [
        "kode",
        "unit",
        "periode",
        "status",
        "total_risiko",
        "total_high",
        "total_mitigasi_terlambat",
    ]
    list_filter = ["tahun_buku", "periode", "status", "unit"]
    search_fields = ["kode", "judul"]
    raw_id_fields = ["tahun_buku", "periode", "unit", "kontrak_manajemen", "reassessment"]
    inlines = [MonthlyRiskReportItemInline]


@admin.register(MonthlyRiskReportItem, site=risk_admin_site)
class MonthlyRiskReportItemAdmin(admin.ModelAdmin):
    list_display = [
        "report",
        "risk_event",
        "km_item",
        "inherent_level",
        "residual_level",
        "target_residual_level",
        "mitigation_progress_percent",
        "mitigation_status",
        "contributes_to_corporate",
    ]
    list_filter = [
        "contributes_to_corporate",
        "mitigation_status",
        "trend",
    ]
    search_fields = ["issue_summary", "next_action", "escalation_note"]
    raw_id_fields = ["report", "risk_event", "km_item"]


@admin.register(MonthlyRiskReportKMAlignment, site=risk_admin_site)
class MonthlyRiskReportKMAlignmentAdmin(admin.ModelAdmin):
    list_display = [
        "report_item",
        "km_item",
        "alignment_status",
        "alignment_score",
    ]
    list_filter = ["alignment_status"]
    search_fields = ["reason"]
    raw_id_fields = ["report_item", "km_item"]


@admin.register(MonthlyRiskReportSubmissionLog, site=risk_admin_site)
class MonthlyRiskReportSubmissionLogAdmin(admin.ModelAdmin):
    list_display = [
        "report",
        "action",
        "action_by",
        "action_at",
    ]
    list_filter = ["action", "action_at"]
    search_fields = ["note"]
    raw_id_fields = ["report", "action_by"]