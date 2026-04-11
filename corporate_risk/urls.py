from django.urls import path
from .views import monte_carlo_result_chart

urlpatterns = [
    path("monte-carlo/<int:pk>/chart/", monte_carlo_result_chart, name="monte_carlo_result_chart"),
]