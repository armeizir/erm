from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.utils.html import format_html

from .models import (
    ReAssessment,
    RiskEvent,
    RiskCause,
    RiskIndicator,
    ExistingControl,
    RiskAssessment,
    TreatmentPlan,
    TreatmentTimeline,
    TreatmentProgress,
    ReAssessmentWorkflowLog,
)
from .workflow import ReAssessmentWorkflowService


class RiskEventInline(admin.TabularInline):
    model = RiskEvent
    extra = 0


class WorkflowLogInline(admin.TabularInline):
    model = ReAssessmentWorkflowLog
    extra = 0
    can_delete = False
    readonly_fields = (
        "action",
        "from_status",
        "to_status",
        "actor",
        "note",
        "metadata",
        "acted_at",
    )


@admin.register(ReAssessment)
class ReAssessmentAdmin(admin.ModelAdmin):
    list_display = (
        "kode",
        "judul",
        "tahun_buku",
        "periode",
        "unit",
        "colored_status",
        "submitted_at",
        "approved_rkm_at",
        "approved_km_at",
        "locked_at",
        "is_escalated",
    )
    list_filter = ("tahun_buku", "periode", "unit", "status", "is_escalated")
    search_fields = ("kode", "judul", "unit__nama")
    readonly_fields = ("workflow_buttons", "colored_status")
    inlines = [RiskEventInline, WorkflowLogInline]

    fieldsets = (
        ("Informasi Utama", {
            "fields": (
                "kode", "judul", "tahun_buku", "periode", "unit",
                "kontrak_manajemen", "versi", "status", "colored_status",
            )
        }),
        ("PIC & Approval", {
            "fields": (
                "prepared_by",
                "reviewed_by_rkm", "approved_by_rkm",
                "reviewed_by_km", "approved_by_km",
            )
        }),
        ("Timeline Workflow", {
            "fields": (
                "submitted_at",
                "reviewed_rkm_at", "approved_rkm_at",
                "reviewed_km_at", "approved_km_at",
                "locked_at",
            )
        }),
        ("Catatan", {
            "fields": ("catatan_unit", "catatan_rkm", "catatan_km", "is_escalated")
        }),
        ("Workflow Action", {
            "fields": ("workflow_buttons",)
        }),
    )

    actions = [
        "action_submit",
        "action_start_rkm_review",
        "action_approve_rkm",
        "action_start_km_review",
        "action_approve_km",
        "action_lock",
    ]

    def colored_status(self, obj):
        color_map = {
            "draft": "#6c757d",
            "submitted": "#0d6efd",
            "review_rkm": "#ffc107",
            "rejected_rkm": "#dc3545",
            "approved_rkm": "#198754",
            "review_km": "#fd7e14",
            "rejected_km": "#dc3545",
            "approved_km": "#20c997",
            "locked": "#212529",
        }
        label_map = dict(ReAssessment.STATUS_CHOICES)
        color = color_map.get(obj.status, "#6c757d")
        label = label_map.get(obj.status, obj.status)
        return format_html(
            '<span style="padding:4px 10px; border-radius:12px; color:white; background:{};">{}</span>',
            color,
            label,
        )
    colored_status.short_description = "Status"

    def workflow_buttons(self, obj):
        if not obj or not obj.pk:
            return "Simpan data terlebih dahulu untuk menampilkan tombol workflow."

        buttons = []

        def btn(url_name, label, color):
            url = reverse(url_name, args=[obj.pk])
            return (
                f'<a class="button" href="{url}" '
                f'style="margin-right:8px; margin-bottom:8px; '
                f'background:{color}; color:white; padding:8px 12px; '
                f'border-radius:6px; text-decoration:none;">{label}</a>'
            )

        if obj.status in {"draft", "rejected_rkm", "rejected_km"}:
            buttons.append(btn("admin:reassessment_reassessment_submit", "Submit", "#0d6efd"))

        if obj.status == "submitted":
            buttons.append(btn("admin:reassessment_reassessment_start_rkm_review", "Start RKM Review", "#ffc107"))
            buttons.append(btn("admin:reassessment_reassessment_approve_rkm", "Approve RKM", "#198754"))
            buttons.append(btn("admin:reassessment_reassessment_reject_rkm", "Reject RKM", "#dc3545"))

        if obj.status == "review_rkm":
            buttons.append(btn("admin:reassessment_reassessment_approve_rkm", "Approve RKM", "#198754"))
            buttons.append(btn("admin:reassessment_reassessment_reject_rkm", "Reject RKM", "#dc3545"))

        if obj.status == "approved_rkm":
            buttons.append(btn("admin:reassessment_reassessment_start_km_review", "Start KM Review", "#fd7e14"))
            buttons.append(btn("admin:reassessment_reassessment_approve_km", "Approve KM", "#20c997"))
            buttons.append(btn("admin:reassessment_reassessment_reject_km", "Reject KM", "#dc3545"))

        if obj.status == "review_km":
            buttons.append(btn("admin:reassessment_reassessment_approve_km", "Approve KM", "#20c997"))
            buttons.append(btn("admin:reassessment_reassessment_reject_km", "Reject KM", "#dc3545"))

        if obj.status == "approved_km":
            buttons.append(btn("admin:reassessment_reassessment_lock", "Lock", "#212529"))

        if not buttons:
            return "Tidak ada action tersedia."

        return format_html(" ".join(buttons))

    workflow_buttons.short_description = "Action Buttons"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:object_id>/submit/",
                self.admin_site.admin_view(self.submit_view),
                name="reassessment_reassessment_submit",
            ),
            path(
                "<int:object_id>/start-rkm-review/",
                self.admin_site.admin_view(self.start_rkm_review_view),
                name="reassessment_reassessment_start_rkm_review",
            ),
            path(
                "<int:object_id>/approve-rkm/",
                self.admin_site.admin_view(self.approve_rkm_view),
                name="reassessment_reassessment_approve_rkm",
            ),
            path(
                "<int:object_id>/reject-rkm/",
                self.admin_site.admin_view(self.reject_rkm_view),
                name="reassessment_reassessment_reject_rkm",
            ),
            path(
                "<int:object_id>/start-km-review/",
                self.admin_site.admin_view(self.start_km_review_view),
                name="reassessment_reassessment_start_km_review",
            ),
            path(
                "<int:object_id>/approve-km/",
                self.admin_site.admin_view(self.approve_km_view),
                name="reassessment_reassessment_approve_km",
            ),
            path(
                "<int:object_id>/reject-km/",
                self.admin_site.admin_view(self.reject_km_view),
                name="reassessment_reassessment_reject_km",
            ),
            path(
                "<int:object_id>/lock/",
                self.admin_site.admin_view(self.lock_view),
                name="reassessment_reassessment_lock",
            ),
        ]
        return custom_urls + urls

    def _redirect_to_change(self, obj):
        url = reverse("admin:reassessment_reassessment_change", args=[obj.pk])
        return HttpResponseRedirect(url)

    def submit_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        try:
            ReAssessmentWorkflowService.submit(obj, request.user, note="Submit via admin button")
            self.message_user(request, "ReAssessment berhasil di-submit.", level=messages.SUCCESS)
        except ValidationError as e:
            self.message_user(request, "; ".join(e.messages), level=messages.ERROR)
        return self._redirect_to_change(obj)

    def start_rkm_review_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        try:
            ReAssessmentWorkflowService.start_rkm_review(obj, request.user, note="Start RKM review via admin button")
            self.message_user(request, "ReAssessment masuk tahap review RKM.", level=messages.SUCCESS)
        except ValidationError as e:
            self.message_user(request, "; ".join(e.messages), level=messages.ERROR)
        return self._redirect_to_change(obj)

    def approve_rkm_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        try:
            ReAssessmentWorkflowService.approve_rkm(obj, request.user, note="Approve RKM via admin button")
            self.message_user(request, "ReAssessment berhasil di-approve RKM.", level=messages.SUCCESS)
        except ValidationError as e:
            self.message_user(request, "; ".join(e.messages), level=messages.ERROR)
        return self._redirect_to_change(obj)

    def reject_rkm_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        try:
            ReAssessmentWorkflowService.reject_rkm(obj, request.user, note="Reject RKM via admin button")
            self.message_user(request, "ReAssessment ditolak pada level RKM.", level=messages.SUCCESS)
        except ValidationError as e:
            self.message_user(request, "; ".join(e.messages), level=messages.ERROR)
        return self._redirect_to_change(obj)

    def start_km_review_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        try:
            ReAssessmentWorkflowService.start_km_review(obj, request.user, note="Start KM review via admin button")
            self.message_user(request, "ReAssessment masuk tahap review KM.", level=messages.SUCCESS)
        except ValidationError as e:
            self.message_user(request, "; ".join(e.messages), level=messages.ERROR)
        return self._redirect_to_change(obj)

    def approve_km_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        try:
            ReAssessmentWorkflowService.approve_km(obj, request.user, note="Approve KM via admin button")
            self.message_user(request, "ReAssessment berhasil di-approve KM.", level=messages.SUCCESS)
        except ValidationError as e:
            self.message_user(request, "; ".join(e.messages), level=messages.ERROR)
        return self._redirect_to_change(obj)

    def reject_km_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        try:
            ReAssessmentWorkflowService.reject_km(obj, request.user, note="Reject KM via admin button")
            self.message_user(request, "ReAssessment ditolak pada level KM.", level=messages.SUCCESS)
        except ValidationError as e:
            self.message_user(request, "; ".join(e.messages), level=messages.ERROR)
        return self._redirect_to_change(obj)

    def lock_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        try:
            ReAssessmentWorkflowService.lock(obj, request.user, note="Lock via admin button")
            self.message_user(request, "ReAssessment berhasil di-lock.", level=messages.SUCCESS)
        except ValidationError as e:
            self.message_user(request, "; ".join(e.messages), level=messages.ERROR)
        return self._redirect_to_change(obj)

    def action_submit(self, request, queryset):
        for obj in queryset:
            try:
                ReAssessmentWorkflowService.submit(obj, request.user, note="Submit via admin action")
            except ValidationError as e:
                self.message_user(request, f"{obj.kode}: {'; '.join(e.messages)}", level=messages.ERROR)
        self.message_user(request, "Action submit selesai.")
    action_submit.short_description = "Submit selected reassessments"

    def action_start_rkm_review(self, request, queryset):
        for obj in queryset:
            try:
                ReAssessmentWorkflowService.start_rkm_review(obj, request.user, note="Start RKM review via admin action")
            except ValidationError as e:
                self.message_user(request, f"{obj.kode}: {'; '.join(e.messages)}", level=messages.ERROR)
        self.message_user(request, "Action start RKM review selesai.")
    action_start_rkm_review.short_description = "Start RKM review"

    def action_approve_rkm(self, request, queryset):
        for obj in queryset:
            try:
                ReAssessmentWorkflowService.approve_rkm(obj, request.user, note="Approve RKM via admin action")
            except ValidationError as e:
                self.message_user(request, f"{obj.kode}: {'; '.join(e.messages)}", level=messages.ERROR)
        self.message_user(request, "Action approve RKM selesai.")
    action_approve_rkm.short_description = "Approve RKM"

    def action_start_km_review(self, request, queryset):
        for obj in queryset:
            try:
                ReAssessmentWorkflowService.start_km_review(obj, request.user, note="Start KM review via admin action")
            except ValidationError as e:
                self.message_user(request, f"{obj.kode}: {'; '.join(e.messages)}", level=messages.ERROR)
        self.message_user(request, "Action start KM review selesai.")
    action_start_km_review.short_description = "Start KM review"

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
    action_lock.short_description = "Lock reassessments"


