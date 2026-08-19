from __future__ import annotations

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseRedirect
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from icofr.forms import ICoFRScheduleForm, RCMUploadForm
from icofr.models import (
    ICoFRPeriod,
    RCMControl,
    RCMControlAttribute,
    RCMEntry,
    RCMEntryAssertion,
    RCMImportBatch,
    RCMMapping,
    RCMRisk,
    RCMSet,
    RCMType,
    RCMSupportingDocument,
    CSAEvidence,
    CSAIneffectivenessCategory,
    CSAAssessment,
    CSAAssessmentReviewLog,
    CSASample,
    CSASampleAttributeResult,
    ICoFRDistributionBatch,
    ICoFRQuestion,
    ICoFRSchedule,
    ICoFRScheduleUnit,
    ICoFRStage,
    ICoFRWorkItem,
    QuestionnaireAnswer,
    QuestionnaireEvidence,
    QuestionnaireSubmission,
)
from icofr.services.exporter import build_rcm_export
from icofr.services.importer import import_batch, validate_batch
from icofr.services.mapping import auto_map_rcm
from icofr.services.phase2 import distribute_schedule_stage, ensure_sample_attributes, preview_schedule_stage
from masterdata.models import OrganizationUnit
from riskproject.admin_site import risk_admin_site


class LockByRCMAdminMixin:
    rcm_lookup = "rcm_set"

    def _rcm(self, obj):
        if not obj:
            return None
        current = obj
        for part in self.rcm_lookup.split("__"):
            current = getattr(current, part)
        return current

    def has_change_permission(self, request, obj=None):
        allowed = super().has_change_permission(request, obj=obj)
        rcm = self._rcm(obj)
        return allowed and not (rcm and rcm.is_locked)

    def has_delete_permission(self, request, obj=None):
        allowed = super().has_delete_permission(request, obj=obj)
        rcm = self._rcm(obj)
        return allowed and not (rcm and rcm.is_locked)


class RCMEntryAssertionInline(admin.TabularInline):
    model = RCMEntryAssertion
    extra = 0


class RCMControlAttributeInline(admin.TabularInline):
    model = RCMControlAttribute
    extra = 0


class RCMSupportingDocumentInline(admin.TabularInline):
    model = RCMSupportingDocument
    extra = 0


