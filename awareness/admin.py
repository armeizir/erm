from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils import timezone
from openpyxl import Workbook

from riskproject.admin_site import risk_admin_site

from .models import AwarenessAnswer, AwarenessAttempt, AwarenessCampaign, AwarenessQuestion
from .notifications import send_awareness_notification


class StaffAwarenessAdminMixin:
    def _is_awareness_staff(self, request):
        return bool(request.user and request.user.is_active and request.user.is_staff)

    def has_module_permission(self, request):
        return self._is_awareness_staff(request)

    def has_view_permission(self, request, obj=None):
        return self._is_awareness_staff(request)

    def has_add_permission(self, request):
        return self._is_awareness_staff(request)

    def has_change_permission(self, request, obj=None):
        return self._is_awareness_staff(request)

    def has_delete_permission(self, request, obj=None):
        return self._is_awareness_staff(request)


class AwarenessQuestionInline(admin.TabularInline):
    model = AwarenessQuestion
    extra = 1
    fields = (
        "order",
        "question_text",
        "option_a",
        "option_b",
        "option_c",
        "option_d",
        "correct_answer",
        "difficulty",
        "weight",
        "is_active",
    )


@admin.register(AwarenessCampaign)
class AwarenessCampaignAdmin(StaffAwarenessAdminMixin, admin.ModelAdmin):
    list_display = (
        "title",
        "topic",
        "start_date",
        "end_date",
        "passing_score",
        "max_attempts",
        "is_active",
        "send_test_link",
        "report_link",
        "export_link",
    )
    search_fields = ("title", "description", "topic")
    list_filter = ("topic", "is_active", "start_date", "end_date")
    inlines = (AwarenessQuestionInline,)
    readonly_fields = ("material_preview", "created_at", "updated_at")
    fieldsets = (
        (None, {
            "fields": (
                "title",
                "description",
                "topic",
                "material_image",
                "material_preview",
                "start_date",
                "end_date",
                "passing_score",
                "max_attempts",
                "time_limit_minutes",
                "is_active",
            )
        }),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description="Preview Materi")
    def material_preview(self, obj):
        if not obj or not obj.material_image:
            return "-"
        return format_html(
            '<img src="{}" style="max-width:420px; width:100%; height:auto; border:1px solid #d9e1ec; border-radius:6px;">',
            obj.material_image.url,
        )

    def get_urls(self):
        custom_urls = [
            path(
                "report/",
                self.admin_site.admin_view(self.report_view),
                name="awareness_campaign_report",
            ),
            path(
                "<int:campaign_id>/export-xlsx/",
                self.admin_site.admin_view(self.export_xlsx_view),
                name="awareness_campaign_export_xlsx",
            ),
            path(
                "<int:campaign_id>/send-test/",
                self.admin_site.admin_view(self.send_test_view),
                name="awareness_campaign_send_test",
            ),
        ]
        return custom_urls + super().get_urls()

    @admin.display(description="Report")
    def report_link(self, obj):
        url = reverse(f"{self.admin_site.name}:awareness_campaign_report")
        return format_html('<a class="button" href="{}">Report</a>', url)

    @admin.display(description="Export")
    def export_link(self, obj):
        url = reverse(f"{self.admin_site.name}:awareness_campaign_export_xlsx", args=[obj.pk])
        return format_html('<a class="button" href="{}">Export XLSX</a>', url)

    @admin.display(description="Notifikasi")
    def send_test_link(self, obj):
        url = reverse(f"{self.admin_site.name}:awareness_campaign_send_test", args=[obj.pk])
        return format_html('<a class="button" href="{}">Kirim Test</a>', url)

    def send_test_view(self, request, campaign_id):
        if not self._is_awareness_staff(request):
            self.message_user(request, "Anda tidak memiliki permission kirim notifikasi awareness.", messages.ERROR)
            return redirect("..")
        campaign = get_object_or_404(AwarenessCampaign, pk=campaign_id)
        recipient = request.GET.get("email") or request.user.email or "armeizir@plnbatam.com"
        sent = send_awareness_notification(campaign, [recipient], request=request)
        if sent:
            self.message_user(request, f"Test notifikasi awareness terkirim ke {recipient}.", messages.SUCCESS)
        else:
            self.message_user(request, f"Test notifikasi awareness gagal dikirim ke {recipient}.", messages.ERROR)
        return redirect(reverse(f"{self.admin_site.name}:awareness_awarenesscampaign_changelist"))

    def _report_context(self, request):
        attempts = AwarenessAttempt.objects.select_related("campaign", "user")
        submitted = attempts.exclude(status=AwarenessAttempt.STATUS_IN_PROGRESS)
        active_campaigns = AwarenessCampaign.objects.filter(is_active=True).count()
        total_participants = submitted.values("user_id").distinct().count()
        passed_count = submitted.filter(status=AwarenessAttempt.STATUS_PASSED).count()
        failed_count = submitted.filter(status=AwarenessAttempt.STATUS_FAILED).count()
        total_attempts = attempts.count()
        avg_score = submitted.aggregate(avg=Avg("score"))["avg"] or 0
        active_users = get_user_model().objects.filter(is_active=True)
        attempted_user_ids = attempts.values_list("user_id", flat=True).distinct()
        not_attempted_users = active_users.exclude(id__in=attempted_user_ids).order_by("username")[:50]
        completion_rate = (total_participants / active_users.count() * 100) if active_users.exists() else 0
        pass_rate = (passed_count / submitted.count() * 100) if submitted.exists() else 0

        campaign_rows = AwarenessCampaign.objects.annotate(
            attempt_count=Count("attempts"),
            participant_count=Count("attempts__user", distinct=True),
            passed_count=Count("attempts", filter=Q(attempts__status=AwarenessAttempt.STATUS_PASSED)),
            avg_score=Avg("attempts__score"),
        ).order_by("-start_date", "title")

        top_users = submitted.order_by("-score", "submitted_at")[:10]
        return {
            **self.admin_site.each_context(request),
            "title": "Awareness Campaign Report",
            "active_campaigns": active_campaigns,
            "total_participants": total_participants,
            "total_attempts": total_attempts,
            "avg_score": avg_score,
            "passed_count": passed_count,
            "failed_count": failed_count,
            "completion_rate": completion_rate,
            "pass_rate": pass_rate,
            "top_users": top_users,
            "not_attempted_users": not_attempted_users,
            "campaign_rows": campaign_rows,
        }

    def report_view(self, request):
        if not self._is_awareness_staff(request):
            self.message_user(request, "Anda tidak memiliki permission melihat report awareness.", messages.ERROR)
            return redirect("..")
        return TemplateResponse(request, "admin/awareness/report.html", self._report_context(request))

    def export_xlsx_view(self, request, campaign_id):
        if not self._is_awareness_staff(request):
            self.message_user(request, "Anda tidak memiliki permission export awareness.", messages.ERROR)
            return redirect("..")
        campaign = get_object_or_404(AwarenessCampaign, pk=campaign_id)
        wb = Workbook()
        ws = wb.active
        ws.title = "Awareness Results"
        ws.append([
            "campaign",
            "user",
            "email",
            "unit/organisasi",
            "attempt number",
            "started_at",
            "submitted_at",
            "duration",
            "score",
            "status",
            "correct_count",
            "wrong_count",
        ])
        for attempt in campaign.attempts.select_related("user", "campaign").order_by("user__username", "attempt_number"):
            user = attempt.user
            unit = getattr(user, "unit", "") or getattr(user, "organization", "") or ""
            ws.append([
                campaign.title,
                user.get_username(),
                user.email,
                str(unit) if unit else "",
                attempt.attempt_number,
                timezone.localtime(attempt.started_at).strftime("%Y-%m-%d %H:%M:%S") if attempt.started_at else "",
                timezone.localtime(attempt.submitted_at).strftime("%Y-%m-%d %H:%M:%S") if attempt.submitted_at else "",
                attempt.duration_seconds,
                float(attempt.score or 0),
                attempt.status,
                attempt.correct_count,
                attempt.wrong_count,
            ])

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = f'attachment; filename="awareness_results_{campaign.pk}.xlsx"'
        wb.save(response)
        return response


