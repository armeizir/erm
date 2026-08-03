from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from masterdata.models import PeriodeLaporan
from risk.models import ProfilRisikoKorporatItem

from .models import (
    MonteCarloMetricHistory,
    MultiMetricAIInsightKorporat,
    MultiMetricMonteCarloResult,
    RiskMetric,
)


MONTHS = (
    (1, "Jan"), (2, "Feb"), (3, "Mar"), (4, "Apr"),
    (5, "Mei"), (6, "Jun"), (7, "Jul"), (8, "Agu"),
    (9, "Sep"), (10, "Okt"), (11, "Nov"), (12, "Des"),
)
MINIMUM_HISTORY_POINTS = 3


@dataclass(frozen=True)
class MatrixCell:
    period: PeriodeLaporan | None
    history: MonteCarloMetricHistory | None


class MonteCarloWorkspaceMixin:
    change_list_template = "admin/corporate_risk/riskmetric/change_list.html"
    workspace_template = "admin/corporate_risk/riskmetric/workspace.html"

    def get_urls(self):
        return [
            path(
                "workspace/",
                self.admin_site.admin_view(self.monte_carlo_workspace_view),
                name="corporate_risk_riskmetric_workspace",
            ),
        ] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        extra_context = dict(extra_context or {})
        extra_context["workspace_url"] = reverse(
            f"{self.admin_site.name}:corporate_risk_riskmetric_workspace"
        )
        return super().changelist_view(request, extra_context=extra_context)

    def _workspace_items(self):
        return (
            ProfilRisikoKorporatItem.objects.select_related("summary")
            .order_by("-summary__tahun", "summary__judul", "no_item", "pk")
        )

    def _selected_item(self, request):
        item_id = request.POST.get("item") or request.GET.get("item")
        if not item_id:
            return None
        try:
            return ProfilRisikoKorporatItem.objects.select_related("summary").get(pk=item_id)
        except (ProfilRisikoKorporatItem.DoesNotExist, TypeError, ValueError):
            return None

    def _monthly_periods(self, year: int) -> dict[int, PeriodeLaporan]:
        periods = PeriodeLaporan.objects.filter(
            tahun_buku__tahun=year,
            jenis_periode="bulanan",
        ).order_by("tanggal_mulai", "tanggal_selesai", "pk")
        result = {}
        for period in periods:
            if period.tanggal_mulai.year == year:
                result.setdefault(period.tanggal_mulai.month, period)
        return result

    def _active_metrics(self, item):
        return list(
            RiskMetric.objects.filter(corporate_risk_item=item, is_active=True)
            .select_related("rkap_item")
            .prefetch_related("metric_histories")
            .order_by("name", "pk")
        )

    def _save_matrix(self, request, item, metrics, periods):
        if not (
            request.user.has_perm("corporate_risk.add_montecarlometrichistory")
            or request.user.has_perm("corporate_risk.change_montecarlometrichistory")
        ):
            raise PermissionDenied

        submitted = []
        invalid = []
        value_field = MonteCarloMetricHistory._meta.get_field("metric_value")
        for metric in metrics:
            for month, period in periods.items():
                raw_value = (request.POST.get(f"history_{metric.pk}_{period.pk}") or "").strip()
                if not raw_value:
                    continue
                try:
                    value = value_field.clean(Decimal(raw_value.replace(",", "")), None)
                except (InvalidOperation, ValidationError, ValueError):
                    invalid.append(f"{metric.name} - bulan {month}: '{raw_value}'")
                    continue
                submitted.append((metric, period, value))

        if invalid:
            self.message_user(
                request,
                "Nilai tidak sah; tidak ada data yang disimpan: " + "; ".join(invalid),
                level=messages.ERROR,
            )
            return 0, 0

        created_count = updated_count = 0
        with transaction.atomic():
            for metric, period, value in submitted:
                history, created = MonteCarloMetricHistory.objects.get_or_create(
                    metric=metric,
                    periode=period,
                    defaults={
                        "tanggal_data": period.tanggal_selesai,
                        "metric_value": value,
                        "status": MonteCarloMetricHistory.STATUS_UPDATED,
                    },
                )
                if created:
                    created_count += 1
                    continue
                history.metric_value = value
                history.tanggal_data = period.tanggal_selesai
                update_fields = ["metric_value", "tanggal_data", "updated_at"]
                if history.status == MonteCarloMetricHistory.STATUS_UNUPDATED:
                    history.status = MonteCarloMetricHistory.STATUS_UPDATED
                    update_fields.append("status")
                history.save(update_fields=update_fields)
                updated_count += 1
        self.message_user(
            request,
            f"Semua histori diproses: {created_count} data baru, {updated_count} data diperbarui.",
            level=messages.SUCCESS,
        )
        return created_count, updated_count

    def _workspace_context(self, request, item):
        namespace = self.admin_site.name
        items = list(self._workspace_items())
        context: dict[str, Any] = {
            **self.admin_site.each_context(request),
            "title": "Monte Carlo Workspace",
            "opts": self.model._meta,
            "items": items,
            "selected_item": item,
            "months": MONTHS,
            "can_manage_history": (
                request.user.has_perm("corporate_risk.add_montecarlometrichistory")
                or request.user.has_perm("corporate_risk.change_montecarlometrichistory")
            ),
            "riskmetric_changelist_url": reverse(
                f"{namespace}:corporate_risk_riskmetric_changelist"
            ),
        }
        if not item:
            return context

        metrics = self._active_metrics(item)
        periods = self._monthly_periods(item.summary.tahun)
        histories = {
            (history.metric_id, history.periode_id): history
            for metric in metrics
            for history in metric.metric_histories.all()
        }
        valid_counts = {
            metric.pk: sum(
                history.status != MonteCarloMetricHistory.STATUS_UNUPDATED
                for history in metric.metric_histories.all()
            )
            for metric in metrics
        }
        metric_rows = []
        for metric in metrics:
            metric_rows.append({
                "metric": metric,
                "cells": [
                    MatrixCell(periods.get(month), histories.get((metric.pk, periods[month].pk)) if month in periods else None)
                    for month, _label in MONTHS
                ],
                "history_count": valid_counts[metric.pk],
                "ready": valid_counts[metric.pk] >= MINIMUM_HISTORY_POINTS,
                "change_url": reverse(
                    f"{namespace}:corporate_risk_riskmetric_change", args=[metric.pk]
                ),
                "history_url": reverse(
                    f"{namespace}:corporate_risk_montecarlometrichistory_changelist"
                ) + f"?metric__id__exact={metric.pk}",
            })

        results = list(
            MultiMetricMonteCarloResult.objects.filter(corporate_risk_item=item)
            .select_related("forecast_periode", "ai_insight_multi_metric")
            .order_by("-created_at")[:5]
        )
        result_rows = []
        insight_ids = set(
            MultiMetricAIInsightKorporat.objects.filter(
                multi_metric_result_id__in=[result.pk for result in results]
            ).values_list("multi_metric_result_id", flat=True)
        )
        for result in results:
            result_rows.append({
                "result": result,
                "change_url": reverse(
                    f"{namespace}:corporate_risk_multimetricmontecarloresult_change",
                    args=[result.pk],
                ),
                "insight_url": (
                    reverse(
                        f"{namespace}:corporate_risk_multimetricaiinsightkorporat_change",
                        args=[result.ai_insight_multi_metric.pk],
                    ) if result.pk in insight_ids else None
                ),
            })

        has_metrics = bool(metrics)
        all_history_ready = has_metrics and all(row["ready"] for row in metric_rows)
        target_metrics = [metric for metric in metrics if metric.is_target_metric]
        target_ready = any(metric.effective_target_value is not None for metric in target_metrics)
        total_weight = sum((metric.weight or Decimal("0")) for metric in metrics)
        is_ready = all_history_ready and bool(target_metrics) and target_ready and total_weight > 0
        context.update({
            "metrics": metrics,
            "metric_rows": metric_rows,
            "periods_available": len(periods),
            "total_history": sum(valid_counts.values()),
            "minimum_history_points": MINIMUM_HISTORY_POINTS,
            "target_metrics": target_metrics,
            "target_ready": target_ready,
            "total_weight": total_weight,
            "is_ready": is_ready,
            "latest_result": results[0] if results else None,
            "result_rows": result_rows,
            "add_metric_url": reverse(f"{namespace}:corporate_risk_riskmetric_add")
                + f"?corporate_risk_item={item.pk}",
            "profile_url": reverse(
                f"{namespace}:risk_profilrisikokorporatsummary_change", args=[item.summary_id]
            ),
            "history_list_url": reverse(
                f"{namespace}:corporate_risk_montecarlometrichistory_changelist"
            ),
            "simulation_add_url": reverse(
                f"{namespace}:corporate_risk_multimetricmontecarloresult_add"
            ) + f"?corporate_risk_item={item.pk}&n_simulations=10000&distribution_type=empirical",
            "results_url": reverse(
                f"{namespace}:corporate_risk_multimetricmontecarloresult_changelist"
            ) + f"?corporate_risk_item__id__exact={item.pk}",
        })
        return context

    def monte_carlo_workspace_view(self, request):
        if not self.has_view_permission(request):
            raise PermissionDenied
        item = self._selected_item(request)
        if request.method == "POST":
            if not item:
                self.message_user(request, "Risiko tidak valid.", level=messages.ERROR)
            else:
                self._save_matrix(
                    request,
                    item,
                    self._active_metrics(item),
                    self._monthly_periods(item.summary.tahun),
                )
            url = reverse(f"{self.admin_site.name}:corporate_risk_riskmetric_workspace")
            return redirect(f"{url}?item={item.pk}" if item else url)
        return TemplateResponse(
            request,
            self.workspace_template,
            self._workspace_context(request, item),
        )