@admin.register(RiskEvent)
class RiskEventAdmin(admin.ModelAdmin):
    list_display = (
        "reassessment",
        "no_risiko",
        "peristiwa_risiko",
        "km_item",
        "risk_owner",
        "confidence_level",
        "is_key_risk",
        "escalate_to_km",
    )
    list_filter = ("confidence_level", "is_key_risk", "escalate_to_km", "status_risiko")
    search_fields = ("no_risiko", "peristiwa_risiko", "reassessment__kode")


@admin.register(RiskCause)
class RiskCauseAdmin(admin.ModelAdmin):
    list_display = ("risk_event", "no_penyebab", "urutan")
    search_fields = ("risk_event__no_risiko", "deskripsi_penyebab")


@admin.register(RiskIndicator)
class RiskIndicatorAdmin(admin.ModelAdmin):
    list_display = ("nama_kri", "risk_event", "risk_cause", "status_threshold")
    search_fields = ("nama_kri", "risk_event__no_risiko")


@admin.register(ExistingControl)
class ExistingControlAdmin(admin.ModelAdmin):
    list_display = ("nama_control", "risk_event", "risk_cause", "pemilik_control")
    search_fields = ("nama_control", "risk_event__no_risiko")


@admin.register(RiskAssessment)
class RiskAssessmentAdmin(admin.ModelAdmin):
    list_display = ("risk_event", "periode", "risk_type", "level_risiko", "warna_level")
    list_filter = ("risk_type", "periode")
    search_fields = ("risk_event__no_risiko",)


