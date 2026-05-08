import json

from .models import MonteCarloKorporatResult

from django.shortcuts import render, redirect, get_object_or_404
from django.forms import modelformset_factory

from .models import RiskMetric, MonteCarloMetricHistory

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from decimal import Decimal

def monte_carlo_result_chart(request, pk):
    result = get_object_or_404(MonteCarloKorporatResult, pk=pk)

    history_labels = [x["periode"] for x in result.history_snapshot]
    history_values = [x["value"] for x in result.history_snapshot]

    context = {
        "result": result,
        "history_labels_json": json.dumps(history_labels),
        "history_values_json": json.dumps(history_values),
        "simulation_values_json": json.dumps(result.simulation_snapshot),
    }
    return render(request, "corporate_risk/monte_carlo_chart.html", context)

def bulk_metric_input(request, metric_id):
    metric = get_object_or_404(RiskMetric, id=metric_id)

    HistoryFormSet = modelformset_factory(
        MonteCarloMetricHistory,
        fields=(
            "periode",
            "tanggal_data",
            "metric_value",
            "target_value",
            "keterangan",
        ),
        extra=12,
        can_delete=True,
    )

    queryset = MonteCarloMetricHistory.objects.filter(
        metric=metric
    ).order_by("tanggal_data")

    if request.method == "POST":
        formset = HistoryFormSet(
            request.POST,
            queryset=queryset,
        )

        if formset.is_valid():
            instances = formset.save(commit=False)

            for obj in instances:
                obj.metric = metric
                obj.save()

            for obj in formset.deleted_objects:
                obj.delete()

            return redirect(
                "corporate_risk:bulk_metric_input",
                metric_id=metric.id,
            )

    else:
        formset = HistoryFormSet(queryset=queryset)

    return render(
        request,
        "corporate_risk/bulk_metric_input.html",
        {
            "metric": metric,
            "formset": formset,
        },
    )

    metric = get_object_or_404(RiskMetric, id=metric_id)

    rows = []
    histories = MonteCarloMetricHistory.objects.filter(
        metric=metric
    ).select_related("periode").order_by("tanggal_data")

    for h in histories:
        rows.append({
            "id": h.id,
            "periode_id": h.periode_id,
            "periode": str(h.periode),
            "tanggal_data": h.tanggal_data.isoformat() if h.tanggal_data else "",
            "metric_value": float(h.metric_value) if h.metric_value is not None else None,
            "target_value": float(h.target_value) if h.target_value is not None else None,
            "keterangan": h.keterangan or "",
        })

    return JsonResponse({
        "metric": {
            "id": metric.id,
            "name": metric.name,
            "unit": metric.unit,
            "direction": metric.direction,
            "weight": float(metric.weight),
        },
        "rows": rows,
    })