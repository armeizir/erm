import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError


STATUS_LABELS = {"green": "Hijau", "yellow": "Kuning", "red": "Merah"}


@dataclass(frozen=True)
class KRIThresholdResult:
    status: str
    label: str
    threshold_range: str


def _numbers(expression):
    return [Decimal(value.replace(",", ".")) for value in re.findall(r"\d+(?:[.,]\d+)?", expression)]


def _matches(expression, value):
    text = (expression or "").strip().casefold().replace("–", "-").replace("—", "-")
    values = _numbers(text)
    if not values:
        raise ValidationError("Konfigurasi threshold KRI belum lengkap. Hubungi administrator.")
    if len(values) >= 2:
        lower, upper = values[0], values[1]
        if lower > upper:
            raise ValidationError("Batas bawah threshold KRI tidak boleh lebih besar dari batas atas.")
        lower_ok = value > lower if re.search(r">\s*" + re.escape(str(values[0])), text) else value >= lower
        upper_ok = value < upper if re.search(r"<\s*" + re.escape(str(values[1])), text) else value <= upper
        return lower_ok and upper_ok
    boundary = values[0]
    if ">=" in text or "≥" in text:
        return value >= boundary
    if "<=" in text or "≤" in text:
        return value <= boundary
    if ">" in text:
        return value > boundary
    if "<" in text:
        return value < boundary
    return value == boundary


def evaluate_kri_threshold(risk_event, actual_value):
    if actual_value is None:
        return None
    try:
        value = Decimal(str(actual_value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError("Nilai realisasi KRI harus berupa angka.") from exc

    direction = getattr(risk_event, "kri_threshold_direction", "")
    if direction not in {"higher_better", "lower_better"}:
        raise ValidationError("Arah threshold KRI belum dikonfigurasi. Hubungi administrator.")
    unit = (risk_event.unit_satuan_kri or "").strip().casefold()
    if unit in {"%", "persen", "percent", "percentage"} and not Decimal("0") <= value <= Decimal("100"):
        raise ValidationError("Nilai realisasi KRI dalam persen harus antara 0 sampai 100.")

    configured = (
        ("green", risk_event.threshold_aman),
        ("yellow", risk_event.threshold_hati_hati),
        ("red", risk_event.threshold_bahaya),
    )
    matches = [(status, expression) for status, expression in configured if _matches(expression, value)]
    if len(matches) != 1:
        raise ValidationError(
            "Konfigurasi threshold KRI tumpang tindih atau memiliki celah. Hubungi administrator."
        )
    status, expression = matches[0]
    return KRIThresholdResult(status, STATUS_LABELS[status], str(expression).strip())