class RCMSetAdmin(admin.ModelAdmin):
    change_list_template = "admin/icofr/rcmset/change_list.html"
    list_display = (
        "rcm_type",
        "version",
        "status_badge",
        "source_row_count",
        "risk_count",
        "control_count",
        "mapping_health",
        "imported_at",
        "quick_actions",
    )
    list_filter = ("rcm_type", "status")
    search_fields = ("version", "entity_name", "source_filename")
    readonly_fields = (
        "status",
        "source_filename",
        "source_sha256",
        "source_row_count",
        "imported_by",
        "imported_at",
        "finalized_by",
        "finalized_at",
        "created_at",
        "updated_at",
    )
    actions = ("finalize_selected", "auto_map_selected")

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path("import/", self.admin_site.admin_view(self.import_view), name="icofr_rcm_import"),
            path(
                "import/<int:batch_id>/confirm/",
                self.admin_site.admin_view(self.import_confirm_view),
                name="icofr_rcm_import_confirm",
            ),
            path(
                "<int:rcm_id>/export/",
                self.admin_site.admin_view(self.export_view),
                name="icofr_rcm_export",
            ),
        ]
        return custom + urls

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {"DRAFT": "#d97706", "FINAL": "#15803d", "ARCHIVED": "#64748b"}
        return format_html(
            '<span style="font-weight:700;color:{}">{}</span>',
            colors.get(obj.status, "#334155"),
            obj.get_status_display(),
        )

    @admin.display(description="Risiko")
    def risk_count(self, obj):
        return obj.risks.count()

    @admin.display(description="Kontrol")
    def control_count(self, obj):
        return obj.controls.count()

    @admin.display(description="Mapping")
    def mapping_health(self, obj):
        total = obj.entries.count()
        mapped = RCMMapping.objects.filter(entry__rcm_set=obj, status__in=[RCMMapping.Status.MAPPED, RCMMapping.Status.MANUAL]).count()
        return f"{mapped}/{total}" if total else "-"

    @admin.display(description="Aksi")
    def quick_actions(self, obj):
        export_url = reverse("risk_admin:icofr_rcm_export", args=[obj.pk])
        entries_url = reverse("risk_admin:icofr_rcmentry_changelist") + f"?rcm_set__id__exact={obj.pk}"
        return format_html('<a href="{}">Detail</a> &nbsp; <a href="{}">Export</a>', entries_url, export_url)

    def has_change_permission(self, request, obj=None):
        allowed = super().has_change_permission(request, obj=obj)
        if obj and obj.is_locked:
            return False
        return allowed

    def has_delete_permission(self, request, obj=None):
        allowed = super().has_delete_permission(request, obj=obj)
        if obj and obj.is_locked:
            return False
        return allowed

    @admin.action(description="Finalisasi / lock RCM terpilih")
    def finalize_selected(self, request, queryset):
        finalized = 0
        errors = []
        for rcm in queryset:
            try:
                rcm.finalize(request.user)
                finalized += 1
            except ValidationError as exc:
                errors.append(f"{rcm}: {exc}")
        if finalized:
            self.message_user(request, f"{finalized} RCM berhasil difinalisasi dan dikunci.", messages.SUCCESS)
        for error in errors[:5]:
            self.message_user(request, error, messages.ERROR)

    @admin.action(description="Auto-map preparer/reviewer (strict exact position)")
    def auto_map_selected(self, request, queryset):
        totals = {"total": 0, "mapped": 0, "partial": 0, "failed": 0}
        for rcm in queryset:
            result = auto_map_rcm(rcm, user=request.user)
            for key in totals:
                totals[key] += result[key]
        self.message_user(
            request,
            "Mapping selesai — total: {total}, mapped: {mapped}, partial: {partial}, gagal: {failed}.".format(**totals),
            messages.INFO,
        )

    def import_view(self, request):
        if not self.has_add_permission(request):
            return self.admin_site.login(request)
        form = RCMUploadForm(request.POST or None, request.FILES or None)
        if request.method == "POST" and form.is_valid():
            uploaded = form.cleaned_data["file"]
            batch = RCMImportBatch.objects.create(
                upload=uploaded,
                original_filename=uploaded.name,
                uploaded_by=request.user,
            )
            validate_batch(batch)
            return HttpResponseRedirect(reverse("risk_admin:icofr_rcm_import_confirm", args=[batch.pk]))
        context = {
            **self.admin_site.each_context(request),
            "title": "Import RCM Excel — Phase 1",
            "opts": self.model._meta,
            "form": form,
            "batch": None,
        }
        return TemplateResponse(request, "admin/icofr/rcmset/import_form.html", context)

    def import_confirm_view(self, request, batch_id):
        batch = get_object_or_404(RCMImportBatch, pk=batch_id)
        if request.method == "POST" and batch.can_import:
            try:
                rcm = import_batch(batch, user=request.user)
            except Exception as exc:
                batch.refresh_from_db()
                self.message_user(request, f"Import gagal: {exc}", messages.ERROR)
            else:
                self.message_user(
                    request,
                    f"RCM {rcm.rcm_type} versi {rcm.version} berhasil diimpor: {rcm.source_row_count} baris.",
                    messages.SUCCESS,
                )
                return HttpResponseRedirect(reverse("risk_admin:icofr_rcmset_change", args=[rcm.pk]))
        context = {
            **self.admin_site.each_context(request),
            "title": "Preview & Validasi Import RCM",
            "opts": self.model._meta,
            "form": None,
            "batch": batch,
        }
        return TemplateResponse(request, "admin/icofr/rcmset/import_form.html", context)

    def export_view(self, request, rcm_id):
        rcm = get_object_or_404(RCMSet, pk=rcm_id)
        if not self.has_view_permission(request, rcm):
            return self.admin_site.login(request)
        content = build_rcm_export(rcm)
        filename = f"RCM_{rcm.rcm_type}_{rcm.version.replace('/', '-')}.xlsx"
        response = HttpResponse(content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class RCMRiskAdmin(LockByRCMAdminMixin, admin.ModelAdmin):
    list_display = ("reference", "rcm_set", "risk_level", "impact", "likelihood")
    list_filter = ("rcm_set__rcm_type", "rcm_set", "risk_level", "impact", "likelihood")
    search_fields = ("reference", "description", "control_area", "control_sub_area", "coso_element")
    autocomplete_fields = ("rcm_set",)


class RCMControlAdmin(LockByRCMAdminMixin, admin.ModelAdmin):
    list_display = ("reference", "rcm_set", "control_type", "is_key_control", "anti_fraud")
    list_filter = ("rcm_set__rcm_type", "rcm_set", "control_type", "is_key_control", "anti_fraud")
    search_fields = ("reference", "objective", "description", "supporting_application")
    autocomplete_fields = ("rcm_set",)


class RCMEntryAdmin(LockByRCMAdminMixin, admin.ModelAdmin):
    list_display = (
        "source_row_number",
        "rcm_set",
        "risk_reference",
        "control_reference",
        "segment",
        "location",
        "preparer_position",
        "mapping_status",
    )
    list_filter = ("rcm_set__rcm_type", "rcm_set", "segment", "location", "frequency")
    search_fields = (
        "risk__reference",
        "risk__description",
        "control__reference",
        "control__description",
        "subprocess_number",
        "subprocess_description",
        "account_description",
        "preparer_position",
        "reviewer_position",
    )
    autocomplete_fields = ("rcm_set", "risk", "control")
    readonly_fields = ("source_row_number", "source_fingerprint", "raw_payload", "created_at", "updated_at")
    inlines = (RCMEntryAssertionInline, RCMControlAttributeInline, RCMSupportingDocumentInline)
    fieldsets = (
        ("Identitas", {"fields": ("rcm_set", "risk", "control", "entity_name", "source_row_number")}),
        ("Proses / Akun TLC", {"fields": ("subprocess_number", "subprocess_description", "account_description", "assertions_raw")}),
        ("Aktivitas Kontrol", {"fields": ("location", "location_description", "frequency", "preparer_position", "reviewer_position", "compensating_control", "segment")}),
        ("Audit Source", {"classes": ("collapse",), "fields": ("source_fingerprint", "raw_payload", "created_at", "updated_at")}),
    )

    @admin.display(description="Ref Risiko", ordering="risk__reference")
    def risk_reference(self, obj):
        return obj.risk.reference

    @admin.display(description="Ref Kontrol", ordering="control__reference")
    def control_reference(self, obj):
        return obj.control.reference

    @admin.display(description="Mapping")
    def mapping_status(self, obj):
        try:
            return obj.mapping.get_status_display()
        except RCMMapping.DoesNotExist:
            return "Belum Dipetakan"


class RCMMappingAdmin(admin.ModelAdmin):
    list_display = ("entry", "status", "preparer_user", "reviewer_user", "mapped_at")
    list_filter = ("status", "entry__rcm_set__rcm_type", "entry__rcm_set")
    search_fields = (
        "entry__risk__reference",
        "entry__control__reference",
        "entry__preparer_position",
        "entry__reviewer_position",
        "preparer_user__username",
        "reviewer_user__username",
    )
    autocomplete_fields = ("entry", "preparer_user", "reviewer_user", "mapped_by")
    readonly_fields = ("mapped_at", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        obj.mapped_by = request.user
        obj.refresh_status(manual=True)
        super().save_model(request, obj, form, change)


class RCMImportBatchAdmin(admin.ModelAdmin):
    list_display = ("created_at", "original_filename", "detected_type", "detected_version", "status", "row_count", "uploaded_by", "imported_rcm")
    list_filter = ("status", "detected_type")
    search_fields = ("original_filename", "detected_version", "source_sha256")
    readonly_fields = tuple(field.name for field in RCMImportBatch._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


class ICoFRPeriodAdmin(admin.ModelAdmin):
    list_display = ("year", "name", "rcm_type", "start_date", "end_date", "is_active")
    list_filter = ("year", "rcm_type", "is_active")
    search_fields = ("name",)




def _is_icofr_admin(user):
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.groups.filter(name="ROLE - ICOFR ADMIN").exists())
    )


class ICoFRScheduleUnitInline(admin.TabularInline):
    model = ICoFRScheduleUnit
    extra = 0
    autocomplete_fields = ("organization_unit",)


class ICoFRScheduleAdmin(admin.ModelAdmin):
    form = ICoFRScheduleForm
    change_form_template = "admin/icofr/icofrschedule/change_form.html"
    list_display = (
        "period",
        "rcm_set",
        "questionnaire_window",
        "line1_window",
        "unit_count",
        "distribution_actions",
    )
    list_filter = ("period__year", "period__rcm_type", "rcm_set__rcm_type")
    search_fields = ("period__name", "rcm_set__version", "notes")
    autocomplete_fields = ("period", "rcm_set")
    readonly_fields = ("created_by", "created_at", "updated_at")
    inlines = (ICoFRScheduleUnitInline,)
    fieldsets = (
        ("Periode & RCM", {"fields": ("period", "rcm_set", "notes")}),
        ("Kuesioner", {"fields": ("questionnaire_active", "questionnaire_start", "questionnaire_end")}),
        ("Line 1 — CSA", {"fields": ("line1_active", "line1_start", "line1_end")}),
        ("Future Stage", {"classes": ("collapse",), "fields": (
            "line2_active", "line2_start", "line2_end",
            "line3_active", "line3_start", "line3_end",
        )}),
        ("Audit", {"classes": ("collapse",), "fields": ("created_by", "created_at", "updated_at")}),
    )

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        readiness = []
        if obj and obj.pk:
            for stage in (ICoFRStage.QUESTIONNAIRE, ICoFRStage.LINE1):
                config = obj.stage_config(stage)
                if not config["active"]:
                    readiness.append({
                        "stage": stage,
                        "stage_label": stage.label,
                        "active": False,
                        "error": "Tahap belum diaktifkan.",
                    })
                    continue
                try:
                    preview = preview_schedule_stage(obj, stage)
                except ValidationError as exc:
                    readiness.append({
                        "stage": stage,
                        "stage_label": stage.label,
                        "active": True,
                        "error": str(exc),
                    })
                else:
                    preview["active"] = True
                    preview["preview_url"] = reverse("risk_admin:icofr_schedule_distribute", args=[obj.pk, stage.value])
                    readiness.append(preview)
        context["icofr_readiness"] = readiness
        context["icofr_timezone"] = timezone.get_current_timezone_name()
        context["icofr_workitem_url"] = reverse("risk_admin:icofr_icofrworkitem_changelist")
        return super().render_change_form(request, context, add, change, form_url, obj)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:schedule_id>/distribute/<str:stage>/",
                self.admin_site.admin_view(self.distribute_view),
                name="icofr_schedule_distribute",
            )
        ]
        return custom + urls

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        obj.full_clean()
        super().save_model(request, obj, form, change)

    @admin.display(description="Kuesioner")
    def questionnaire_window(self, obj):
        if not obj.questionnaire_active:
            return "Belum aktif"
        return f"{obj.questionnaire_start:%d-%m-%Y} s.d. {obj.questionnaire_end:%d-%m-%Y}"

    @admin.display(description="Line 1")
    def line1_window(self, obj):
        if not obj.line1_active:
            return "Belum aktif"
        return f"{obj.line1_start:%d-%m-%Y} s.d. {obj.line1_end:%d-%m-%Y}"

    @admin.display(description="Unit Aktif")
    def unit_count(self, obj):
        return obj.unit_activations.count()

    @admin.display(description="Distribusi")
    def distribution_actions(self, obj):
        q_url = reverse("risk_admin:icofr_schedule_distribute", args=[obj.pk, ICoFRStage.QUESTIONNAIRE])
        l1_url = reverse("risk_admin:icofr_schedule_distribute", args=[obj.pk, ICoFRStage.LINE1])
        return format_html('<a href="{}">Kuesioner</a> &nbsp; <a href="{}">Line 1</a>', q_url, l1_url)

    def distribute_view(self, request, schedule_id, stage):
        schedule = get_object_or_404(ICoFRSchedule, pk=schedule_id)
        if not self.has_change_permission(request, schedule):
            return self.admin_site.login(request)
        try:
            stage_value = ICoFRStage(stage)
            preview = preview_schedule_stage(schedule, stage_value)
        except (ValueError, ValidationError) as exc:
            self.message_user(request, f"Distribusi belum siap: {exc}", messages.ERROR)
            return HttpResponseRedirect(reverse("risk_admin:icofr_icofrschedule_change", args=[schedule.pk]))

        if request.method == "POST":
            try:
                batch = distribute_schedule_stage(schedule, stage_value, user=request.user)
            except ValidationError as exc:
                self.message_user(request, f"Distribusi gagal: {exc}", messages.ERROR)
                return HttpResponseRedirect(reverse("risk_admin:icofr_icofrschedule_change", args=[schedule.pk]))

            detail = batch.summary.get("skip_reasons", {})
            detail_text = "; ".join(f"{key}: {value}" for key, value in detail.items())
            message = (
                f"Distribusi {stage_value.label}: {batch.distributed_count}/{batch.total_entries} entry berhasil; "
                f"{batch.skipped_count} dilewati."
            )
            if detail_text:
                message += f" {detail_text}"
            self.message_user(request, message, messages.SUCCESS if not batch.skipped_count else messages.WARNING)
            work_items_url = reverse("risk_admin:icofr_icofrworkitem_changelist")
            return HttpResponseRedirect(
                f"{work_items_url}?schedule__id__exact={schedule.pk}&stage__exact={stage_value.value}"
            )

        context = {
            **self.admin_site.each_context(request),
            "title": f"Pre-flight Distribusi — {stage_value.label}",
            "opts": self.model._meta,
            "schedule": schedule,
            "preview": preview,
            "stage": stage_value,
            "back_url": reverse("risk_admin:icofr_icofrschedule_change", args=[schedule.pk]),
        }
        return TemplateResponse(request, "admin/icofr/icofrschedule/distribute_preview.html", context)


