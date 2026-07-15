from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from datetime import timedelta

from risk.models import AppSetting

from .models import AwarenessAnswer, AwarenessAttempt, AwarenessCampaign


def _active_campaigns():
    today = timezone.localdate()
    return AwarenessCampaign.objects.filter(
        is_active=True,
        start_date__lte=today,
        end_date__gte=today,
    ).order_by("-start_date", "title")


def _template_context(**context):
    return {"app_setting": AppSetting.get_solo(), **context}


def _user_display_name(user):
    full_name = user.get_full_name().strip()
    return full_name or user.get_username()


def _user_group_label(user):
    group_names = [group.name for group in user.groups.all()]
    return ", ".join(group_names) if group_names else "-"


def _campaign_status(campaign, user):
    attempts = campaign.attempts.filter(user=user).order_by("-attempt_number", "-started_at")
    latest = attempts.first()
    passed = attempts.filter(status=AwarenessAttempt.STATUS_PASSED).exists()
    in_progress = attempts.filter(status=AwarenessAttempt.STATUS_IN_PROGRESS).first()
    if in_progress and in_progress.is_expired():
        in_progress = None
    max_attempts = campaign.max_attempts
    attempt_count = attempts.count()
    attempt_exhausted = bool(max_attempts and attempt_count >= max_attempts and not passed and not in_progress)

    if passed:
        label = "lulus"
    elif in_progress:
        label = "sedang dikerjakan"
    elif attempt_exhausted:
        label = "attempt habis"
    elif latest and latest.status == AwarenessAttempt.STATUS_FAILED:
        label = "belum lulus"
    else:
        label = "belum dikerjakan"

    return {
        "label": label,
        "latest": latest,
        "in_progress": in_progress,
        "attempt_count": attempt_count,
        "attempt_exhausted": attempt_exhausted,
        "passed": passed,
    }


@login_required
def campaign_list(request):
    rows = []
    for campaign in _active_campaigns().prefetch_related("questions"):
        status = _campaign_status(campaign, request.user)
        rows.append({
            "campaign": campaign,
            "status": status,
            "question_count": campaign.question_count,
        })
    return render(request, "awareness/campaign_list.html", _template_context(rows=rows))


@login_required
def campaign_participants(request, campaign_id):
    campaign = get_object_or_404(AwarenessCampaign, pk=campaign_id)
    attempts = (
        campaign.attempts
        .filter(status__in=[
            AwarenessAttempt.STATUS_SUBMITTED,
            AwarenessAttempt.STATUS_PASSED,
            AwarenessAttempt.STATUS_FAILED,
            AwarenessAttempt.STATUS_EXPIRED,
        ])
        .select_related("user")
        .prefetch_related("user__groups")
        .order_by("user__first_name", "user__last_name", "user__username", "-submitted_at", "-started_at")
    )
    seen_users = set()
    rows = []
    for attempt in attempts:
        if attempt.user_id in seen_users:
            continue
        seen_users.add(attempt.user_id)
        rows.append({
            "awareness": _user_display_name(attempt.user),
            "group": _user_group_label(attempt.user),
        })
    rows.sort(key=lambda row: (row["group"].casefold(), row["awareness"].casefold()))
    return render(
        request,
        "awareness/participants.html",
        _template_context(campaign=campaign, rows=rows),
    )


@login_required
def campaign_material(request, campaign_id):
    campaign = get_object_or_404(AwarenessCampaign, pk=campaign_id)
    if not campaign.is_currently_active():
        messages.error(request, "Program awareness tidak aktif atau sudah di luar periode.")
        return redirect("awareness:campaign_list")

    status = _campaign_status(campaign, request.user)
    if status["passed"]:
        messages.info(request, "Anda sudah lulus program awareness ini.")
        return redirect("awareness:attempt_result", attempt_id=status["latest"].pk)
    if status["in_progress"]:
        return redirect("awareness:quiz_attempt", attempt_id=status["in_progress"].pk)
    if status["attempt_exhausted"]:
        messages.error(request, "Batas attempt untuk program awareness ini sudah habis.")
        return redirect("awareness:campaign_list")

    return render(
        request,
        "awareness/material.html",
        _template_context(campaign=campaign, question_count=campaign.question_count),
    )


