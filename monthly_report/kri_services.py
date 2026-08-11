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

    # BEGIN KRI CATEGORICAL THRESHOLD SUPPORT
    normalized_expression = (
        str(expression or "")
        .strip()
        .casefold()
    )

    categorical_values = {
        "ada": Decimal("1"),
        "ya": Decimal("1"),
        "yes": Decimal("1"),
        "tersedia": Decimal("1"),
        "tidak": Decimal("0"),
        "tidak ada": Decimal("0"),
        "no": Decimal("0"),
        "tidak tersedia": Decimal("0"),
    }

    if normalized_expression in categorical_values:
        return value == categorical_values[normalized_expression]
    # END KRI CATEGORICAL THRESHOLD SUPPORT

    text = (expression or "").strip().casefold().replace("–", "-").replace("—", "-")

    # BEGIN KRI SIGNED RANGE SUPPORT V2
    # Parse signed numeric expressions BEFORE legacy _numbers().
    # Supports:
    #   -5--1.0001
    #   -5 - -1.0001
    #   99-99.9999
    #   >=-1
    #   <-5
    #   100%
    number_pattern = r"[+-]?\d+(?:[.,]\d+)?"

    signed_range = re.fullmatch(
        rf"\s*(?P<lower>{number_pattern})\s*%?\s*"
        rf"(?:-|s/d|sd|to)\s*"
        rf"(?P<upper>{number_pattern})\s*%?\s*",
        text,
    )
    if signed_range:
        lower = Decimal(signed_range.group("lower").replace(",", "."))
        upper = Decimal(signed_range.group("upper").replace(",", "."))
        if lower > upper:
            raise ValidationError(
                "Batas bawah threshold KRI tidak boleh lebih besar dari batas atas."
            )
        return lower <= value <= upper

    signed_boundary = re.fullmatch(
        rf"\s*(?P<op>>=|<=|>|<|≥|≤)?\s*"
        rf"(?P<boundary>{number_pattern})\s*%?\s*",
        text,
    )
    if signed_boundary:
        op = signed_boundary.group("op") or ""
        boundary = Decimal(
            signed_boundary.group("boundary").replace(",", ".")
        )
        if op in (">=", "≥"):
            return value >= boundary
        if op in ("<=", "≤"):
            return value <= boundary
        if op == ">":
            return value > boundary
        if op == "<":
            return value < boundary
        return value == boundary
    # END KRI SIGNED RANGE SUPPORT V2


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
    matches = [
        (status, expression)
        for status, expression in configured
        if _matches(expression, value)
    ]

    if not matches:
        raise ValidationError(
            "Nilai realisasi tidak masuk ke rentang threshold KRI "
            "yang dikonfigurasi. Hubungi administrator."
        )

    if len(matches) > 1:
        normalized_expressions = {
            "".join(str(expression or "").split()).casefold()
            for _, expression in matches
        }

        # KRI dua tingkat dapat menggunakan expression yang sama
        # untuk status Kuning dan Merah, misalnya:
        #
        #   Ada / Tidak / Tidak
        #   100% / <100% / <100%
        #
        # Untuk expression yang identik, gunakan status paling
        # konservatif. Overlap dengan expression berbeda tetap ditolak.
        if len(normalized_expressions) != 1:
            raise ValidationError(
                "Konfigurasi threshold KRI tumpang tindih atau "
                "memiliki celah. Hubungi administrator."
            )

        severity = {
            "green": 1,
            "yellow": 2,
            "red": 3,
        }

        status, expression = max(
            matches,
            key=lambda match: severity.get(match[0], 0),
        )
    else:
        status, expression = matches[0]
    return KRIThresholdResult(status, STATUS_LABELS[status], str(expression).strip())
