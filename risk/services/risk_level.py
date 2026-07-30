from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError


@dataclass(frozen=True)
class RiskLevel:
    code: str
    workbook_label: str
    display_label: str
    css_class: str
    color: str


RISK_LEVELS = (
    (1, 5, RiskLevel("LOW", "Low", "Rendah", "risk-level-low", "#00B050")),
    (
        6,
        11,
        RiskLevel(
            "LOW_TO_MODERATE",
            "Low To Moderate",
            "Rendah ke Moderat",
            "risk-level-low-moderate",
            "#92D050",
        ),
    ),
    (
        12,
        15,
        RiskLevel(
            "MODERATE",
            "Moderate",
            "Moderat",
            "risk-level-moderate",
            "#FFFF00",
        ),
    ),
    (
        16,
        19,
        RiskLevel(
            "MODERATE_TO_HIGH",
            "Moderate To High",
            "Moderat ke Tinggi",
            "risk-level-moderate-high",
            "#FFC000",
        ),
    ),
    (20, 25, RiskLevel("HIGH", "High", "Tinggi", "risk-level-high", "#FF0000")),
)

RISK_LEVEL_CHOICES = tuple(
    (level.workbook_label, level.display_label) for _, _, level in RISK_LEVELS
)

_LEVEL_BY_NORMALIZED_LABEL = {}
for _, _, _level in RISK_LEVELS:
    for _label in (_level.code, _level.workbook_label, _level.display_label):
        _LEVEL_BY_NORMALIZED_LABEL[
            " ".join(
                str(_label)
                .strip()
                .replace("_", " ")
                .replace("-", " ")
                .casefold()
                .split()
            )
        ] = _level

# Legacy labels stored before the official five-level terminology was applied.
_LEVEL_BY_NORMALIZED_LABEL.update(
    {
        "sedang": next(level for _, _, level in RISK_LEVELS if level.code == "MODERATE"),
        "tinggi": next(level for _, _, level in RISK_LEVELS if level.code == "HIGH"),
        "ekstrem": next(level for _, _, level in RISK_LEVELS if level.code == "HIGH"),
        "extreme": next(level for _, _, level in RISK_LEVELS if level.code == "HIGH"),
    }
)


def normalize_risk_scale(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValidationError("Skala Risiko harus berupa bilangan bulat antara 1 dan 25.")
    try:
        numeric = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(
            "Skala Risiko harus berupa bilangan bulat antara 1 dan 25."
        ) from exc
    if not numeric.is_finite() or numeric != numeric.to_integral_value():
        raise ValidationError("Skala Risiko harus berupa bilangan bulat antara 1 dan 25.")
    scale = int(numeric)
    if not 1 <= scale <= 25:
        raise ValidationError("Skala Risiko harus berupa bilangan bulat antara 1 dan 25.")
    return scale


def classify_risk_level(risk_scale):
    """Return the official risk-level definition for a scale from 1 through 25."""
    scale = normalize_risk_scale(risk_scale)
    if scale is None:
        return None
    for lower, upper, level in RISK_LEVELS:
        if lower <= scale <= upper:
            return level
    raise AssertionError("Validated risk scale was not classified.")


def normalize_level_label(value):
    """Resolve stored canonical, workbook, Indonesian, and legacy labels."""
    if value is None or not str(value).strip():
        return None
    normalized = " ".join(
        str(value)
        .strip()
        .replace("_", " ")
        .replace("-", " ")
        .casefold()
        .split()
    )
    return _LEVEL_BY_NORMALIZED_LABEL.get(normalized)


def resolve_item_quarterly_risk_level(item, quarter):
    """Read the correct persisted field, then fall back to the quarter's scale."""
    stored = getattr(item, f"level_nilai_risiko_q{quarter}", None)
    level = normalize_level_label(stored)
    if level:
        return level

    scale = getattr(item, f"skala_risiko_q{quarter}", None)
    if scale in (None, ""):
        return None
    try:
        return classify_risk_level(scale)
    except ValidationError:
        return None


def get_quarterly_risk_level_display(item, quarter):
    level = resolve_item_quarterly_risk_level(item, quarter)
    return level.display_label if level else "-"


def calculate_item_quarterly_risk_levels(item):
    values = {}
    for quarter in range(1, 5):
        field_name = f"level_nilai_risiko_q{quarter}"
        try:
            level = classify_risk_level(
                getattr(item, f"skala_risiko_q{quarter}", None)
            )
        except ValidationError as exc:
            raise ValidationError(
                {
                    f"skala_risiko_q{quarter}": (
                        f"Skala Risiko Q{quarter} harus berupa bilangan bulat "
                        "antara 1 dan 25."
                    )
                }
            ) from exc
        values[field_name] = level.workbook_label if level else None
    return values


def assign_item_quarterly_risk_levels(item):
    values = calculate_item_quarterly_risk_levels(item)
    for field_name, value in values.items():
        setattr(item, field_name, value)
    return values
