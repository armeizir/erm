from django.contrib import (
    admin,
    messages,
)
from django.contrib.admin.sites import AlreadyRegistered
from django.core.exceptions import (
    PermissionDenied,
    ValidationError,
)
from django.db.models import Q
from django.http import HttpResponseNotAllowed
from django.shortcuts import (
    get_object_or_404,
    redirect,
)
from django.template.response import TemplateResponse
from django.urls import (
    path,
    reverse,
)
from django.utils.html import format_html

from risk.access_policy import (
    organizational_groups_for_user,
)
from risk.forms_treatment_change import (
    RiskTreatmentChangeProposalForm,
)
from risk.models import (
    ReAssessmentItem,
    RiskTreatmentChangeRequest,
)
from risk.services.permissions import (
    is_risk_admin,
)
from risk.services.treatment_change import (
    approve_change_request,
    create_change_request,
    reject_change_request,
    request_revision,
    start_review,
    submit_change_request,
)
from riskproject.admin_site import risk_admin_site


OPEN_STATUSES = {
    RiskTreatmentChangeRequest.STATUS_DRAFT,
    RiskTreatmentChangeRequest.STATUS_SUBMITTED,
    RiskTreatmentChangeRequest.STATUS_UNDER_REVIEW,
    RiskTreatmentChangeRequest.STATUS_REVISION,
}


FIELD_LABELS = {
    "opsi_perlakuan_risiko_id":
        "Opsi Perlakuan Risiko",

    "jenis_rencana_perlakuan_risiko_ids":
        "Jenis Rencana Perlakuan",

    "rencana_perlakuan_risiko":
        "Rencana Perlakuan Risiko",

    "output_perlakuan_risiko":
        "Output Perlakuan Risiko",

    "biaya_perlakuan_risiko":
        "Biaya Perlakuan Risiko",

    "pos_anggaran_id":
        "Pos Anggaran",

    "prk":
        "PRK",

    "jenis_program_dalam_rkap_id":
        "Jenis Program Dalam RKAP",

    "pic":
        "PIC",

    "pic_organization_unit_id":
        "PIC Organisasi",

    "pic_user_assignment_id":
        "PIC Pelaksana",

    **{
        f"timeline_{month}":
            f"Timeline Bulan {month}"
        for month in range(1, 13)
    },
}


def accessible_items(user):
    qs = (
        ReAssessmentItem.objects
        .filter(is_active=True)
        .select_related(
            "summary",
            "unit_bisnis",
            "km_item",
            "pic_organization_unit",
            "pic_user_assignment",
        )
    )

    if user.is_superuser or is_risk_admin(user):
        return qs

    groups = organizational_groups_for_user(
        user
    )

    return qs.filter(
        summary__unit_bisnis__in=groups
    )


def can_access_item(user, item):
    return (
        accessible_items(user)
        .filter(pk=item.pk)
        .exists()
    )


def display_value(item, key, value):
    if value in (None, ""):
        return "—"

    if key.startswith("timeline_"):
        return "Ya" if int(value) == 1 else "Tidak"

    if key == (
        "jenis_rencana_perlakuan_risiko_ids"
    ):
        model = (
            item
            .jenis_rencana_perlakuan_risiko
            .model
        )

        labels = list(
            model.objects
            .filter(pk__in=value or [])
            .order_by("pk")
            .values_list(
                "nama",
                flat=True,
            )
        )

        if not labels:
            labels = [
                str(obj)
                for obj in (
                    model.objects
                    .filter(pk__in=value or [])
                    .order_by("pk")
                )
            ]

        return ", ".join(labels) or "—"

    if key.endswith("_id"):
        field_name = key[:-3]

        try:
            field = item._meta.get_field(
                field_name
            )
        except Exception:
            return str(value)

        related_model = (
            field.remote_field.model
        )

        obj = (
            related_model.objects
            .filter(pk=value)
            .first()
        )

        return str(obj) if obj else str(value)

    return str(value)


