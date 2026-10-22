"""Residual owners matching monthly_report.admin.kri_is_owner.

Cause rows retain III.B treatment data and are never modified here.
"""
from decimal import Decimal


def monthly_risk_key(risk):
    number = getattr(risk, "no_item", None)
    if number not in (None, ""):
        return f"risk:{number}"
    number = getattr(risk, "no_risiko", None)
    if number not in (None, ""):
        return f"source:{number}"
    event = (getattr(risk, "peristiwa_risiko", "") or "").strip().casefold()
    return f"event:{event}" if event else f"item:{risk.pk}"


def _order(value):
    # PostgreSQL ASC defaults to NULLS LAST. Profile number fields are numeric.
    if value is None:
        return (2, "")
    if isinstance(value, (int, float, Decimal)):
        return (0, value)
    return (1, str(value))


def residual_owner_items(items):
    """One owner per report/no_item; selection does not depend on residual score."""
    candidates = [item for item in items if getattr(item, "risk_event", None) is not None]
    candidates.sort(key=lambda item: (
        _order(getattr(item.risk_event, "no_item", None)),
        _order(getattr(item.risk_event, "no_risiko", None)),
        _order(getattr(item.risk_event, "no_penyebab_risiko", None)),
        _order(item.pk),
    ))
    seen = set()
    owners = []
    for item in candidates:
        key = (getattr(item, "report_id", None), monthly_risk_key(item.risk_event))
        if key not in seen:
            seen.add(key)
            owners.append(item)
    return owners