@admin.register(AwarenessQuestion)
class AwarenessQuestionAdmin(StaffAwarenessAdminMixin, admin.ModelAdmin):
    list_display = ("campaign", "order", "question_text_short", "correct_answer", "difficulty", "is_active")
    list_filter = ("campaign", "difficulty", "is_active")
    search_fields = ("question_text", "option_a", "option_b", "option_c", "option_d")
    autocomplete_fields = ("campaign",)

    @admin.display(description="Pertanyaan")
    def question_text_short(self, obj):
        return obj.question_text[:100]


@admin.register(AwarenessAttempt)
class AwarenessAttemptAdmin(StaffAwarenessAdminMixin, admin.ModelAdmin):
    list_display = (
        "campaign",
        "user",
        "score",
        "status",
        "correct_count",
        "wrong_count",
        "started_at",
        "submitted_at",
    )
    list_filter = ("campaign", "status", "submitted_at")
    search_fields = ("user__username", "user__email", "campaign__title")
    readonly_fields = (
        "campaign",
        "user",
        "started_at",
        "submitted_at",
        "score",
        "total_questions",
        "correct_count",
        "wrong_count",
        "status",
        "attempt_number",
        "duration_seconds",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return self._is_awareness_staff(request)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AwarenessAnswer)
class AwarenessAnswerAdmin(StaffAwarenessAdminMixin, admin.ModelAdmin):
    list_display = ("attempt", "question", "selected_answer", "is_correct", "answered_at")
    readonly_fields = ("attempt", "question", "selected_answer", "is_correct", "answered_at")
    list_filter = ("is_correct", "selected_answer")
    search_fields = ("attempt__user__username", "question__question_text")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return self._is_awareness_staff(request)

    def has_delete_permission(self, request, obj=None):
        return False


for model, model_admin in (
    (AwarenessCampaign, AwarenessCampaignAdmin),
    (AwarenessQuestion, AwarenessQuestionAdmin),
    (AwarenessAttempt, AwarenessAttemptAdmin),
    (AwarenessAnswer, AwarenessAnswerAdmin),
):
    try:
        risk_admin_site.register(model, model_admin)
    except Exception:
        pass
