from django.urls import path

from .views import (
    monte_carlo_result_chart,
    bulk_metric_input,
    metric_history_input_menu,
)

urlpatterns = [
    path(
        "monte-carlo/<int:pk>/chart/",
        monte_carlo_result_chart,
        name="monte_carlo_result_chart",
    ),

    path(
        "metric/<int:metric_id>/bulk-input/",
        bulk_metric_input,
        name="bulk_metric_input",
    ),

    path(
        "metric-history-input/",
        metric_history_input_menu,
        name="metric_history_input_menu",
    ),
]
