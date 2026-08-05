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
    data_status: str = "valid"
    diagnostics: dict | None = None
    is_complete: bool = True
    requires_verification: bool = False
    assessed_weight: Decimal = Decimal("100.00")
    unassessed_weight: Decimal = Decimal("0.00")
    provisional_score: Decimal = Decimal("0.00")
    final_score: Decimal | None = None
    final_rating: str | None = None
    normalized_indicative_score: Decimal | None = None