@admin.register(TreatmentPlan)
class TreatmentPlanAdmin(admin.ModelAdmin):
    list_display = ("risk_event", "opsi_perlakuan", "status", "pic", "target_mulai", "target_selesai")
    list_filter = ("status", "opsi_perlakuan")
    search_fields = ("risk_event__no_risiko", "rencana_perlakuan")


@admin.register(TreatmentTimeline)
class TreatmentTimelineAdmin(admin.ModelAdmin):
    list_display = ("treatment_plan", "bulan_ke", "planned_flag", "actual_flag")
    list_filter = ("planned_flag", "actual_flag")


@admin.register(TreatmentProgress)
class TreatmentProgressAdmin(admin.ModelAdmin):
    list_display = ("treatment_plan", "periode", "persentase_progress", "status_realisasi", "updated_by")
    list_filter = ("status_realisasi", "periode")


@admin.register(ReAssessmentWorkflowLog)
class ReAssessmentWorkflowLogAdmin(admin.ModelAdmin):
    list_display = ("reassessment", "action", "from_status", "to_status", "actor", "acted_at")
    list_filter = ("action", "to_status", "acted_at")
    search_fields = ("reassessment__kode", "note", "actor__username")
    readonly_fields = ("reassessment", "action", "from_status", "to_status", "actor", "note", "metadata", "acted_at")