from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .models import ReAssessment
from .workflow import ReAssessmentWorkflowService


@login_required
@require_POST
def submit_reassessment(request, pk):
    obj = get_object_or_404(ReAssessment, pk=pk)
    note = request.POST.get("note", "")
    try:
        ReAssessmentWorkflowService.submit(obj, request.user, note=note)
        messages.success(request, "ReAssessment berhasil di-submit.")
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
    return redirect(request.META.get("HTTP_REFERER", "/admin/"))

@login_required
@require_POST
def start_rkm_review(request, pk):
    obj = get_object_or_404(ReAssessment, pk=pk)
    note = request.POST.get("note", "").strip()

    try:
        ReAssessmentWorkflowService.start_rkm_review(obj, request.user, note=note)
        messages.success(request, "ReAssessment masuk tahap review RKM.")
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
    except Exception as e:
        messages.error(request, f"Error start RKM review: {e}")

    return redirect(request.META.get("HTTP_REFERER", "/admin/"))


@login_required
@require_POST
def start_km_review(request, pk):
    obj = get_object_or_404(ReAssessment, pk=pk)
    note = request.POST.get("note", "").strip()

    try:
        ReAssessmentWorkflowService.start_km_review(obj, request.user, note=note)
        messages.success(request, "ReAssessment masuk tahap review KM.")
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
    except Exception as e:
        messages.error(request, f"Error start KM review: {e}")

    return redirect(request.META.get("HTTP_REFERER", "/admin/"))


@login_required
@require_POST
def approve_rkm(request, pk):
    obj = get_object_or_404(ReAssessment, pk=pk)
    note = request.POST.get("note", "")
    try:
        ReAssessmentWorkflowService.approve_rkm(obj, request.user, note=note)
        messages.success(request, "ReAssessment berhasil di-approve pada level RKM.")
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
    return redirect(request.META.get("HTTP_REFERER", "/admin/"))


@login_required
@require_POST
def reject_rkm(request, pk):
    obj = get_object_or_404(ReAssessment, pk=pk)
    note = request.POST.get("note", "")
    try:
        ReAssessmentWorkflowService.reject_rkm(obj, request.user, note=note)
        messages.success(request, "ReAssessment dikembalikan ke unit.")
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
    return redirect(request.META.get("HTTP_REFERER", "/admin/"))


@login_required
@require_POST
def approve_km(request, pk):
    obj = get_object_or_404(ReAssessment, pk=pk)
    note = request.POST.get("note", "")
    escalate = request.POST.get("escalate") == "1"
    try:
        ReAssessmentWorkflowService.approve_km(obj, request.user, note=note, escalate=escalate)
        messages.success(request, "ReAssessment berhasil di-approve pada level KM.")
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
    return redirect(request.META.get("HTTP_REFERER", "/admin/"))


@login_required
@require_POST
def reject_km(request, pk):
    obj = get_object_or_404(ReAssessment, pk=pk)
    note = request.POST.get("note", "")
    try:
        ReAssessmentWorkflowService.reject_km(obj, request.user, note=note)
        messages.success(request, "ReAssessment ditolak pada level KM.")
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
    return redirect(request.META.get("HTTP_REFERER", "/admin/"))


@login_required
@require_POST
def lock_reassessment(request, pk):
    obj = get_object_or_404(ReAssessment, pk=pk)
    note = request.POST.get("note", "")
    try:
        ReAssessmentWorkflowService.lock(obj, request.user, note=note)
        messages.success(request, "ReAssessment berhasil di-lock.")
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
    return redirect(request.META.get("HTTP_REFERER", "/admin/"))