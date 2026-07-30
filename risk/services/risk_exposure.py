from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError


EXPOSURE_QUANTUM = Decimal("0.01")
PROBABILITY_MIN = Decimal("0")
PROBABILITY_MAX = Decimal("100")


def _as_decimal(value):
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError("Nilai dampak dan probabilitas harus berupa angka.") from exc


def calculate_quarterly_risk_exposure(impact, probability):
    """Calculate an exposure from an impact and a 0–100 probability."""
    impact = _as_decimal(impact)
    probability = _as_decimal(probability)
    if impact is None or probability is None:
        return None
    if not PROBABILITY_MIN <= probability <= PROBABILITY_MAX:
        raise ValidationError(
            "Nilai probabilitas harus berada antara 0% dan 100%."
        )
    return (
        impact * (probability / Decimal("100"))
    ).quantize(EXPOSURE_QUANTUM, rounding=ROUND_HALF_UP)


def calculate_item_quarterly_exposures(item):
    values = {}
    for quarter in range(1, 5):
        try:
            values[f"eksposur_risiko_q{quarter}"] = (
                calculate_quarterly_risk_exposure(
                    getattr(item, f"nilai_dampak_q{quarter}"),
                    getattr(item, f"nilai_probabilitas_q{quarter}"),
                )
            )
        except ValidationError as exc:
            raise ValidationError(
                {
                    f"nilai_probabilitas_q{quarter}": (
                        f"Nilai Probabilitas Q{quarter} harus berada "
                        "antara 0% dan 100%."
                    )
                }
            ) from exc
    return values


def assign_item_quarterly_exposures(item):
    values = calculate_item_quarterly_exposures(item)
    for field_name, value in values.items():
        setattr(item, field_name, value)
    return values