class ICoFRDistributionBatchAdmin(admin.ModelAdmin):
    list_display = ("distributed_at", "schedule", "stage", "status", "distributed_count", "skipped_count", "distributed_by")
    list_filter = ("stage", "status", "schedule__period__year", "schedule__rcm_set__rcm_type")
    readonly_fields = tuple(field.name for field in ICoFRDistributionBatch._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ICoFRWorkItemAdmin(admin.ModelAdmin):
    change_list_template = "admin/icofr/icofrworkitem/change_list.html"
    list_display = (
        "stage", "rcm_type", "risk_ref", "control_ref", "organization_unit",
        "preparer_user", "reviewer_user", "status", "workflow_action",
    )
    list_filter = (
        "stage",
        "status",
        ("schedule", admin.RelatedOnlyFieldListFilter),
        ("schedule__period", admin.RelatedOnlyFieldListFilter),
        "schedule__period__year",
        "schedule__rcm_set__rcm_type",
        ("organization_unit", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = (
        "entry__risk__reference", "entry__control__reference", "entry__control__description",
        "preparer_user__username", "preparer_user__first_name", "preparer_user__last_name",
        "reviewer_user__username", "reviewer_user__first_name", "reviewer_user__last_name",
        "organization_unit__code", "organization_unit__name", "entry__segment",
    )
    autocomplete_fields = ("schedule", "entry", "organization_unit", "preparer_user", "reviewer_user")
    readonly_fields = ("distribution_batch", "created_at", "updated_at")
    list_per_page = 50

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        if not hasattr(response, "context_data"):
            return response
        cl = response.context_data.get("cl")
        filtered_qs = cl.queryset if cl is not None else self.get_queryset(request)
        response.context_data.update({
            "icofr_stage_choices": ICoFRStage.choices,
            "icofr_status_choices": ICoFRWorkItem.Status.choices,
            "icofr_rcm_choices": RCMType.choices,
            "icofr_periods": ICoFRPeriod.objects.filter(schedules__work_items__isnull=False).distinct().order_by("-year", "name"),
            "icofr_units": OrganizationUnit.objects.filter(icofr_work_items__isnull=False).distinct().order_by("code", "name"),
            "icofr_total": filtered_qs.count(),
            "icofr_ready": filtered_qs.filter(status=ICoFRWorkItem.Status.READY).count(),
            "icofr_submitted": filtered_qs.filter(status=ICoFRWorkItem.Status.SUBMITTED).count(),
            "icofr_rejected": filtered_qs.filter(status=ICoFRWorkItem.Status.REJECTED).count(),
            "icofr_approved": filtered_qs.filter(status__in=[ICoFRWorkItem.Status.APPROVED, ICoFRWorkItem.Status.FINISHED]).count(),
        })
        return response

    def has_add_permission(self, request):
        # Pelaksana Risk Control/work item hanya boleh dibentuk oleh proses Distribusi.
        # Tidak ada pembuatan manual dari Django Admin agar jadwal, RCM, unit,
        # Preparer dan Reviewer selalu berasal dari snapshot distribusi yang valid.
        return False

    def has_change_permission(self, request, obj=None):
        # Work item adalah hasil distribusi dan bersifat read-only. Django Admin
        # tetap dapat menampilkan detail melalui view permission, tetapi tidak
        # menyediakan form perubahan manual.
        return False

    def has_delete_permission(self, request, obj=None):
        # Penghapusan work item harus mengikuti lifecycle distribusi, bukan delete manual.
        return False

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:work_item_id>/open/",
                self.admin_site.admin_view(self.open_work_item_view),
                name="icofr_workitem_open",
            ),
        ]
        return custom + urls

    def open_work_item_view(self, request, work_item_id):
        item = get_object_or_404(
            ICoFRWorkItem.objects.select_related(
                "entry__risk", "entry__control", "schedule__rcm_set",
                "preparer_user", "reviewer_user",
            ),
            pk=work_item_id,
        )
        can_view = bool(
            _is_icofr_admin(request.user)
            or item.preparer_user_id == request.user.pk
            or item.reviewer_user_id == request.user.pk
        )
        if not can_view:
            self.message_user(request, "Anda tidak memiliki akses ke work item ini.", messages.ERROR)
            return HttpResponseRedirect(reverse("risk_admin:icofr_icofrworkitem_changelist"))

        if item.stage == ICoFRStage.LINE1:
            try:
                assessment = item.csa_assessment
            except CSAAssessment.DoesNotExist:
                self.message_user(request, "CSA Line 1 belum terbentuk. Jalankan distribusi Line 1 kembali.", messages.ERROR)
                return HttpResponseRedirect(reverse("risk_admin:icofr_icofrworkitem_changelist"))

            editable = assessment.status in {
                CSAAssessment.Status.READY,
                CSAAssessment.Status.DRAFT,
                CSAAssessment.Status.REJECTED,
            }
            if (item.preparer_user_id == request.user.pk or _is_icofr_admin(request.user)) and editable:
                return HttpResponseRedirect(reverse("risk_admin:icofr_csaassessment_change", args=[assessment.pk]))
            return HttpResponseRedirect(reverse("risk_admin:icofr_csa_review", args=[assessment.pk]))

        if item.stage == ICoFRStage.QUESTIONNAIRE:
            try:
                submission = item.questionnaire_submission
            except QuestionnaireSubmission.DoesNotExist:
                self.message_user(request, "Kuesioner belum terbentuk. Jalankan distribusi Kuesioner kembali.", messages.ERROR)
                return HttpResponseRedirect(reverse("risk_admin:icofr_icofrworkitem_changelist"))
            return HttpResponseRedirect(reverse("risk_admin:icofr_questionnairesubmission_change", args=[submission.pk]))

        self.message_user(request, "Tahap ini belum mempunyai halaman kerja pada Phase 2.", messages.INFO)
        return HttpResponseRedirect(reverse("risk_admin:icofr_icofrworkitem_changelist"))

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("entry__risk", "entry__control", "schedule__rcm_set")
        if _is_icofr_admin(request.user):
            return qs
        return qs.filter(Q(preparer_user=request.user) | Q(reviewer_user=request.user))

    @admin.display(description="RCM")
    def rcm_type(self, obj):
        return obj.schedule.rcm_set.rcm_type

    @admin.display(description="Ref Risiko")
    def risk_ref(self, obj):
        return obj.entry.risk.reference

    @admin.display(description="Ref Kontrol")
    def control_ref(self, obj):
        return obj.entry.control.reference

    @admin.display(description="Aksi")
    def workflow_action(self, obj):
        if obj.stage not in {ICoFRStage.QUESTIONNAIRE, ICoFRStage.LINE1}:
            return "-"
        url = reverse("risk_admin:icofr_workitem_open", args=[obj.pk])
        if obj.stage == ICoFRStage.QUESTIONNAIRE:
            label = "Buka Kuesioner"
        elif obj.status == ICoFRWorkItem.Status.SUBMITTED:
            label = "Review CSA"
        elif obj.status == ICoFRWorkItem.Status.APPROVED:
            label = "Lihat CSA"
        elif obj.status == ICoFRWorkItem.Status.REJECTED:
            label = "Perbaiki CSA"
        else:
            label = "Kerjakan CSA"
        return format_html('<a class="button" href="{}">{}</a>', url, label)


class ICoFRQuestionAdmin(admin.ModelAdmin):
    list_display = ("rcm_type", "sequence", "question", "is_active")
    list_filter = ("rcm_type", "is_active")
    list_editable = ("sequence", "is_active")
    search_fields = ("question",)


class QuestionnaireAnswerInline(admin.TabularInline):
    model = QuestionnaireAnswer
    extra = 0
    fields = ("question", "answer", "change_description")
    readonly_fields = ("question",)

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        if obj and obj.status not in {QuestionnaireSubmission.Status.READY, QuestionnaireSubmission.Status.DRAFT, QuestionnaireSubmission.Status.REJECTED}:
            return False
        return super().has_change_permission(request, obj=obj)


class QuestionnaireEvidenceInline(admin.TabularInline):
    model = QuestionnaireEvidence
    extra = 0
    exclude = ("uploaded_by",)

    def has_add_permission(self, request, obj=None):
        if obj and obj.status not in {QuestionnaireSubmission.Status.READY, QuestionnaireSubmission.Status.DRAFT, QuestionnaireSubmission.Status.REJECTED}:
            return False
        return super().has_add_permission(request, obj=obj)

    def has_change_permission(self, request, obj=None):
        if obj and obj.status not in {QuestionnaireSubmission.Status.READY, QuestionnaireSubmission.Status.DRAFT, QuestionnaireSubmission.Status.REJECTED}:
            return False
        return super().has_change_permission(request, obj=obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj=obj)


class QuestionnaireSubmissionAdmin(admin.ModelAdmin):
    list_display = ("work_item", "rcm_type", "status", "has_change_badge", "submitted_at", "reviewed_by", "reviewed_at")
    list_filter = ("status", "work_item__schedule__period__year", "work_item__schedule__rcm_set__rcm_type")
    search_fields = ("work_item__entry__risk__reference", "work_item__entry__control__reference", "work_item__preparer_user__username")
    readonly_fields = ("work_item", "status", "submitted_at", "reviewed_by", "reviewed_at", "created_at", "updated_at")
    inlines = (QuestionnaireAnswerInline, QuestionnaireEvidenceInline)
    actions = ("submit_selected", "approve_requested", "reject_requested")

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("work_item__entry__rcm_set", "work_item__preparer_user")
        if _is_icofr_admin(request.user):
            return qs
        return qs.filter(work_item__preparer_user=request.user)

    def has_change_permission(self, request, obj=None):
        base = super().has_change_permission(request, obj=obj)
        if not base or obj is None:
            return base
        if _is_icofr_admin(request.user):
            return True
        return (
            obj.work_item.preparer_user_id == request.user.pk
            and obj.status in {QuestionnaireSubmission.Status.READY, QuestionnaireSubmission.Status.DRAFT, QuestionnaireSubmission.Status.REJECTED}
        )

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, QuestionnaireEvidence) and not instance.uploaded_by_id:
                instance.uploaded_by = request.user
            instance.save()
        for obj in formset.deleted_objects:
            obj.delete()
        formset.save_m2m()

    @admin.display(description="RCM")
    def rcm_type(self, obj):
        return obj.work_item.entry.rcm_set.rcm_type

    @admin.display(description="Ada Perubahan", boolean=True)
    def has_change_badge(self, obj):
        return obj.has_change

    @admin.action(description="Kirim kuesioner terpilih")
    def submit_selected(self, request, queryset):
        success = 0
        for obj in queryset:
            if not _is_icofr_admin(request.user) and obj.work_item.preparer_user_id != request.user.pk:
                continue
            try:
                obj.submit()
            except ValidationError as exc:
                self.message_user(request, f"{obj}: {exc}", messages.ERROR)
            else:
                success += 1
        if success:
            self.message_user(request, f"{success} kuesioner berhasil diproses/dikirim.", messages.SUCCESS)

    @admin.action(description="Setujui kuesioner Requested")
    def approve_requested(self, request, queryset):
        if not _is_icofr_admin(request.user):
            self.message_user(request, "Hanya ICOFR Admin yang dapat menyetujui usulan.", messages.ERROR)
            return
        success = 0
        for obj in queryset:
            try:
                obj.approve(request.user)
            except ValidationError as exc:
                self.message_user(request, f"{obj}: {exc}", messages.ERROR)
            else:
                success += 1
        if success:
            self.message_user(request, f"{success} usulan kuesioner disetujui.", messages.SUCCESS)

    @admin.action(description="Tolak kuesioner Requested (isi Catatan Admin dahulu)")
    def reject_requested(self, request, queryset):
        if not _is_icofr_admin(request.user):
            return
        count = 0
        now = timezone.now()
        for obj in queryset.filter(status=QuestionnaireSubmission.Status.REQUESTED).exclude(admin_note=""):
            obj.status = QuestionnaireSubmission.Status.REJECTED
            obj.reviewed_by = request.user
            obj.reviewed_at = now
            obj.save(update_fields=("status", "reviewed_by", "reviewed_at", "updated_at"))
            obj.work_item.status = ICoFRWorkItem.Status.REJECTED
            obj.work_item.save(update_fields=("status", "updated_at"))
            count += 1
        self.message_user(request, f"{count} usulan kuesioner ditolak.", messages.WARNING)


