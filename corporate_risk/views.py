import json

from .models import MonteCarloKorporatResult

from django.shortcuts import render, redirect, get_object_or_404
from django.forms import modelformset_factory

from .models import RiskMetric, MonteCarloMetricHistory


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

    MonteCarloMetricHistory.objects.filter(
        metric=metric
    ).order_by("tanggal_data")

    if request.method == "POST":
        formset = HistoryFormSet(request.POST, queryset=queryset)

        if formset.is_valid():
            instances = formset.save(commit=False)

            for obj in instances:
                obj.risk_metric = metric
                obj.save()

            for obj in formset.deleted_objects:
                obj.delete()

            return redirect("admin:corporate_risk_montecarlometrichistory_changelist")
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

