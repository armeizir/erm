from django.urls import path

from .strategy_risk_map import strategy_risk_map

app_name = "strategy_risk_map"

urlpatterns = [
    path("", strategy_risk_map, name="home"),
]