class CSAIneffectivenessCategoryAdmin(admin.ModelAdmin):
    list_display = ("rcm_type", "name", "is_active")
    list_filter = ("rcm_type", "is_active")
    search_fields = ("name", "description")


class CSASampleInline(admin.TabularInline):
    model = CSASample
    extra = 0
    fields = ("description", "transaction_date", "result", "notes")
    show_change_link = True
    verbose_name = "Sampel Transaksi"
    verbose_name_plural = "2. Sampel Transaksi"

    def _editable(self, obj):
        return not obj or obj.status in {CSAAssessment.Status.READY, CSAAssessment.Status.DRAFT, CSAAssessment.Status.REJECTED}

    def has_add_permission(self, request, obj=None):
        return self._editable(obj) and super().has_add_permission(request, obj=obj)

    def has_change_permission(self, request, obj=None):
        return self._editable(obj) and super().has_change_permission(request, obj=obj)

    def has_delete_permission(self, request, obj=None):
        return self._editable(obj) and super().has_delete_permission(request, obj=obj)


class CSAEvidenceAssessmentInline(admin.TabularInline):
    model = CSAEvidence
    fk_name = "assessment"
    extra = 0
    exclude = ("sample", "uploaded_by")
    verbose_name = "Evidence Umum / TAT"
    verbose_name_plural = "3. Evidence Umum / TAT"

    def _editable(self, obj):
        return not obj or obj.status in {CSAAssessment.Status.READY, CSAAssessment.Status.DRAFT, CSAAssessment.Status.REJECTED}

    def has_add_permission(self, request, obj=None):
        return self._editable(obj) and super().has_add_permission(request, obj=obj)

    def has_change_permission(self, request, obj=None):
        return self._editable(obj) and super().has_change_permission(request, obj=obj)

    def has_delete_permission(self, request, obj=None):
        return self._editable(obj) and super().has_delete_permission(request, obj=obj)


