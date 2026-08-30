"""Canonical scoring engine untuk Kontrak Manajemen / NKO."""

from decimal import Decimal, ROUND_DOWN


HUNDRED = Decimal("100")
CORPORATE_CAP = Decimal("110")
COMPLIANCE_CAP = Decimal("10")
TWO_DECIMAL = Decimal("0.01")


def _decimal(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def is_corporate_km_item(item):
    """True hanya untuk Item KM milik Group KORPORAT."""
    try:
        unit_name = item.kontrak.unit_bisnis.name
    except Exception:
        return False
    return str(unit_name or "").strip().casefold() == "korporat"


def corporate_rule(item):
    """
    Aturan khusus KM Korporat 2026.

    IKK 01-06,08-09 : positive ratio
    IKK 07          : inverse deviation (Electricity Losses)
    IKK 10          : compliance deduction
    """
    if not is_corporate_km_item(item):
        return "legacy"

    no = getattr(item, "no_urut", None)

    if no == 7:
        return "inverse_deviation"
    if no == 10:
        return "deduction"
    return "positive_ratio"


def truncate_two(value):
    """Excel-like TRUNC ke 2 desimal."""
    value = _decimal(value)
    if value is None:
        return None
    return value.quantize(TWO_DECIMAL, rounding=ROUND_DOWN)


def weighted_score(weight, achievement, *, truncate=False):
    weight = _decimal(weight)
    achievement = _decimal(achievement)

    if weight is None or achievement is None:
        return None

    result = weight * achievement / HUNDRED
    return truncate_two(result) if truncate else result


def compliance_deduction(value):
    """
    Compliance merupakan nilai pengurang maksimum 10.

    Input  0   ->  0
    Input  2   -> -2
    Input -2   -> -2
    Input 12   -> -10
    Input -12  -> -10
    """
    value = _decimal(value)
    if value is None:
        return None

    deduction = -abs(value)

    if deduction < -COMPLIANCE_CAP:
        deduction = -COMPLIANCE_CAP

    return truncate_two(deduction)


def calculate_km_score(item, target, realisasi):
    """
    Return:
        (achievement_percent, weighted_score)

    Legacy KM Unit/Bidang dipertahankan:
      positif -> realisasi / target * 100
      negatif -> target / realisasi * 100

    KM Korporat:
      IKK 1-6,8-9 -> realisasi / target * 100, cap 110
      IKK 7       -> 200 - realisasi/target*100, cap 110
      IKK 10      -> deduction langsung, max -10
      weighted score di-TRUNC 2 decimal.
    """
    target = _decimal(target)
    realisasi = _decimal(realisasi)

    rule = corporate_rule(item)

    # Compliance tidak membutuhkan target numerik.
    if rule == "deduction":
        if realisasi is None:
            return None, None
        return None, compliance_deduction(realisasi)

    if target is None or realisasi is None or target == 0:
        return None, None

    if rule == "inverse_deviation":
        achievement = (
            Decimal("200")
            - (realisasi / target * HUNDRED)
        )
        achievement = max(
            Decimal("0"),
            min(achievement, CORPORATE_CAP),
        )

        score = weighted_score(
            getattr(item, "bobot", 0),
            achievement,
            truncate=True,
        )
        return achievement, score

    if rule == "positive_ratio":
        achievement = realisasi / target * HUNDRED
        achievement = max(
            Decimal("0"),
            min(achievement, CORPORATE_CAP),
        )

        score = weighted_score(
            getattr(item, "bobot", 0),
            achievement,
            truncate=True,
        )
        return achievement, score

    # ======================================================
    # LEGACY UNIT / BIDANG — jangan ubah perilaku existing.
    # ======================================================
    if getattr(item, "polaritas", None) == "negatif":
        if realisasi == 0:
            return None, None
        achievement = target / realisasi * HUNDRED
    else:
        achievement = realisasi / target * HUNDRED

    score = weighted_score(
        getattr(item, "bobot", 0),
        achievement,
        truncate=False,
    )

    return achievement, score