class RiskTreatmentChangeRequestAdmin(
    admin.ModelAdmin
):
    change_list_template = (
        "admin/risk/treatment_change/"
        "change_list.html"
    )

    list_display = (
        "id",
        "risk_identity",
        "version",
        "status_badge",
        "created_by",
        "requested_at",
        "reviewed_by",
        "approved_by",
        "detail_button",
    )

    list_filter = (
        "status",
        "reassessment_item__summary__tahun",
        "reassessment_item__summary__unit_bisnis",
    )

    search_fields = (
        "reassessment_item__summary__judul",
        "reassessment_item__rencana_perlakuan_risiko",
        "alasan_perubahan",
    )

    readonly_fields = tuple(
        field.name
        for field in (
            RiskTreatmentChangeRequest
            ._meta
            .fields
        )
    )

    def has_module_permission(self, request):
        user = request.user

        return bool(
            user.is_active
            and user.is_staff
            and (
                user.is_superuser
                or is_risk_admin(user)
                or bool(
                    organizational_groups_for_user(
                        user
                    )
                )
            )
        )

    def has_view_permission(
        self,
        request,
        obj=None,
    ):
        if not self.has_module_permission(
            request
        ):
            return False

        if obj is None:
            return True

        return can_access_item(
            request.user,
            obj.reassessment_item,
        )

    def has_add_permission(
        self,
        request,
    ):
        return False

    def has_change_permission(
        self,
        request,
        obj=None,
    ):
        # Editing langsung Change Request dilarang.
        # Semua perubahan melalui workflow view.
        return False

    def has_delete_permission(
        self,
        request,
        obj=None,
    ):
        return False

    def get_queryset(self, request):
        qs = (
            super()
            .get_queryset(request)
            .select_related(
                "reassessment_item",
                "reassessment_item__summary",
                "created_by",
                "requested_by",
                "reviewed_by",
                "approved_by",
            )
        )

        if (
            request.user.is_superuser
            or is_risk_admin(request.user)
        ):
            return qs

        return qs.filter(
            reassessment_item__in=(
                accessible_items(
                    request.user
                )
            )
        )

    @admin.display(
        description="Risiko",
    )
    def risk_identity(self, obj):
        item = obj.reassessment_item

        return (
            f"{item.summary} | "
            f"Item {item.no_item} | "
            f"Risiko {item.no_risiko}"
        )

    @admin.display(
        description="Status",
    )
    def status_badge(self, obj):
        colors = {
            "draft": "#64748b",
            "submitted": "#2563eb",
            "under_review": "#7c3aed",
            "revision": "#d97706",
            "rejected": "#b91c1c",
            "approved": "#15803d",
        }

        return format_html(
            '<strong style="color:{}">{}</strong>',
            colors.get(
                obj.status,
                "#334155",
            ),
            obj.get_status_display(),
        )

    @admin.display(
        description="Aksi",
    )
    def detail_button(self, obj):
        url = reverse(
            (
                f"{self.admin_site.name}:"
                "risk_risktreatmentchangerequest_detail"
            ),
            args=[obj.pk],
        )

        return format_html(
            '<a class="button" href="{}">'
            "Lihat"
            "</a>",
            url,
        )

    def get_urls(self):
        custom = [
            path(
                "choose/",
                self.admin_site.admin_view(
                    self.choose_view
                ),
                name=(
                    "risk_risktreatmentchangerequest_choose"
                ),
            ),

            path(
                "create/<int:item_id>/",
                self.admin_site.admin_view(
                    self.create_view
                ),
                name=(
                    "risk_risktreatmentchangerequest_create"
                ),
            ),

            path(
                "detail/<int:change_id>/",
                self.admin_site.admin_view(
                    self.detail_view
                ),
                name=(
                    "risk_risktreatmentchangerequest_detail"
                ),
            ),

            path(
                "detail/<int:change_id>/submit/",
                self.admin_site.admin_view(
                    self.submit_view
                ),
                name=(
                    "risk_risktreatmentchangerequest_submit"
                ),
            ),

            path(
                "detail/<int:change_id>/review/",
                self.admin_site.admin_view(
                    self.review_view
                ),
                name=(
                    "risk_risktreatmentchangerequest_review"
                ),
            ),

            path(
                "detail/<int:change_id>/revision/",
                self.admin_site.admin_view(
                    self.revision_view
                ),
                name=(
                    "risk_risktreatmentchangerequest_revision"
                ),
            ),

            path(
                "detail/<int:change_id>/reject/",
                self.admin_site.admin_view(
                    self.reject_view
                ),
                name=(
                    "risk_risktreatmentchangerequest_reject"
                ),
            ),

            path(
                "detail/<int:change_id>/approve/",
                self.admin_site.admin_view(
                    self.approve_view
                ),
                name=(
                    "risk_risktreatmentchangerequest_approve"
                ),
            ),
        ]

        return custom + super().get_urls()

    def changelist_view(
        self,
        request,
        extra_context=None,
    ):
        extra_context = (
            extra_context or {}
        )

        extra_context[
            "treatment_choose_url"
        ] = reverse(
            (
                f"{self.admin_site.name}:"
                "risk_risktreatmentchangerequest_choose"
            )
        )

        return super().changelist_view(
            request,
            extra_context=extra_context,
        )

    def choose_view(self, request):
        if not self.has_module_permission(
            request
        ):
            raise PermissionDenied

        qs = (
            accessible_items(request.user)
            .prefetch_related(
                "treatment_change_requests"
            )
            .order_by(
                "summary__judul",
                "no_item",
                "no_risiko",
                "pk",
            )
        )

        q = (
            request.GET.get("q", "")
            .strip()
        )

        if q:
            qs = qs.filter(
                Q(
                    summary__judul__icontains=q
                )
                | Q(
                    rencana_perlakuan_risiko__icontains=q
                )
                | Q(
                    output_perlakuan_risiko__icontains=q
                )
            )

        rows = []

        for item in qs[:500]:
            open_change = next(
                (
                    change
                    for change in (
                        item
                        .treatment_change_requests
                        .all()
                    )
                    if change.status
                    in OPEN_STATUSES
                ),
                None,
            )

            if open_change:
                url = reverse(
                    (
                        f"{self.admin_site.name}:"
                        "risk_risktreatmentchangerequest_detail"
                    ),
                    args=[open_change.pk],
                )

                label = (
                    "Lihat Usulan Aktif"
                )
            else:
                url = reverse(
                    (
                        f"{self.admin_site.name}:"
                        "risk_risktreatmentchangerequest_create"
                    ),
                    args=[item.pk],
                )

                label = (
                    "Ajukan Perubahan"
                )

            rows.append(
                {
                    "item": item,
                    "open_change":
                        open_change,
                    "url": url,
                    "label": label,
                }
            )

        context = {
            **self.admin_site.each_context(
                request
            ),
            "opts": self.model._meta,
            "title": (
                "Pilih Rencana Perlakuan Risiko"
            ),
            "rows": rows,
            "q": q,
        }

        return TemplateResponse(
            request,
            (
                "admin/risk/"
                "treatment_change/"
                "choose.html"
            ),
            context,
        )

    def create_view(
        self,
        request,
        item_id,
    ):
        item = get_object_or_404(
            accessible_items(request.user),
            pk=item_id,
        )

        existing_open = (
            RiskTreatmentChangeRequest
            .objects
            .filter(
                reassessment_item=item,
                status__in=OPEN_STATUSES,
            )
            .first()
        )

        if existing_open:
            messages.warning(
                request,
                (
                    "Masih ada usulan perubahan "
                    "aktif untuk treatment ini."
                ),
            )

            return redirect(
                (
                    f"{self.admin_site.name}:"
                    "risk_risktreatmentchangerequest_detail"
                ),
                existing_open.pk,
            )

        form = RiskTreatmentChangeProposalForm(
            request.POST or None,
            instance=item,
            user=request.user,
        )

        if (
            request.method == "POST"
            and form.is_valid()
        ):
            try:
                change = create_change_request(
                    reassessment_item=item,
                    changes=(
                        form.proposed_changes()
                    ),
                    alasan_perubahan=(
                        form.cleaned_data[
                            "alasan_perubahan"
                        ]
                    ),
                    dampak_perubahan=(
                        form.cleaned_data.get(
                            "dampak_perubahan",
                            "",
                        )
                    ),
                    actor=request.user,
                )

                if "_submit" in request.POST:
                    change = (
                        submit_change_request(
                            change_request=change,
                            actor=request.user,
                        )
                    )

                messages.success(
                    request,
                    (
                        "Usulan perubahan "
                        "berhasil disimpan."
                    ),
                )

                return redirect(
                    (
                        f"{self.admin_site.name}:"
                        "risk_risktreatmentchangerequest_detail"
                    ),
                    change.pk,
                )

            except ValidationError as exc:
                form.add_error(
                    None,
                    exc,
                )

        context = {
            **self.admin_site.each_context(
                request
            ),
            "opts": self.model._meta,
            "title": (
                "Ajukan Perubahan "
                "Rencana Perlakuan Risiko"
            ),
            "item": item,
            "form": form,
        }

        return TemplateResponse(
            request,
            (
                "admin/risk/"
                "treatment_change/"
                "create.html"
            ),
            context,
        )

    def _change(self, request, change_id):
        change = get_object_or_404(
            self.get_queryset(request),
            pk=change_id,
        )

        if not can_access_item(
            request.user,
            change.reassessment_item,
        ):
            raise PermissionDenied

        return change

    def _can_submit(
        self,
        user,
        change,
    ):
        return bool(
            user.is_superuser
            or is_risk_admin(user)
            or change.created_by_id
            == user.pk
        )

    def _can_review(
        self,
        user,
        change,
    ):
        summary = (
            change
            .reassessment_item
            .summary
        )

        return bool(
            user.is_superuser
            or is_risk_admin(user)
            or summary.reviewed_by_id
            == user.pk
        )

    def _can_approve(
        self,
        user,
        change,
    ):
        summary = (
            change
            .reassessment_item
            .summary
        )

        return bool(
            user.is_superuser
            or is_risk_admin(user)
            or summary.approved_by_id
            == user.pk
        )

    def detail_view(
        self,
        request,
        change_id,
    ):
        change = self._change(
            request,
            change_id,
        )

        item = change.reassessment_item

        comparison = []

        for key, proposed in (
            change
            .proposed_changes
            .items()
        ):
            before = (
                change
                .before_snapshot
                .get(key)
            )

            comparison.append(
                {
                    "field": (
                        FIELD_LABELS.get(
                            key,
                            key,
                        )
                    ),
                    "before":
                        display_value(
                            item,
                            key,
                            before,
                        ),
                    "after":
                        display_value(
                            item,
                            key,
                            proposed,
                        ),
                }
            )

        context = {
            **self.admin_site.each_context(
                request
            ),
            "opts": self.model._meta,
            "title": (
                "Detail Usulan Perubahan "
                "Rencana Perlakuan Risiko"
            ),
            "change": change,
            "item": item,
            "comparison": comparison,

            "can_submit": (
                self._can_submit(
                    request.user,
                    change,
                )
                and change.status
                in {
                    "draft",
                    "revision",
                }
            ),

            "can_review": (
                self._can_review(
                    request.user,
                    change,
                )
                and change.status
                == "submitted"
            ),

            "can_decide_review": (
                self._can_review(
                    request.user,
                    change,
                )
                and change.status
                == "under_review"
            ),

            "can_approve": (
                self._can_approve(
                    request.user,
                    change,
                )
                and change.status
                == "under_review"
            ),
        }

        return TemplateResponse(
            request,
            (
                "admin/risk/"
                "treatment_change/"
                "detail.html"
            ),
            context,
        )

    def _post_only(self, request):
        if request.method != "POST":
            return HttpResponseNotAllowed(
                ["POST"]
            )
        return None

    def submit_view(
        self,
        request,
        change_id,
    ):
        invalid = self._post_only(request)

        if invalid:
            return invalid

        change = self._change(
            request,
            change_id,
        )

        if not self._can_submit(
            request.user,
            change,
        ):
            raise PermissionDenied

        try:
            submit_change_request(
                change_request=change,
                actor=request.user,
            )

            messages.success(
                request,
                "Usulan berhasil diajukan.",
            )

        except ValidationError as exc:
            messages.error(
                request,
                str(exc),
            )

        return redirect(
            (
                f"{self.admin_site.name}:"
                "risk_risktreatmentchangerequest_detail"
            ),
            change.pk,
        )

    def review_view(
        self,
        request,
        change_id,
    ):
        invalid = self._post_only(request)

        if invalid:
            return invalid

        change = self._change(
            request,
            change_id,
        )

        if not self._can_review(
            request.user,
            change,
        ):
            raise PermissionDenied

        try:
            start_review(
                change_request=change,
                actor=request.user,
            )

            messages.success(
                request,
                "Usulan masuk tahap review.",
            )

        except ValidationError as exc:
            messages.error(
                request,
                str(exc),
            )

        return redirect(
            (
                f"{self.admin_site.name}:"
                "risk_risktreatmentchangerequest_detail"
            ),
            change.pk,
        )

    def revision_view(
        self,
        request,
        change_id,
    ):
        invalid = self._post_only(request)

        if invalid:
            return invalid

        change = self._change(
            request,
            change_id,
        )

        if not self._can_review(
            request.user,
            change,
        ):
            raise PermissionDenied

        try:
            request_revision(
                change_request=change,
                actor=request.user,
                reviewer_note=(
                    request.POST.get(
                        "reviewer_note",
                        "",
                    )
                ),
            )

            messages.warning(
                request,
                (
                    "Usulan dikembalikan "
                    "untuk revisi."
                ),
            )

        except ValidationError as exc:
            messages.error(
                request,
                str(exc),
            )

        return redirect(
            (
                f"{self.admin_site.name}:"
                "risk_risktreatmentchangerequest_detail"
            ),
            change.pk,
        )

    def reject_view(
        self,
        request,
        change_id,
    ):
        invalid = self._post_only(request)

        if invalid:
            return invalid

        change = self._change(
            request,
            change_id,
        )

        if not self._can_review(
            request.user,
            change,
        ):
            raise PermissionDenied

        try:
            reject_change_request(
                change_request=change,
                actor=request.user,
                reviewer_note=(
                    request.POST.get(
                        "reviewer_note",
                        "",
                    )
                ),
            )

            messages.warning(
                request,
                "Usulan ditolak.",
            )

        except ValidationError as exc:
            messages.error(
                request,
                str(exc),
            )

        return redirect(
            (
                f"{self.admin_site.name}:"
                "risk_risktreatmentchangerequest_detail"
            ),
            change.pk,
        )

    def approve_view(
        self,
        request,
        change_id,
    ):
        invalid = self._post_only(request)

        if invalid:
            return invalid

        change = self._change(
            request,
            change_id,
        )

        if not self._can_approve(
            request.user,
            change,
        ):
            raise PermissionDenied

        try:
            approve_change_request(
                change_request=change,
                actor=request.user,
                reviewer_note=(
                    request.POST.get(
                        "reviewer_note",
                        "",
                    )
                ),
            )

            messages.success(
                request,
                (
                    "Perubahan disetujui dan "
                    "diterapkan ke Profil Risiko."
                ),
            )

        except ValidationError as exc:
            messages.error(
                request,
                str(exc),
            )

        return redirect(
            (
                f"{self.admin_site.name}:"
                "risk_risktreatmentchangerequest_detail"
            ),
            change.pk,
        )


def register_treatment_change_admin():
    for site in (
        admin.site,
        risk_admin_site,
    ):
        try:
            site.register(
                RiskTreatmentChangeRequest,
                RiskTreatmentChangeRequestAdmin,
            )
        except AlreadyRegistered:
            pass


register_treatment_change_admin()