class CSAAssessmentAdmin(admin.ModelAdmin):
    change_form_template = "admin/icofr/csaassessment/change_form.html"
    fieldsets = (
        ("1. Penilaian CSA", {"fields": ("result",)}),
        (
            "Ketidakefektifan & Perbaikan",
            {"fields": ("ineffectiveness_category", "ineffectiveness_explanation")},
        ),
    )
    @admin.display(description="Kontrol")
    def control_identity(self, obj):
        return f"{obj.work_item.entry.risk.reference} / {obj.work_item.entry.control.reference}"

    @admin.display(description="Periode")
    def period_name(self, obj):
        return obj.work_item.schedule.period.name

    @admin.display(description="Hasil")
    def result_badge(self, obj):
        if not obj.result:
            return "-"
        colors = {
            CSAAssessment.Result.EFFECTIVE: "#15803d",
            CSAAssessment.Result.INEFFECTIVE: "#b91c1c",
            CSAAssessment.Result.TAT: "#a16207",
        }
        return format_html('<span style="font-weight:700;color:{}">{}</span>', colors.get(obj.result, "#334155"), obj.get_result_display())

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            CSAAssessment.Status.READY: "#64748b",
            CSAAssessment.Status.DRAFT: "#2563eb",
            CSAAssessment.Status.SUBMITTED: "#7c3aed",
            CSAAssessment.Status.APPROVED: "#15803d",
            CSAAssessment.Status.REJECTED: "#b91c1c",
        }
        return format_html('<span style="font-weight:700;color:{}">{}</span>', colors.get(obj.status, "#334155"), obj.get_status_display())

    @admin.display(description="Aksi")
    def review_action(self, obj):
        url = reverse("risk_admin:icofr_csa_review", args=[obj.pk])
        label = "Review" if obj.status == CSAAssessment.Status.SUBMITTED else "Detail"
        return format_html('<a class="button" href="{}">{}</a>', url, label)

    list_display = (
        "control_identity", "rcm_type", "period_name", "preparer", "reviewer",
        "result_badge", "status_badge", "review_round", "submitted_at", "review_action",
    )
    list_filter = ("status", "result", "work_item__schedule__period__year", "work_item__schedule__rcm_set__rcm_type")
    search_fields = (
        "work_item__entry__risk__reference", "work_item__entry__control__reference",
        "work_item__entry__control__description", "work_item__preparer_user__username",
        "work_item__preparer_user__first_name", "work_item__preparer_user__last_name",
        "work_item__reviewer_user__username",
    )
    readonly_fields = (
        "work_item", "status", "review_round", "submitted_at", "reviewed_by",
        "reviewed_at", "reviewer_note", "created_at", "updated_at"
    )
    inlines = (CSASampleInline, CSAEvidenceAssessmentInline)
    actions = ("submit_selected",)

    def has_add_permission(self, request):
        # CSA tidak dibuat manual. Objek CSA dibentuk otomatis oleh proses Distribusi Line 1.
        return False

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:assessment_id>/review/",
                self.admin_site.admin_view(self.review_view),
                name="icofr_csa_review",
            ),
        ]
        return custom + urls

    def _can_review(self, request, obj):
        return bool(
            request.user.is_superuser
            or obj.work_item.reviewer_user_id == request.user.pk
        )

    def review_view(self, request, assessment_id):
        obj = get_object_or_404(
            CSAAssessment.objects.select_related(
                "work_item__entry__risk", "work_item__entry__control",
                "work_item__entry__rcm_set", "work_item__schedule__period",
                "work_item__organization_unit", "work_item__preparer_user",
                "work_item__reviewer_user", "ineffectiveness_category",
            ).prefetch_related(
                "samples__attribute_results__attribute",
                "samples__evidences__supporting_document",
                "evidences__supporting_document", "review_logs__actor",
            ),
            pk=assessment_id,
        )
        can_view = bool(
            _is_icofr_admin(request.user)
            or obj.work_item.preparer_user_id == request.user.pk
            or obj.work_item.reviewer_user_id == request.user.pk
        )
        if not can_view:
            self.message_user(request, "Anda tidak memiliki akses untuk melihat CSA ini.", messages.ERROR)
            return HttpResponseRedirect(reverse("risk_admin:icofr_csaassessment_changelist"))

        if request.method == "POST":
            if not self._can_review(request, obj):
                self.message_user(
                    request,
                    "Hanya Control Reviewer yang terdistribusi yang dapat memberikan keputusan CSA.",
                    messages.ERROR,
                )
            else:
                action = request.POST.get("review_action")
                note = (request.POST.get("review_note") or "").strip()
                try:
                    if action == "approve":
                        obj.approve(request.user, note=note)
                        self.message_user(request, "CSA berhasil disetujui.", messages.SUCCESS)
                    elif action == "reject":
                        obj.reject(request.user, note=note)
                        self.message_user(request, "CSA dikembalikan kepada Preparer untuk diperbaiki.", messages.WARNING)
                    else:
                        raise ValidationError("Aksi review tidak dikenali.")
                except ValidationError as exc:
                    self.message_user(request, str(exc), messages.ERROR)
                else:
                    return HttpResponseRedirect(reverse("risk_admin:icofr_csaassessment_changelist"))
            obj.refresh_from_db()

        context = {
            **self.admin_site.each_context(request),
            "title": f"Review CSA — {obj.work_item.entry.control.reference}",
            "opts": self.model._meta,
            "original": obj,
            "assessment": obj,
            "entry": obj.work_item.entry,
            "samples": obj.samples.all(),
            "general_evidences": obj.evidences.filter(sample__isnull=True),
            "review_logs": obj.review_logs.all(),
            "can_decide": self._can_review(request, obj) and obj.status == CSAAssessment.Status.SUBMITTED,
        }
        return TemplateResponse(request, "admin/icofr/csaassessment/review.html", context)

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related(
            "work_item__entry__rcm_set", "work_item__preparer_user", "work_item__reviewer_user"
        )
        if _is_icofr_admin(request.user):
            return qs
        return qs.filter(Q(work_item__preparer_user=request.user) | Q(work_item__reviewer_user=request.user))

    def has_change_permission(self, request, obj=None):
        base = super().has_change_permission(request, obj=obj)
        if not base or obj is None:
            return base
        # Setelah dikirim, isi CSA dibekukan untuk seluruh role. Reviewer mengambil
        # keputusan melalui halaman Review CSA khusus.
        if obj.status in {CSAAssessment.Status.SUBMITTED, CSAAssessment.Status.APPROVED}:
            return False
        if _is_icofr_admin(request.user):
            return True
        return (
            obj.work_item.preparer_user_id == request.user.pk
            and obj.status in {CSAAssessment.Status.READY, CSAAssessment.Status.DRAFT, CSAAssessment.Status.REJECTED}
        )

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields

    def response_change(self, request, obj):
        is_preparer = obj.work_item.preparer_user_id == request.user.pk or request.user.is_superuser
        if "_save_draft" in request.POST:
            if not is_preparer:
                self.message_user(request, "Hanya Control Preparer yang dapat menyimpan draft CSA.", messages.ERROR)
            elif obj.status == CSAAssessment.Status.READY:
                obj.status = CSAAssessment.Status.DRAFT
                obj.save(update_fields=("status", "updated_at"))
                obj.work_item.status = ICoFRWorkItem.Status.DRAFT
                obj.work_item.save(update_fields=("status", "updated_at"))
                self.message_user(request, "Draft CSA berhasil disimpan.", messages.SUCCESS)
            else:
                # Status REJECTED sengaja dipertahankan agar pengiriman berikutnya tercatat sebagai RESUBMIT.
                self.message_user(request, "Perubahan CSA berhasil disimpan.", messages.SUCCESS)
            return HttpResponseRedirect(reverse("risk_admin:icofr_csaassessment_change", args=[obj.pk]))

        if "_submit_csa" in request.POST:
            if not is_preparer:
                self.message_user(request, "Hanya Control Preparer yang dapat mengirim CSA.", messages.ERROR)
            else:
                try:
                    obj.submit(user=request.user)
                except ValidationError as exc:
                    self.message_user(request, str(exc), messages.ERROR)
                else:
                    self.message_user(request, "CSA berhasil dikirim ke Control Reviewer.", messages.SUCCESS)
                    return HttpResponseRedirect(reverse("risk_admin:icofr_csaassessment_changelist"))
        return super().response_change(request, obj)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "ineffectiveness_category" and getattr(request, "_icofr_csa_obj", None):
            obj = request._icofr_csa_obj
            kwargs["queryset"] = CSAIneffectivenessCategory.objects.filter(
                rcm_type=obj.work_item.entry.rcm_set.rcm_type,
                is_active=True,
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        editable_statuses = {CSAAssessment.Status.READY, CSAAssessment.Status.DRAFT, CSAAssessment.Status.REJECTED}
        is_preparer = bool(
            obj
            and (obj.work_item.preparer_user_id == request.user.pk or request.user.is_superuser)
        )
        context["icofr_can_edit"] = bool(obj and is_preparer and obj.status in editable_statuses)
        context["icofr_can_submit"] = context["icofr_can_edit"]
        context["icofr_rejection_note"] = obj.reviewer_note if obj and obj.status == CSAAssessment.Status.REJECTED else ""
        if obj:
            entry = obj.work_item.entry
            context["icofr_entry"] = entry
            context["icofr_attributes"] = entry.control_attributes.all().order_by("sequence", "id")
            context["icofr_documents"] = entry.supporting_documents.all().order_by("sequence", "id")
            context["icofr_review_url"] = reverse("risk_admin:icofr_csa_review", args=[obj.pk])
        return super().render_change_form(request, context, add, change, form_url, obj)

    def get_form(self, request, obj=None, **kwargs):
        request._icofr_csa_obj = obj
        return super().get_form(request, obj, **kwargs)

    def save_model(self, request, obj, form, change):
        if obj.result != CSAAssessment.Result.INEFFECTIVE:
            obj.ineffectiveness_category = None
            obj.ineffectiveness_explanation = ""
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, CSAEvidence) and not instance.uploaded_by_id:
                instance.uploaded_by = request.user
            instance.save()
            if isinstance(instance, CSASample):
                ensure_sample_attributes(instance)
        for obj in formset.deleted_objects:
            obj.delete()
        formset.save_m2m()

    @admin.display(description="RCM")
    def rcm_type(self, obj):
        return obj.work_item.entry.rcm_set.rcm_type

    @admin.display(description="Preparer")
    def preparer(self, obj):
        return obj.work_item.preparer_user

    @admin.display(description="Reviewer")
    def reviewer(self, obj):
        return obj.work_item.reviewer_user

    @admin.action(description="Kirim CSA terpilih ke Reviewer")
    def submit_selected(self, request, queryset):
        count = 0
        for obj in queryset:
            if obj.work_item.preparer_user_id != request.user.pk and not request.user.is_superuser:
                continue
            try:
                obj.submit(user=request.user)
            except ValidationError as exc:
                self.message_user(request, f"{obj}: {exc}", messages.ERROR)
            else:
                count += 1
        if count:
            self.message_user(request, f"{count} CSA berhasil dikirim.", messages.SUCCESS)



class CSAAssessmentReviewLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "assessment", "round_number", "action", "actor", "note_short")
    list_filter = ("action", "round_number", "assessment__work_item__schedule__period__year")
    search_fields = (
        "assessment__work_item__entry__risk__reference",
        "assessment__work_item__entry__control__reference",
        "actor__username", "note",
    )
    readonly_fields = tuple(field.name for field in CSAAssessmentReviewLog._meta.fields)

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related(
            "assessment__work_item__preparer_user", "assessment__work_item__reviewer_user", "actor"
        )
        if _is_icofr_admin(request.user):
            return qs
        return qs.filter(
            Q(assessment__work_item__preparer_user=request.user)
            | Q(assessment__work_item__reviewer_user=request.user)
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    @admin.display(description="Catatan")
    def note_short(self, obj):
        return (obj.note[:80] + "…") if len(obj.note) > 80 else obj.note


class CSASampleAttributeResultInline(admin.TabularInline):
    model = CSASampleAttributeResult
    extra = 0


class CSAEvidenceSampleInline(admin.TabularInline):
    model = CSAEvidence
    fk_name = "sample"
    extra = 0
    exclude = ("assessment", "uploaded_by", "evidence_type")


class CSASampleAdmin(admin.ModelAdmin):
    list_display = ("assessment", "description", "transaction_date", "result", "attribute_health")
    list_filter = ("result", "assessment__work_item__schedule__rcm_set__rcm_type", "assessment__status")
    search_fields = ("description", "assessment__work_item__entry__risk__reference", "assessment__work_item__entry__control__reference")
    inlines = (CSASampleAttributeResultInline, CSAEvidenceSampleInline)

    def has_add_permission(self, request):
        # Sampel dibuat dari form CSA agar selalu terikat ke assessment/work item yang valid.
        return False

    def get_model_perms(self, request):
        # Menu Sampel CSA disembunyikan dari user bisnis; akses sampel dilakukan dari CSA Line 1.
        if not _is_icofr_admin(request.user):
            return {}
        return super().get_model_perms(request)

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("assessment__work_item__preparer_user", "assessment__work_item__reviewer_user")
        if _is_icofr_admin(request.user):
            return qs
        return qs.filter(
            Q(assessment__work_item__preparer_user=request.user)
            | Q(assessment__work_item__reviewer_user=request.user)
        )

    def has_change_permission(self, request, obj=None):
        base = super().has_change_permission(request, obj=obj)
        if not base or obj is None:
            return base
        if _is_icofr_admin(request.user):
            return True
        return (
            obj.assessment.work_item.preparer_user_id == request.user.pk
            and obj.assessment.status in {CSAAssessment.Status.READY, CSAAssessment.Status.DRAFT, CSAAssessment.Status.REJECTED}
        )

    def save_model(self, request, obj, form, change):
        obj.full_clean()
        super().save_model(request, obj, form, change)
        ensure_sample_attributes(obj)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, CSAEvidence):
                instance.assessment = form.instance.assessment
                instance.evidence_type = CSAEvidence.EvidenceType.SUPPORTING
                if not instance.uploaded_by_id:
                    instance.uploaded_by = request.user
            instance.save()
        for obj in formset.deleted_objects:
            obj.delete()
        formset.save_m2m()

    @admin.display(description="Atribut")
    def attribute_health(self, obj):
        total = obj.attribute_results.count()
        met = obj.attribute_results.filter(is_met=True).count()
        return f"{met}/{total}" if total else "-"


for model, model_admin in (
    (ICoFRPeriod, ICoFRPeriodAdmin),
    (RCMSet, RCMSetAdmin),
    (RCMRisk, RCMRiskAdmin),
    (RCMControl, RCMControlAdmin),
    (RCMEntry, RCMEntryAdmin),
    (RCMMapping, RCMMappingAdmin),
    (RCMImportBatch, RCMImportBatchAdmin),
    (ICoFRSchedule, ICoFRScheduleAdmin),
    (ICoFRDistributionBatch, ICoFRDistributionBatchAdmin),
    (ICoFRWorkItem, ICoFRWorkItemAdmin),
    (ICoFRQuestion, ICoFRQuestionAdmin),
    (QuestionnaireSubmission, QuestionnaireSubmissionAdmin),
    (CSAIneffectivenessCategory, CSAIneffectivenessCategoryAdmin),
    (CSAAssessment, CSAAssessmentAdmin),
    (CSAAssessmentReviewLog, CSAAssessmentReviewLogAdmin),
    (CSASample, CSASampleAdmin),
):
    try:
        risk_admin_site.register(model, model_admin)
    except admin.sites.AlreadyRegistered:
        pass
