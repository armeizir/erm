import json

from django.shortcuts import get_object_or_404, render

from .models import MonteCarloKorporatResult


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