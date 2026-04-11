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


def _percentile(values, p):
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * (p / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return values[int(k)]
    d0 = values[f] * (c - k)
    d1 = values[c] * (k - f)
    return d0 + d1


def _std(values):
    if len(values) <= 1:
        return 0
    avg = _mean(values)
    return math.sqrt(sum((x - avg) ** 2 for x in values) / (len(values) - 1))


def _simulate(history, n):
    avg = _mean(history)
    std = _std(history)

    if std == 0:
        return [avg] * n

    return [random.gauss(avg, std) for _ in range(n)]


def _derive_status(probability):
    if probability is None:
        return "UNKNOWN"
    if probability >= 80:
        return "AMAN"
    if probability >= 60:
        return "WASPADA"
    return "KRITIS"


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
    p50 = _percentile(simulations, 50)
    p80 = _percentile(simulations, 80)
    p90 = _percentile(simulations, 90)
    min_value = min(simulations)
    max_value = max(simulations)

    latest = histories.last()
    target = float(latest.target_value) if latest and latest.target_value is not None else None

    probability = None
    if target is not None:
        if config.direction == "lower":
            probability = sum(1 for x in simulations if x <= target) / len(simulations) * 100
        else:
            probability = sum(1 for x in simulations if x >= target) / len(simulations) * 100

    status_hasil = _derive_status(probability)

    result = MonteCarloKorporatResult.objects.create(
        corporate_risk_item=item,
        forecast_periode=forecast_periode,
        metric_name=config.metric_name,
        mean_value=_to_decimal(mean),
        p50_value=_to_decimal(p50),
        p80_value=_to_decimal(p80),
        p90_value=_to_decimal(p90),
        min_value=_to_decimal(min_value),
        max_value=_to_decimal(max_value),
        probability_meet_target=_to_decimal(probability) if probability is not None else None,
        target_value=_to_decimal(target) if target is not None else None,
        status_hasil=status_hasil,
        history_snapshot=[
            {
                "periode": h.periode.nama_periode,
                "tanggal": str(h.tanggal_data),
                "value": float(h.metric_value),
                "target": float(h.target_value) if h.target_value is not None else None,
            }
            for h in histories
        ],
        simulation_snapshot=[round(x, 4) for x in simulations[:300]],
    )

    return result