from __future__ import annotations

from decimal import Decimal
from typing import Any

from corporate_risk.models import (
    MonteCarloForecastAssumption,
    MonteCarloMetricHistory,
    MultiMetricMonteCarloResult,
    RiskMetric,
)
from risk.executive_signage import (
    _build_risk_card,
    _format_value,
    _linked_ratio_actuals,
    _rate_actuals,
    _validated_imported_outlook,
)
from risk.models import ProfilRisikoKorporatItem


YEAR = 2026
BLANKS = (None, "", "–", "-")


def check(label: str, condition: bool, details: str = "") -> bool:
    status = "PASS" if condition else "REVIEW"
    suffix = f" | {details}" if details else ""
    print(f"{status:<8} {label}{suffix}")
    return bool(condition)


def get_risk(no: int):
    obj = (
        ProfilRisikoKorporatItem.objects
        .filter(summary__tahun=YEAR, no_risiko=no)
        .first()
    )
    if not obj:
        raise RuntimeError(f"STOP: Risk #{no} tahun {YEAR} tidak ditemukan.")
    return obj


def latest_result(risk):
    return (
        MultiMetricMonteCarloResult.objects
        .filter(corporate_risk_item=risk)
        .order_by("-created_at", "-id")
        .first()
    )


def external_validation(result):
    if not result:
        return {}
    return (result.simulation_snapshot or {}).get("external_validation") or {}


def executive_meta(result):
    if not result:
        return {}
    return (result.simulation_snapshot or {}).get("executive_risk") or {}


def result_row(result, metric):
    if not result:
        return None
    rows = (result.metric_snapshot or {}).get("metrics") or []
    for row in rows:
        if row.get("metric_id") == metric.id or row.get("metric_name") == metric.name:
            return row
    return None


def active_assumptions(metric):
    return MonteCarloForecastAssumption.objects.filter(
        metric=metric,
        forecast_date__year=YEAR,
        is_active=True,
    )


def histories(metric, through_month=8):
    return list(
        MonteCarloMetricHistory.objects
        .filter(
            metric=metric,
            tanggal_data__year=YEAR,
            tanggal_data__month__lte=through_month,
        )
        .order_by("tanggal_data", "id")
    )


def sum_hist(metric, through_month=8):
    return sum(
        (Decimal(str(x.metric_value)) for x in histories(metric, through_month)),
        Decimal("0"),
    )


def last_hist(metric, through_month=8):
    qs = (
        MonteCarloMetricHistory.objects
        .filter(
            metric=metric,
            tanggal_data__year=YEAR,
            tanggal_data__month__lte=through_month,
        )
        .order_by("-tanggal_data", "-id")
    )
    return qs.first()


def card_line(card: dict[str, Any]):
    return (
        f"CURRENT={card.get('current')} | YTD={card.get('ytd')} | "
        f"TARGET={card.get('target')} | FORECAST={card.get('forecast')} | "
        f"WORST={card.get('worst_case')} | PROB={card.get('probability_not_achieve')} | "
        f"STATUS={card.get('status')} | VALID={card.get('model_validation')} | "
        f"SOURCE={card.get('model_source')}"
    )


print("=" * 170)
print("ERM LOCAL — CONSOLIDATED CRYSTAL BALL / EXECUTIVE RISK REGRESSION V4.6.1 — READ ONLY")
print("=" * 170)
print("YEAR     : 2026")
print("DB WRITE : NONE")
print("MC RERUN : NONE — uses latest existing result only")
print()

all_checks = []
matrix = []


# ======================================================================
# RISK #2 + #3
# ======================================================================
risk2 = get_risk(2)
risk3 = get_risk(3)

sales = (
    RiskMetric.objects
    .filter(corporate_risk_item=risk2, name__iexact="Penjualan Tenaga Listrik (kWh)")
    .first()
)
if not sales:
    sales = (
        RiskMetric.objects
        .filter(corporate_risk_item=risk2, name__icontains="Penjualan Tenaga Listrik")
        .exclude(name__icontains="Pendapatan")
        .first()
    )
if not sales:
    raise RuntimeError("STOP: Risk #2 sales metric tidak ditemukan.")

