#!/usr/bin/env python3
"""
READ ONLY audit for:
  2. KK RISIKO Penjualan - Demand Agustus 2026.xlsx

Purpose:
- Extract cached Crystal Ball model inputs/benchmarks from workbook.
- Validate monthly Normal assumptions for Sep-Dec 2026.
- Compare Crystal Ball P5/P50/P95 with analytical Normal aggregation.
- NO database write. NO workbook write.

Usage:
  python corporate_risk/scripts/audit_crystal_ball_penjualan_agustus_2026_v1_readonly.py /tmp/KK_RISIKO_Penjualan_Demand_Agustus_2026.xlsx
"""
from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path

from openpyxl import load_workbook

Z_05 = 1.6448536269514722
MONTHS_ACTUAL = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu"]
MONTHS_FORECAST = ["Sep", "Okt", "Nov", "Des"]


def fmt(v, decimals=4):
    if v is None:
        return "None"
    if isinstance(v, (int, float)):
        return f"{v:,.{decimals}f}"
    return str(v)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def pct_diff(actual, benchmark):
    if benchmark in (None, 0):
        return None
    return (actual - benchmark) / benchmark * 100.0


def analytic_normal(actual_total, means, sigmas):
    mu = float(actual_total) + sum(float(x) for x in means)
    sigma = math.sqrt(sum(float(x) ** 2 for x in sigmas))
    return {
        "p5": mu - Z_05 * sigma,
        "p50": mu,
        "p95": mu + Z_05 * sigma,
        "sigma_total": sigma,
    }


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python audit_crystal_ball_penjualan_agustus_2026_v1_readonly.py <source.xlsx>")

    source = Path(sys.argv[1]).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"SOURCE NOT FOUND: {source}")

    print("=" * 132)
    print("READ ONLY AUDIT — CRYSTAL BALL PENJUALAN / PENDAPATAN AGUSTUS 2026")
    print("=" * 132)
    print(f"SOURCE : {source}")
    print(f"SIZE   : {source.stat().st_size}")
    print(f"SHA256 : {sha256(source)}")

    # data_only=True is intentional: use the cached values produced by Excel/Crystal Ball.
    wb = load_workbook(source, data_only=True, read_only=False)
    required = {"Dashboard", "Niaga", "CB_DATA_"}
    missing = required - set(wb.sheetnames)
    print(f"SHEETS : {wb.sheetnames}")
    if missing:
        raise SystemExit(f"STOP: required sheets missing: {sorted(missing)}")

    niaga = wb["Niaga"]
    dash = wb["Dashboard"]
    cb = wb["CB_DATA_"]

    print("\nA. CRYSTAL BALL MARKER")
    print("-" * 132)
    print(f"CB_DATA_!P2 : {cb['P2'].value!r}  (workbook marker; model run is expected around 10,000 trials)")

    print("\nB. ACTUAL 2026 — WORKBOOK SNAPSHOT")
    print("-" * 132)
    print(f"{'MONTH':<8}{'SALES kWh':>22}{'REVENUE Rp':>28}{'HJR Rp/kWh':>20}")
    sales_actual = []
    revenue_actual = []
    hjr_actual = []
    for idx, row in enumerate(range(89, 97)):
        s = niaga[f"Y{row}"].value
        r = niaga[f"AK{row}"].value
        h = niaga[f"P{row}"].value
        sales_actual.append(float(s))
        revenue_actual.append(float(r))
        hjr_actual.append(float(h))
        print(f"{MONTHS_ACTUAL[idx]:<8}{s:>22,.4f}{r:>28,.4f}{h:>20,.6f}")

    sales_ytd = sum(sales_actual)
    revenue_ytd = sum(revenue_actual)
    print("-" * 132)
    print(f"YTD SALES   : {sales_ytd:,.4f} | Dashboard={dash['C4'].value:,.4f}")
    print(f"YTD REVENUE : {revenue_ytd:,.4f} | Dashboard={dash['C5'].value:,.4f}")
    print(f"AUG HJR     : {hjr_actual[-1]:,.6f} | Dashboard={dash['C6'].value:,.6f}")

    print("\nC. FORECAST ASSUMPTIONS SEP–DEC — CACHED MODEL INPUT")
    print("-" * 132)
    print("SALES — Normal(mean=P50, sigma=STDEV=P50-P15.865254)")
    print(f"{'MONTH':<8}{'P50/MEAN':>22}{'P15.865254':>22}{'STDEV':>22}{'CHECK':>14}")
    sales_means, sales_sigmas = [], []
    for idx, row in enumerate(range(97, 101)):
        mean_v = float(niaga[f"AA{row}"].value)
        p15_v = float(niaga[f"AB{row}"].value)
        sd_v = float(niaga[f"AC{row}"].value)
        sales_means.append(mean_v)
        sales_sigmas.append(sd_v)
        ok = abs((mean_v - p15_v) - sd_v) <= max(1.0, abs(sd_v) * 1e-9)
        print(f"{MONTHS_FORECAST[idx]:<8}{mean_v:>22,.4f}{p15_v:>22,.4f}{sd_v:>22,.4f}{('PASS' if ok else 'REVIEW'):>14}")

    print("\nREVENUE — Normal(mean=P50, sigma=STDEV=P50-P15.865254)")
    print(f"{'MONTH':<8}{'P50/MEAN':>28}{'P15.865254':>28}{'STDEV':>24}{'CHECK':>14}")
    revenue_means, revenue_sigmas = [], []
    for idx, row in enumerate(range(97, 101)):
        mean_v = float(niaga[f"AM{row}"].value)
        p15_v = float(niaga[f"AN{row}"].value)
        sd_v = float(niaga[f"AO{row}"].value)
        revenue_means.append(mean_v)
        revenue_sigmas.append(sd_v)
        ok = abs((mean_v - p15_v) - sd_v) <= max(1.0, abs(sd_v) * 1e-9)
        print(f"{MONTHS_FORECAST[idx]:<8}{mean_v:>28,.4f}{p15_v:>28,.4f}{sd_v:>24,.4f}{('PASS' if ok else 'REVIEW'):>14}")

    print("\nD. CRYSTAL BALL BENCHMARK")
    print("-" * 132)
    benchmarks = {
        "sales": {"p95": float(niaga['Y117'].value), "p50": float(niaga['Y118'].value), "p5": float(niaga['Y119'].value), "target": float(niaga['Y121'].value)},
        "revenue": {"p95": float(niaga['AA117'].value), "p50": float(niaga['AA118'].value), "p5": float(niaga['AA119'].value), "target": float(niaga['AA121'].value)},
        "hjr": {"p95": float(niaga['AB117'].value), "p50": float(niaga['AB118'].value), "p5": float(niaga['AB119'].value), "target": float(niaga['AB121'].value)},
    }
    for key, label in (("sales", "SALES"), ("revenue", "REVENUE"), ("hjr", "HJR")):
        b = benchmarks[key]
        print(f"{label:<10} TARGET={fmt(b['target'], 6)} | P5={fmt(b['p5'], 6)} | P50={fmt(b['p50'], 6)} | P95={fmt(b['p95'], 6)}")

    print("\nE. ANALYTICAL NORMAL CROSS-CHECK")
    print("-" * 132)
    for key, actual_total, means, sigmas in (
        ("sales", sales_ytd, sales_means, sales_sigmas),
        ("revenue", revenue_ytd, revenue_means, revenue_sigmas),
    ):
        a = analytic_normal(actual_total, means, sigmas)
        b = benchmarks[key]
        print(f"{key.upper()}")
        print(f"  Aggregate sigma : {a['sigma_total']:,.6f}")
        for p in ("p5", "p50", "p95"):
            diff = a[p] - b[p]
            pd = pct_diff(a[p], b[p])
            print(f"  {p.upper():<4} analytical={a[p]:,.6f} | CB={b[p]:,.6f} | diff={diff:,.6f} | diff%={pd:.6f}%")

    print("\nF. IMPACT / PROBABILITY REFERENCE")
    print("-" * 132)
    cb_worst_impact = benchmarks['revenue']['target'] - benchmarks['revenue']['p5']
    print(f"Worst-case revenue impact = Target Revenue - Revenue P5 = {cb_worst_impact:,.4f}")
    print(f"Dashboard impact          = {dash['G4'].value:,.4f}")
    print(f"Workbook likelihood ref   = Sales={niaga['Y125'].value!r}; Revenue={niaga['AA125'].value!r}")
    print("NOTE: workbook text says graph approaches 100%; 0.95 is therefore treated as a reference cell, not authoritative Monte Carlo probability.")

    print("\nG. MODEL SEMANTICS CHECK")
    print("-" * 132)
    print("PASS: Sales and Revenue are annual SUM metrics (actual YTD + Sep-Dec simulated monthly values).")
    print("PASS: HJR is a RATE/RATIO metric and MUST NOT be summed across months.")
    print(f"AUG ratio check Revenue/Sales = {revenue_actual[-1] / sales_actual[-1]:,.6f}; workbook HJR={hjr_actual[-1]:,.6f}")
    print("ACTION: ERM needs aggregation semantics (SUM vs RATIO/RATE) before Risk #3 can be validated correctly.")

    print("\n" + "=" * 132)
    print("READ ONLY AUDIT COMPLETE — NO DATABASE WRITE / NO WORKBOOK WRITE")
    print("=" * 132)


if __name__ == "__main__":
    main()
