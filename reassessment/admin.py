from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import ReAssessment, RiskEvent, ReAssessmentWorkflowLog
from .workflow import ReAssessmentWorkflowService


class RiskEventInline(admin.TabularInline):
    model = RiskEvent
    extra = 0


class ReAssessmentWorkflowLogInline(admin.TabularInline):
    model = ReAssessmentWorkflowLog
    extra = 0
    readonly_fields = ("action", "from_status", "to_status", "actor", "note", "metadata", "acted_at")
    can_delete = False


@admin.register(ReAssessment)
class ReAssessmentAdmin(admin.ModelAdmin):
    list_display = (
        "kode", "judul", "tahun_buku", "periode", "unit",
        "status", "submitted_at", "approved_rkm_at", "approved_km_at", "locked_at"
    )
    list_filter = ("tahun_buku", "periode", "unit", "status", "is_escalated")
    search_fields = ("kode", "judul", "unit__nama")
    inlines = [RiskEventInline, ReAssessmentWorkflowLogInline]

    actions = [
        "action_submit",
        "action_approve_rkm",
        "action_approve_km",
        "action_lock",
    ]

    def action_submit(self, request, queryset):
        for obj in queryset:
            try:
                ReAssessmentWorkflowService.submit(obj, request.user, note="Submit via admin action")
            except ValidationError as e:
                self.message_user(request, f"{obj.kode}: {'; '.join(e.messages)}", level=messages.ERROR)
        self.message_user(request, "Action submit selesai.")
    action_submit.short_description = "Submit selected reassessments"

    def action_approve_rkm(self, request, queryset):
        for obj in queryset:
            try:
                ReAssessmentWorkflowService.approve_rkm(obj, request.user, note="Approve RKM via admin action")
            except ValidationError as e:
                self.message_user(request, f"{obj.kode}: {'; '.join(e.messages)}", level=messages.ERROR)
        self.message_user(request, "Action approve RKM selesai.")
    action_approve_rkm.short_description = "Approve RKM"

    def action_approve_km(self, request, queryset):
        for obj in queryset:
            try:
                ReAssessmentWorkflowService.approve_km(obj, request.user, note="Approve KM via admin action")
            except ValidationError as e:
                self.message_user(request, f"{obj.kode}: {'; '.join(e.messages)}", level=messages.ERROR)
        self.message_user(request, "Action approve KM selesai.")
    action_approve_km.short_description = "Approve KM"

    def action_lock(self, request, queryset):
        for obj in queryset:
            try:
                ReAssessmentWorkflowService.lock(obj, request.user, note="Lock via admin action")
            except ValidationError as e:
                self.message_user(request, f"{obj.kode}: {'; '.join(e.messages)}", level=messages.ERROR)
        self.message_user(request, "Action lock selesai.")
    action_lock.short_description = "Lock approved reassessments"


@admin.register(RiskEvent)
class RiskEventAdmin(admin.ModelAdmin):
    list_display = (
        "reassessment", "no_risiko", "peristiwa_risiko",
        "km_item", "risk_owner", "confidence_level", "escalate_to_km"
    )
    list_filter = ("confidence_level", "escalate_to_km", "status_risiko")
    search_fields = ("no_risiko", "peristiwa_risiko", "reassessment__kode")


@admin.register(ReAssessmentWorkflowLog)
class ReAssessmentWorkflowLogAdmin(admin.ModelAdmin):
    list_display = ("reassessment", "action", "from_status", "to_status", "actor", "acted_at")
    list_filter = ("action", "to_status", "acted_at")
    search_fields = ("reassessment__kode", "note", "actor__username")
    readonly_fields = ("reassessment", "action", "from_status", "to_status", "actor", "note", "metadata", "acted_at")