@login_required
@require_POST
def start_campaign(request, campaign_id):
    campaign = get_object_or_404(AwarenessCampaign, pk=campaign_id)
    if not campaign.is_currently_active():
        messages.error(request, "Program awareness tidak aktif atau sudah di luar periode.")
        return redirect("awareness:campaign_list")

    if not campaign.questions.filter(is_active=True).exists():
        messages.error(request, "Program awareness belum memiliki soal aktif.")
        return redirect("awareness:campaign_list")

    in_progress = AwarenessAttempt.objects.filter(
        campaign=campaign,
        user=request.user,
        status=AwarenessAttempt.STATUS_IN_PROGRESS,
    ).order_by("-started_at").first()
    if in_progress:
        if in_progress.mark_expired_if_needed():
            messages.warning(request, "Attempt sebelumnya sudah melewati batas waktu.")
        else:
            return redirect("awareness:quiz_attempt", attempt_id=in_progress.pk)

    with transaction.atomic():
        existing_attempts = AwarenessAttempt.objects.select_for_update().filter(
            campaign=campaign,
            user=request.user,
        )
        attempt_count = existing_attempts.count()
        if campaign.max_attempts and attempt_count >= campaign.max_attempts:
            messages.error(request, "Batas attempt untuk program awareness ini sudah habis.")
            return redirect("awareness:campaign_list")

        attempt = AwarenessAttempt.objects.create(
            campaign=campaign,
            user=request.user,
            attempt_number=attempt_count + 1,
            total_questions=campaign.question_count,
        )
    return redirect("awareness:quiz_attempt", attempt_id=attempt.pk)


def _get_user_attempt(request, attempt_id):
    attempt = get_object_or_404(
        AwarenessAttempt.objects.select_related("campaign", "user"),
        pk=attempt_id,
    )
    if attempt.user_id != request.user.id:
        raise PermissionDenied
    return attempt


@login_required
def quiz_attempt(request, attempt_id):
    attempt = _get_user_attempt(request, attempt_id)
    if attempt.mark_expired_if_needed():
        messages.error(request, "Waktu pengerjaan sudah habis.")
        return redirect("awareness:attempt_result", attempt_id=attempt.pk)
    if attempt.status != AwarenessAttempt.STATUS_IN_PROGRESS:
        return redirect("awareness:attempt_result", attempt_id=attempt.pk)

    questions = list(attempt.campaign.questions.filter(is_active=True).order_by("order", "id"))
    answers = {
        answer.question_id: answer.selected_answer
        for answer in attempt.answers.all()
    }
    deadline = None
    if attempt.campaign.time_limit_minutes:
        deadline = attempt.started_at + timedelta(minutes=attempt.campaign.time_limit_minutes)

    return render(
        request,
        "awareness/quiz.html",
        _template_context(
            attempt=attempt,
            campaign=attempt.campaign,
            questions=questions,
            answers=answers,
            deadline=deadline,
        ),
    )


@login_required
@require_POST
def submit_attempt(request, attempt_id):
    attempt = _get_user_attempt(request, attempt_id)
    if attempt.status != AwarenessAttempt.STATUS_IN_PROGRESS:
        messages.warning(request, "Attempt ini sudah disubmit.")
        return redirect("awareness:attempt_result", attempt_id=attempt.pk)
    if attempt.mark_expired_if_needed():
        messages.error(request, "Waktu pengerjaan sudah habis.")
        return redirect("awareness:attempt_result", attempt_id=attempt.pk)

    questions = list(attempt.campaign.questions.filter(is_active=True).order_by("order", "id"))
    missing = []
    for question in questions:
        if request.POST.get(f"question_{question.pk}") not in {"A", "B", "C", "D"}:
            missing.append(question.pk)
    if missing:
        messages.error(request, "Semua pertanyaan wajib dijawab sebelum submit.")
        return redirect("awareness:quiz_attempt", attempt_id=attempt.pk)

    with transaction.atomic():
        for question in questions:
            selected = request.POST.get(f"question_{question.pk}")
            AwarenessAnswer.objects.update_or_create(
                attempt=attempt,
                question=question,
                defaults={
                    "selected_answer": selected,
                    "is_correct": selected == question.correct_answer,
                },
            )
        attempt.calculate_result()

    messages.success(request, "Jawaban berhasil disubmit.")
    return redirect("awareness:attempt_result", attempt_id=attempt.pk)


@login_required
def attempt_result(request, attempt_id):
    attempt = _get_user_attempt(request, attempt_id)
    if attempt.status == AwarenessAttempt.STATUS_IN_PROGRESS and attempt.user_id == request.user.id:
        return redirect("awareness:quiz_attempt", attempt_id=attempt.pk)

    answers = attempt.answers.select_related("question").order_by("question__order", "question_id")
    return render(
        request,
        "awareness/result.html",
        _template_context(attempt=attempt, campaign=attempt.campaign, answers=answers),
    )