revenue = (
    RiskMetric.objects
    .filter(corporate_risk_item=risk2, name__iexact="Pendapatan Penjualan Tenaga Listrik")
    .first()
)
hjr = (
    RiskMetric.objects
    .filter(corporate_risk_item=risk3, name__icontains="Harga Jual Rata-rata")
    .first()
)
if not revenue or not hjr:
    raise RuntimeError("STOP: Risk #2 revenue atau Risk #3 HJR metric tidak ditemukan.")

r2_result = latest_result(risk2)
r2_validation = external_validation(r2_result)
r2_exec = executive_meta(r2_result)
r2_outlook = _validated_imported_outlook(r2_result, sales) if r2_result else None
card2 = _build_risk_card(risk2, YEAR)
card3 = _build_risk_card(risk3, YEAR)
ratio_actuals = _linked_ratio_actuals(hjr, YEAR) or {}

print("A. RISK #2 DEMAND + RISK #3 DERIVED HJR")
print("-" * 170)
print(f"RISK #2 RESULT : ID={getattr(r2_result, 'id', None)} | VALID={r2_validation.get('status')}")
print("RISK #2 CARD   :", card_line(card2))
print("RISK #3 CARD   :", card_line(card3))
print(
    f"RATIO ACTUALS  : current={ratio_actuals.get('current')} | "
    f"ytd={ratio_actuals.get('ytd')} | month={ratio_actuals.get('month')}"
)

r2_checks = [
    check("R2 latest result exists", r2_result is not None),
    check("R2 external validation PASS", r2_validation.get("status") == "PASS"),
    check("R2 aggregation SUM", sales.aggregation_type == "sum"),
    check("R2 direction decrease", sales.direction == "decrease"),
    check("R2 Executive validation PASS", card2.get("model_validation") == "PASS"),
    check("R2 Executive forecast populated", card2.get("forecast") not in BLANKS),
    check("R2 Executive worst populated", card2.get("worst_case") not in BLANKS),
    check(
        "R2 headline worst = P5",
        bool(r2_outlook) and r2_outlook.get("worst_case_percentile") == "P5",
        "validated outlook direction-aware check",
    ),
    check("R3 HJR aggregation RATIO", hjr.aggregation_type == "ratio"),
    check("R3 derived current month = Aug", ratio_actuals.get("month") == 8),
    check("R3 Executive validation PASS", card3.get("model_validation") == "PASS"),
    check(
        "R3 Executive source is derived RATIO",
        "derived RATIO" in str(card3.get("model_source") or ""),
    ),
]
all_checks.extend(r2_checks)
matrix.append(("#2", "Demand", "FULL VALIDATED", all(r2_checks)))
matrix.append(("#3", "HJR derived ratio", "DERIVED VALIDATED", all(r2_checks[8:])))


# ======================================================================
# RISK #4
# ======================================================================
risk4 = get_risk(4)
offgrid = RiskMetric.objects.filter(
    corporate_risk_item=risk4,
    name__iexact="Total Pendapatan Off Grid",
).first()
if not offgrid:
    raise RuntimeError("STOP: Risk #4 Total Pendapatan Off Grid metric tidak ditemukan.")

r4_result = latest_result(risk4)
r4_validation = external_validation(r4_result)
r4_exec = executive_meta(r4_result)
card4 = _build_risk_card(risk4, YEAR)
r4_assumption = active_assumptions(offgrid).order_by("forecast_date", "id").first()
r4_meta = (r4_assumption.source_metadata or {}) if r4_assumption else {}
r4_dep = r4_meta.get("dependency_model") or {}

print()
print("B. RISK #4 OFF GRID")
print("-" * 170)
print(f"RESULT      : ID={getattr(r4_result, 'id', None)} | VALID={r4_validation.get('status')}")
print(f"DEPENDENCY  : {r4_dep}")
print("CARD        :", card_line(card4))

