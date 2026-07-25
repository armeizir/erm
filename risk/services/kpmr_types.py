from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.contrib.auth.models import Group


@dataclass(frozen=True)
class KPMRCalculation:
    year: int
    quarter: int
    unit: Group
    report_count: int
    item_count: int
    score_total: Decimal
    rating: str
    indicators: list[dict]
    notes: list[str]
    month: int | None = None
