import math
import random
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from .models import (
    MonteCarloKorporatConfig,
    MonteCarloKorporatHistory,
    MonteCarloKorporatResult,
)


def _to_decimal(value):
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _mean(values):
    return sum(values) / len(values)


def _std(values):
    avg = _mean(values)
    return math.sqrt(sum((x - avg) ** 2 for x in values) / (len(values) - 1))


def _simulate(history, n):
    avg = _mean(history)
    std = _std(history) if len(history) > 1 else 0

    if std == 0:
        return [avg] * n

    return [random.gauss(avg, std) for _ in range(n)]


@transaction.atomic
def run_monte_carlo_for_korporat_item(item, forecast_periode):

    config = item.monte_carlo_config

    histories = MonteCarloKorporatHistory.objects.filter(
        corporate_risk_item=item,
        metric_name=config.metric_name
    ).order_by("tanggal_data")

    values = [float(x.metric_value) for x in histories]

    if len(values) < config.minimum_history_points:
        raise ValueError("Data histori belum cukup")

    simulations = _simulate(values, config.n_simulations)

    simulations.sort()

    mean = _mean(simulations)
    p80 = simulations[int(len(simulations) * 0.8)]

    target = histories.last().target_value if histories.last() else None

    probability = None
    if target:
        target = float(target)

        if config.direction == "lower":
            probability = sum(1 for x in simulations if x <= target) / len(simulations) * 100
        else:
            probability = sum(1 for x in simulations if x >= target) / len(simulations) * 100

    result = MonteCarloKorporatResult.objects.create(
        corporate_risk_item=item,
        forecast_periode=forecast_periode,
        metric_name=config.metric_name,
        mean_value=_to_decimal(mean),
        p80_value=_to_decimal(p80),
        probability_meet_target=_to_decimal(probability) if probability else None,
    )

    return result