r4_checks = [
    check("R4 latest result exists", r4_result is not None),
    check("R4 validation PASS", r4_validation.get("status") == "PASS"),
    check("R4 aggregation SUM", offgrid.aggregation_type == "sum"),
    check("R4 direction decrease", offgrid.direction == "decrease"),
    check("R4 dependency equicorrelation", r4_dep.get("type") == "equicorrelation"),
    check(
        "R4 rho approximately 0.14779",
        abs(float(r4_dep.get("rho") or 0) - 0.14779007686114584) < 1e-6,
    ),
    check("R4 zero-floor disabled", r4_dep.get("truncate_at_zero") is False),
    check("R4 worst percentile P5", r4_exec.get("headline_worst_case_percentile") == "P5"),
    check("R4 Executive validation PASS", card4.get("model_validation") == "PASS"),
]
all_checks.extend(r4_checks)
matrix.append(("#4", "Off Grid", "FULL VALIDATED", all(r4_checks)))


# ======================================================================
# RISK #5
# ======================================================================
risk5 = get_risk(5)
sla = RiskMetric.objects.filter(
    corporate_risk_item=risk5,
    name__iexact="Realisasi Kompensasi SLA",
).first()
if not sla:
    raise RuntimeError("STOP: Risk #5 SLA metric tidak ditemukan.")

r5_result = latest_result(risk5)
r5_validation = external_validation(r5_result)
card5 = _build_risk_card(risk5, YEAR)
r5_outlook = _validated_imported_outlook(r5_result, sla) if r5_result else None
r5_assumption = active_assumptions(sla).order_by("forecast_date", "id").first()
r5_meta = (r5_assumption.source_metadata or {}) if r5_assumption else {}
r5_upper = r5_meta.get("upper_tail_diagnostic") or {}

print()
print("C. RISK #5 BLACKOUT — SAFETY BLOCK")
print("-" * 170)
print(f"RESULT      : ID={getattr(r5_result, 'id', None)} | VALID={r5_validation.get('status')}")
print(f"SCOPE       : {r5_meta.get('validation_scope')}")
print(f"UPPER TAIL  : {r5_upper.get('upper_tail_status')}")
print("CARD        :", card_line(card5))
print(f"VALIDATED IMPORTED OUTLOOK OBJECT: {r5_outlook}")

r5_checks = [
    check("R5 latest result exists", r5_result is not None),
    check("R5 external validation remains REVIEW", r5_validation.get("status") == "REVIEW"),
    check("R5 validation scope PARTIAL_BASELINE", r5_meta.get("validation_scope") == "PARTIAL_BASELINE"),
    check("R5 upper tail UNRESOLVED", r5_upper.get("upper_tail_status") == "UNRESOLVED"),
    check("R5 imported Executive outlook BLOCKED", r5_outlook is None),
    check("R5 no PASS badge on Executive", card5.get("model_validation") != "PASS"),
    check("R5 Executive forecast hidden while REVIEW", card5.get("forecast") in BLANKS),
    check("R5 Executive worst hidden while REVIEW", card5.get("worst_case") in BLANKS),
]
all_checks.extend(r5_checks)
matrix.append(("#5", "Blackout", "BASELINE PASS / UPPER TAIL UNRESOLVED", all(r5_checks)))


# ======================================================================
# RISK #8
# ======================================================================
risk8 = get_risk(8)
mpp = RiskMetric.objects.filter(
    corporate_risk_item=risk8,
    name__iexact="Realisasi Pendapatan MPP",
).first()
if not mpp:
    raise RuntimeError("STOP: Risk #8 MPP metric tidak ditemukan.")

r8_result_count = MultiMetricMonteCarloResult.objects.filter(
    corporate_risk_item=risk8
).count()
r8_assumption_count = active_assumptions(mpp).count()
r8_hist = histories(mpp)
r8_ytd = sum_hist(mpp)
r8_last = last_hist(mpp)
card8 = _build_risk_card(risk8, YEAR)

print()
print("D. RISK #8 MPP — ACTUAL + TARGET ONLY")
print("-" * 170)
print(f"HISTORY COUNT : {len(r8_hist)}")
print(f"CURRENT RAW   : {getattr(r8_last, 'metric_value', None)}")
print(f"YTD RAW       : {r8_ytd}")
print(f"TARGET RAW    : {mpp.effective_target_value}")
print(f"ASSUMPTIONS   : {r8_assumption_count}")
print(f"MC RESULTS    : {r8_result_count}")
print("CARD          :", card_line(card8))

r8_checks = [
    check("R8 history Jan-Aug count = 8", len(r8_hist) == 8),
    check("R8 current Aug exact", Decimal(str(r8_last.metric_value)) == Decimal("178460158516") if r8_last else False),
    check("R8 YTD exact", r8_ytd == Decimal("1252643350306")),
    check("R8 target RKAP exact", Decimal(str(mpp.effective_target_value)).quantize(Decimal("1")) == Decimal("1346855000000")),
    check("R8 direction decrease", mpp.direction == "decrease"),
    check("R8 aggregation SUM", mpp.aggregation_type == "sum"),
    check("R8 active assumptions = 0", r8_assumption_count == 0),
    check("R8 MC result count = 0", r8_result_count == 0),
    check("R8 no Crystal Ball PASS badge", card8.get("model_validation") != "PASS"),
    check(
        "R8 Executive YTD uses Jan-Aug SUM",
        card8.get("ytd") == _format_value(r8_ytd, "Rp"),
        f"card={card8.get('ytd')} expected={_format_value(r8_ytd, 'Rp')}",
    ),
]
all_checks.extend(r8_checks)
matrix.append(("#8", "MPP", "ACTUAL + TARGET ONLY", all(r8_checks)))


# ======================================================================
# RISK #9
# ======================================================================
risk9 = get_risk(9)
gas_volume = RiskMetric.objects.filter(
    corporate_risk_item=risk9,
    name__iexact="Realisasi Volume Gas",
).first()
gas_cost = RiskMetric.objects.filter(
    corporate_risk_item=risk9,
    name__iexact="Realisasi Biaya Gas",
).first()
if not gas_volume or not gas_cost:
    raise RuntimeError("STOP: Risk #9 Volume/Cost Gas metric tidak ditemukan.")

r9_result = latest_result(risk9)
r9_validation = external_validation(r9_result)
r9_exec = executive_meta(r9_result)
card9 = _build_risk_card(risk9, YEAR)

print()
print("E. RISK #9 VOLUME GAS")
print("-" * 170)
print(f"RESULT : ID={getattr(r9_result, 'id', None)} | VALID={r9_validation.get('status')}")
print(f"EXEC   : {r9_exec}")
print("CARD   :", card_line(card9))

r9_checks = [
    check("R9 latest result exists", r9_result is not None),
    check("R9 validation PASS", r9_validation.get("status") == "PASS"),
    check("R9 volume direction increase", gas_volume.direction == "increase"),
    check("R9 volume aggregation SUM", gas_volume.aggregation_type == "sum"),
    check("R9 gas cost aggregation SUM", gas_cost.aggregation_type == "sum"),
    check("R9 worst percentile P95", r9_exec.get("headline_worst_case_percentile") == "P95"),
    check("R9 impact metric = Gas Cost", r9_exec.get("impact_metric_id") == gas_cost.id),
    check("R9 impact worst percentile P95", r9_exec.get("impact_worst_case_percentile") == "P95"),
    check("R9 Executive validation PASS", card9.get("model_validation") == "PASS"),
    check("R9 Executive impact populated", card9.get("potential_loss") not in BLANKS),
]
all_checks.extend(r9_checks)
matrix.append(("#9", "Volume Gas", "FULL VALIDATED", all(r9_checks)))


# ======================================================================
# RISK #10
# ======================================================================
risk10 = get_risk(10)
gas_price = RiskMetric.objects.filter(
    corporate_risk_item=risk10,
    name__iexact="Harga Gas Tertimbang Realisasi",
).first()
if not gas_price:
    raise RuntimeError("STOP: Risk #10 Harga Gas metric tidak ditemukan.")

r10_result = latest_result(risk10)
r10_validation = external_validation(r10_result)
r10_exec = executive_meta(r10_result)
card10 = _build_risk_card(risk10, YEAR)
r10_rate = _rate_actuals(gas_price, YEAR) or {}

print()
print("F. RISK #10 HARGA GAS RATE")
print("-" * 170)
print(f"RESULT       : ID={getattr(r10_result, 'id', None)} | VALID={r10_validation.get('status')}")
print(
    f"RATE ACTUALS : current={r10_rate.get('current')} | "
    f"ytd={r10_rate.get('ytd')} | month={r10_rate.get('month')}"
)
print("CARD         :", card_line(card10))

r10_checks = [
    check("R10 latest result exists", r10_result is not None),
    check("R10 validation PASS", r10_validation.get("status") == "PASS"),
    check("R10 aggregation RATE", gas_price.aggregation_type == "rate"),
    check("R10 direction increase", gas_price.direction == "increase"),
    check(
        "R10 official ERM target 7.4654",
        abs(float(gas_price.effective_target_value) - 7.4654) < 1e-6,
    ),
    check("R10 worst percentile P95", r10_exec.get("headline_worst_case_percentile") == "P95"),
    check("R10 current Aug = 7.50", abs(float(r10_rate.get("current") or 0) - 7.50) < 1e-9),
    check("R10 YTD arithmetic mean = 7.30125", abs(float(r10_rate.get("ytd") or 0) - 7.30125) < 1e-9),
    check("R10 Executive validation PASS", card10.get("model_validation") == "PASS"),
]
all_checks.extend(r10_checks)
matrix.append(("#10", "Harga Gas", "FULL VALIDATED", all(r10_checks)))


# ======================================================================
# CROSS-RISK SAFETY / REGRESSION
# ======================================================================
print()
print("G. CROSS-RISK SAFETY GATES")
print("-" * 170)

cross_checks = [
    check(
        "Only validated models are allowed to show PASS",
        card2.get("model_validation") == "PASS"
        and card3.get("model_validation") == "PASS"
        and card4.get("model_validation") == "PASS"
        and card9.get("model_validation") == "PASS"
        and card10.get("model_validation") == "PASS"
        and card5.get("model_validation") != "PASS"
        and card8.get("model_validation") != "PASS",
    ),
    check(
        "Decrease risks use lower-tail headline where modelled",
        bool(r2_outlook)
        and r2_outlook.get("worst_case_percentile") == "P5"
        and r4_exec.get("headline_worst_case_percentile") == "P5",
    ),
    check(
        "Increase risks use upper-tail headline where fully validated",
        r9_exec.get("headline_worst_case_percentile") == "P95"
        and r10_exec.get("headline_worst_case_percentile") == "P95",
    ),
    check(
        "R5 partial model cannot leak into Executive imported outlook",
        r5_outlook is None
        and card5.get("forecast") in BLANKS
        and card5.get("worst_case") in BLANKS,
    ),
    check(
        "R8 cannot accidentally become stochastic",
        r8_assumption_count == 0 and r8_result_count == 0,
    ),
]
all_checks.extend(cross_checks)


# ======================================================================
# MATRIX / DECISION
# ======================================================================
print()
print("H. CONSOLIDATED MODEL STATUS")
print("-" * 170)
print(f"{'RISK':<8}{'MODEL / SUBJECT':<32}{'EXPECTED STATE':<42}{'REGRESSION':<12}")
for no, subject, state, ok in matrix:
    print(f"{no:<8}{subject:<32}{state:<42}{'PASS' if ok else 'REVIEW':<12}")

passed = sum(1 for x in all_checks if x)
total = len(all_checks)
overall = all(all_checks)

print()
print("I. RELEASE GATE — LOCAL")
print("-" * 170)
print(f"CHECKS : {passed}/{total} PASS")
if overall:
    print("MODEL REGRESSION     : PASS")
    print("EXECUTIVE INTEGRATION: PASS")
    print("DATA CONTAMINATION   : PASS")
    print("LOCAL RELEASE GATE   : PASS FOR VISUAL/UAT REVIEW")
    print()
    print("IMPORTANT:")
    print("  - Risk #5 remains intentionally PARTIAL / blocked from imported Executive outlook.")
    print("  - Risk #8 remains Actual + Target only, with no stochastic badge.")
    print("  - This audit does NOT authorize production deployment by itself.")
else:
    print("MODEL REGRESSION     : REVIEW")
    print("EXECUTIVE INTEGRATION: REVIEW")
    print("LOCAL RELEASE GATE   : BLOCKED")
    print("STOP: inspect all REVIEW lines before any visual/UAT or deployment step.")

print()
print("=" * 170)
print(
    "OVERALL V4.6.1 CONSOLIDATED REGRESSION : "
    + ("PASS — SAFE FOR LOCAL VISUAL/UAT REVIEW" if overall else "REVIEW — BLOCKED")
)
print("DB WRITE: NONE")
print("=" * 170)
