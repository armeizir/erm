from __future__ import annotations

import hashlib
import math
import random
import statistics
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

from corporate_risk.models import (
    MonteCarloMetricHistory,
    MultiMetricMonteCarloResult,
    RiskMetric,
)
from risk.models import ProfilRisikoKorporatItem


YEAR = 2026
TRIALS = 10_000
SEED = 20260909
Z95 = 1.6448536269514722
DEFAULT_PATH = "/tmp/05_KK_RISIKO_Gangguan_Padam_System_Agustus_2026.xlsx"

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def percentile(values, p):
    a = sorted(float(x) for x in values)
    if not a:
        return 0.0
    pos = (len(a) - 1) * p
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return a[lo]
    frac = pos - lo
    return a[lo] + (a[hi] - a[lo]) * frac


def normal_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def sample_skew(values):
    x = [float(v) for v in values]
    n = len(x)
    if n < 3:
        return 0.0
    mean = statistics.mean(x)
    sd = statistics.stdev(x)
    if sd == 0:
        return 0.0
    return (
        n
        / ((n - 1) * (n - 2))
        * sum(((v - mean) / sd) ** 3 for v in x)
    )


def pearson(xs, ys):
    xs = [float(x) for x in xs]
    ys = [float(y) for y in ys]
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mx = statistics.mean(xs)
    my = statistics.mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


class XlsxCached:
    """Minimal cached-value XLSX reader. READ ONLY. Does not evaluate formulas."""

    def __init__(self, path):
        self.path = Path(path)
        self.zf = ZipFile(self.path)
        self.shared_strings = []
        if "xl/sharedStrings.xml" in self.zf.namelist():
            root = ET.fromstring(self.zf.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{{{NS_MAIN}}}si"):
                self.shared_strings.append(
                    "".join((t.text or "") for t in si.iter(f"{{{NS_MAIN}}}t"))
                )

        wb = ET.fromstring(self.zf.read("xl/workbook.xml"))
        rels_root = ET.fromstring(self.zf.read("xl/_rels/workbook.xml.rels"))
        rels = {node.attrib["Id"]: node.attrib["Target"] for node in rels_root}
        ns = {"m": NS_MAIN, "r": NS_REL}
        self.sheet_paths = {}
        for sh in wb.find("m:sheets", ns):
            rid = sh.attrib[f"{{{NS_REL}}}id"]
            target = rels[rid]
            xml_path = target.lstrip("/") if target.startswith("/") else "xl/" + target.lstrip("/")
            self.sheet_paths[sh.attrib["name"]] = xml_path
        self._cache = {}

    def _load_sheet(self, sheet):
        if sheet in self._cache:
            return self._cache[sheet]
        root = ET.fromstring(self.zf.read(self.sheet_paths[sheet]))
        cells = {}
        for c in root.iter(f"{{{NS_MAIN}}}c"):
            ref = c.attrib["r"]
            typ = c.attrib.get("t")
            vnode = c.find(f"{{{NS_MAIN}}}v")
            fnode = c.find(f"{{{NS_MAIN}}}f")
            formula = fnode.text if fnode is not None else None
            value = None

            if typ == "s" and vnode is not None:
                try:
                    value = self.shared_strings[int(vnode.text)]
                except Exception:
                    value = vnode.text
            elif typ == "inlineStr":
                value = "".join((t.text or "") for t in c.iter(f"{{{NS_MAIN}}}t"))
            elif typ in ("str", "e") and vnode is not None:
                value = vnode.text
            elif typ == "b" and vnode is not None:
                value = bool(int(vnode.text))
            elif vnode is not None:
                try:
                    raw = float(vnode.text)
                    value = int(raw) if raw.is_integer() else raw
                except Exception:
                    value = vnode.text
            cells[ref] = (value, formula)
        self._cache[sheet] = cells
        return cells

    def value(self, sheet, ref, default=None):
        return self._load_sheet(sheet).get(ref, (default, None))[0]


def simulate_independent_normal(actual_ytd, means, sds, floor_zero):
    rng = random.Random(SEED)
    totals = []
    for _ in range(TRIALS):
        total = float(actual_ytd)
        for mean, sd in zip(means, sds):
            x = rng.gauss(float(mean), abs(float(sd)))
            if floor_zero:
                x = max(x, 0.0)
            total += x
        totals.append(total)
    return {
        "p5": percentile(totals, 0.05),
        "p50": percentile(totals, 0.50),
        "p95": percentile(totals, 0.95),
        "prob_gt": sum(1 for x in totals if x > TARGET) / len(totals),
    }


def compound_poisson(means, sds, lambdas, actual_ytd, severity_dist):
    rng = random.Random(SEED)
    totals = []
    params = []

    # Moment-match each monthly compound Poisson:
    # E[T] = lambda * E[S]
    # Var[T] = lambda * E[S^2]
    for mean, sd, lam in zip(means, sds, lambdas):
        lam = max(float(lam), 1e-9)
        msev = float(mean) / lam
        cv2 = (float(sd) ** 2 * lam / (float(mean) ** 2)) - 1.0
        params.append((lam, msev, cv2))

    for _ in range(TRIALS):
        total = float(actual_ytd)
        for lam, msev, cv2 in params:
            # Knuth Poisson, fine for lambda ~2.33
            L = math.exp(-lam)
            k = 0
            p = 1.0
            while p > L:
                k += 1
                p *= rng.random()
            n = k - 1

            if cv2 <= 0:
                total += n * msev
                continue

            if severity_dist == "gamma":
                shape = 1.0 / cv2
                scale = msev / shape
                for __ in range(n):
                    total += rng.gammavariate(shape, scale)
            elif severity_dist == "lognormal":
                sigma2 = math.log1p(cv2)
                sigma = math.sqrt(sigma2)
                mu = math.log(max(msev, 1e-12)) - sigma2 / 2.0
                for __ in range(n):
                    total += rng.lognormvariate(mu, sigma)
            else:
                raise ValueError(severity_dist)

        totals.append(total)

    return {
        "p5": percentile(totals, 0.05),
        "p50": percentile(totals, 0.50),
        "p95": percentile(totals, 0.95),
        "prob_gt": sum(1 for x in totals if x > TARGET) / len(totals),
    }, params


def mixture_cdf(y, mu, sigma, q, shock):
    base = normal_cdf((y - mu) / sigma)
    shifted = normal_cdf((y - shock - mu) / sigma)
    return (1.0 - q) * base + q * shifted


def mixture_quantile(p, mu, sigma, q, shock):
    lo = mu - 7.0 * sigma
    hi = mu + shock + 7.0 * sigma
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if mixture_cdf(mid, mu, sigma, q, shock) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def best_one_sided_shock(mu, sigma, cb, target):
    best = None
    for q_i in range(1, 21):  # 1% .. 20%
        q = q_i / 100.0
        for s_i in range(1, 81):  # Rp0.05b .. Rp4.0b
            shock = s_i * 50_000_000.0
            p5 = mixture_quantile(0.05, mu, sigma, q, shock)
            p50 = mixture_quantile(0.50, mu, sigma, q, shock)
            p95 = mixture_quantile(0.95, mu, sigma, q, shock)
            prob = 1.0 - mixture_cdf(target, mu, sigma, q, shock)

            err = (
                ((p5 - cb["p5"]) / cb["p5"]) ** 2
                + ((p50 - cb["p50"]) / cb["p50"]) ** 2
                + ((p95 - cb["p95"]) / cb["p95"]) ** 2
                + ((prob - cb["prob"]) / 0.10) ** 2
            )
            row = (err, q, shock, p5, p50, p95, prob)
            if best is None or row[0] < best[0]:
                best = row
    return best


arg_path = None
for arg in sys.argv[1:]:
    if arg.lower().endswith(".xlsx"):
        arg_path = arg
        break

path = Path(arg_path or DEFAULT_PATH)
if not path.exists():
    raise SystemExit(f"STOP: workbook tidak ditemukan: {path}")

x = XlsxCached(path)
SHEET = "Gangguan (2)"

# Historical Jan-2024 to Aug-2026 = rows 5:36
hist_dates = []
hist_comp = []
hist_count = []

for r in range(5, 37):
    serial = x.value(SHEET, f"A{r}")
    comp = x.value(SHEET, f"B{r}")
    count = x.value(SHEET, f"C{r}")

    if serial is None:
        continue

    dt = datetime(1899, 12, 30) + timedelta(days=float(serial))
    hist_dates.append(dt.date())
    hist_comp.append(float(comp or 0.0))

    try:
        hist_count.append(float(count))
    except Exception:
        hist_count.append(0.0)

# 2026 actual Jan-Aug = rows 29:36
actual_2026 = [float(x.value(SHEET, f"B{r}") or 0.0) for r in range(29, 37)]
actual_ytd = sum(actual_2026)

# Forecast Sep-Dec = rows 47:50
means = [float(x.value(SHEET, f"B{r}") or 0.0) for r in range(47, 51)]
p1586 = [float(x.value(SHEET, f"C{r}") or 0.0) for r in range(47, 51)]
sds = [float(x.value(SHEET, f"D{r}") or 0.0) for r in range(47, 51)]

# Forecast feeder counts appear rows 37:40 in col C (2.3333 each)
forecast_counts = [float(x.value(SHEET, f"C{r}") or 0.0) for r in range(37, 41)]
if not all(v > 0 for v in forecast_counts):
    forecast_counts = [2.3333333333333335] * 4

CB = {
    "p5": float(x.value(SHEET, "G47")),
    "p50": float(x.value(SHEET, "G48")),
    "p95": float(x.value(SHEET, "G49")),
    "target": float(x.value(SHEET, "G51")),
    "prob": float(x.value(SHEET, "G55")),
}
TARGET = CB["target"]

positive = [v for v in hist_comp if v > 0]
zero_count = sum(1 for v in hist_comp if v <= 0)

severity_per_feeder = [
    comp / cnt
    for comp, cnt in zip(hist_comp, hist_count)
    if comp > 0 and cnt > 0
]
severe_months = [v for v in hist_comp if v >= 1_000_000_000]

# Analytical independent Normal, no zero floor
mu_total = actual_ytd + sum(means)
sigma_total = math.sqrt(sum(sd * sd for sd in sds))
analytical = {
    "p5": mu_total - Z95 * sigma_total,
    "p50": mu_total,
    "p95": mu_total + Z95 * sigma_total,
    "prob_gt": 1.0 - normal_cdf((TARGET - mu_total) / sigma_total),
}

# stochastic comparisons
no_floor = simulate_independent_normal(actual_ytd, means, sds, floor_zero=False)
with_floor = simulate_independent_normal(actual_ytd, means, sds, floor_zero=True)
gamma_model, gamma_params = compound_poisson(
    means, sds, forecast_counts, actual_ytd, "gamma"
)
lognormal_model, lognormal_params = compound_poisson(
    means, sds, forecast_counts, actual_ytd, "lognormal"
)

best_shock = best_one_sided_shock(
    mu_total,
    sigma_total,
    {"p5": CB["p5"], "p50": CB["p50"], "p95": CB["p95"], "prob": CB["prob"]},
    TARGET,
)

risk = (
    ProfilRisikoKorporatItem.objects
    .filter(summary__tahun=YEAR, no_risiko=5)
    .first()
)

print("=" * 154)
print("READ ONLY AUDIT — RISK #5 FREQUENCY / SEVERITY / UPPER-TAIL V4.4")
print("=" * 154)
print(f"SOURCE   : {path.resolve()}")
print(f"SHA256   : {sha256(path)}")
print(f"TRIALS   : {TRIALS:,}")
print(f"RNG SEED : {SEED}")
print("DB WRITE : NONE")
print()

print("A. ERM CURRENT CONFIGURATION")
print("-" * 154)
if risk:
    print(f"RISK : #{risk.no_risiko} ID={risk.id} | {risk.peristiwa_risiko}")
    metrics = RiskMetric.objects.filter(corporate_risk_item=risk).order_by("id")
    for metric in metrics:
        last = (
            MonteCarloMetricHistory.objects
            .filter(metric=metric)
            .order_by("-tanggal_data", "-id")
            .first()
        )
        print(
            f"METRIC ID={metric.id} | {metric.name} | UNIT={metric.unit}"
            f" | DIR={metric.direction} | AGG={metric.aggregation_type}"
            f" | TARGET={metric.effective_target_value}"
            f" | LAST={last.tanggal_data if last else None}"
            f" | LAST VALUE={last.metric_value if last else None}"
        )
    latest = (
        MultiMetricMonteCarloResult.objects
        .filter(corporate_risk_item=risk)
        .order_by("-created_at")
        .first()
    )
    if latest:
        print(
            f"LATEST MC RESULT ID={latest.id} | P5={latest.worst_case_value}"
            f" | P50={latest.baseline_value} | P95={latest.best_case_value}"
            f" | PROB={latest.probability_not_achieve_target}"
        )
else:
    print("RISK #5 tidak ditemukan di database.")

print()
print("B. HISTORICAL FREQUENCY / SEVERITY 2024-01 s.d. 2026-08")
print("-" * 154)
print(f"MONTHS                      : {len(hist_comp)}")
print(f"ZERO-COMP MONTHS            : {zero_count} ({zero_count/len(hist_comp)*100:.2f}%)")
print(f"POSITIVE-COMP MONTHS        : {len(positive)} ({len(positive)/len(hist_comp)*100:.2f}%)")
print(f"MONTHLY COMP MEAN           : Rp {statistics.mean(hist_comp):,.2f}")
print(f"MONTHLY COMP MEDIAN         : Rp {statistics.median(hist_comp):,.2f}")
print(f"MONTHLY COMP STDEV          : Rp {statistics.stdev(hist_comp):,.2f}")
print(f"MONTHLY COMP SKEWNESS       : {sample_skew(hist_comp):.4f}")
print(f"MAX MONTHLY COMP            : Rp {max(hist_comp):,.2f}")
print()
print(f"FEEDER COUNT MEAN           : {statistics.mean(hist_count):.4f}")
print(f"FEEDER COUNT MEDIAN         : {statistics.median(hist_count):.4f}")
print(f"FEEDER COUNT STDEV          : {statistics.stdev(hist_count):.4f}")
print(f"CORR(FEEDER, COMPENSATION)  : {pearson(hist_count, hist_comp):.4f}")
print()
print(f"POSITIVE MONTH SEVERITY MEAN: Rp {statistics.mean(positive):,.2f}")
print(f"POSITIVE MONTH SEVERITY MED : Rp {statistics.median(positive):,.2f}")
print(f"POSITIVE MONTH SKEWNESS     : {sample_skew(positive):.4f}")
print()
print(f"SEVERITY PER FEEDER MEAN    : Rp {statistics.mean(severity_per_feeder):,.2f}")
print(f"SEVERITY PER FEEDER MEDIAN  : Rp {statistics.median(severity_per_feeder):,.2f}")
print(f"SEVERITY PER FEEDER SKEW    : {sample_skew(severity_per_feeder):.4f}")
print()
print(f"SEVERE MONTHS >= Rp1B       : {len(severe_months)} / {len(hist_comp)} ({len(severe_months)/len(hist_comp)*100:.2f}%)")
if severe_months:
    print(f"SEVERE MONTH MEDIAN         : Rp {statistics.median(severe_months):,.2f}")
    print(f"SEVERE MONTH MEAN           : Rp {statistics.mean(severe_months):,.2f}")

print()
print("C. WORKBOOK FORECAST ASSUMPTIONS SEP-DEC")
print("-" * 154)
for idx, (mean, p15, sd, cnt) in enumerate(zip(means, p1586, sds, forecast_counts), start=9):
    pneg = normal_cdf(-mean / sd) * 100 if sd else 0.0
    print(
        f"2026-{idx:02d} | MEAN={mean:,.2f} | P15.86={p15:,.2f}"
        f" | SD={sd:,.2f} | FEEDER FORECAST={cnt:.4f}"
        f" | P(Normal monthly < 0)={pneg:.2f}%"
    )

print()
print("D. CRYSTAL BALL BENCHMARK")
print("-" * 154)
print(f"ACTUAL JAN-AUG YTD : Rp {actual_ytd:,.2f}")
print(f"P5 / BEST          : Rp {CB['p5']:,.2f}")
print(f"P50 / BASELINE     : Rp {CB['p50']:,.2f}")
print(f"P95 / WORST        : Rp {CB['p95']:,.2f}")
print(f"TARGET             : Rp {TARGET:,.2f}")
print(f"P(RISK > TARGET)   : {CB['prob']*100:.4f}%")

print()
print("E. BASELINE INDEPENDENT NORMAL — NO ZERO FLOOR")
print("-" * 154)
print(
    f"ANALYTICAL P5  = Rp {analytical['p5']:,.2f}"
    f" | diff={(analytical['p5']-CB['p5'])/CB['p5']*100:+.4f}%"
)
print(
    f"ANALYTICAL P50 = Rp {analytical['p50']:,.2f}"
    f" | diff={(analytical['p50']-CB['p50'])/CB['p50']*100:+.4f}%"
)
print(
    f"ANALYTICAL P95 = Rp {analytical['p95']:,.2f}"
    f" | diff={(analytical['p95']-CB['p95'])/CB['p95']*100:+.4f}%"
)
print(
    f"ANALYTICAL P(RISK)={analytical['prob_gt']*100:.4f}%"
    f" | CB={CB['prob']*100:.4f}%"
    f" | diff={(analytical['prob_gt']-CB['prob'])*100:+.4f} pp"
)
print()
print(
    f"STOCHASTIC NO-FLOOR P5/P50/P95 = "
    f"{no_floor['p5']:,.2f} | {no_floor['p50']:,.2f} | {no_floor['p95']:,.2f}"
)
print(f"STOCHASTIC NO-FLOOR P(RISK)     = {no_floor['prob_gt']*100:.4f}%")
print()
print("INTERPRETATION:")
print("  - P5, P50, dan probability sangat dekat dengan Crystal Ball.")
print("  - P95 Crystal Ball jauh lebih berat daripada symmetric independent Normal.")
print("  - Ini menunjukkan one-sided upper-tail component, bukan sekadar correlation symmetric.")

print()
print("F. CURRENT ERM ZERO-FLOOR EFFECT")
print("-" * 154)
print(
    f"WITH FLOOR P5/P50/P95 = "
    f"{with_floor['p5']:,.2f} | {with_floor['p50']:,.2f} | {with_floor['p95']:,.2f}"
)
print(f"WITH FLOOR P(RISK)     = {with_floor['prob_gt']*100:.4f}%")
print(
    f"NO FLOOR  P5/P50/P95  = "
    f"{no_floor['p5']:,.2f} | {no_floor['p50']:,.2f} | {no_floor['p95']:,.2f}"
)
print(f"NO FLOOR  P(RISK)      = {no_floor['prob_gt']*100:.4f}%")
print("NOTE: zero-floor materially menggeser median/probability dan tidak mereplikasi workbook Risk #5.")

print()
print("G. COMPOUND FREQUENCY / SEVERITY CANDIDATES")
print("-" * 154)
print("Moment-matched compound Poisson using workbook feeder forecast as lambda.")
print("This is a diagnostic candidate only; not a production model.")
print()
print(
    f"GAMMA    P5/P50/P95 = "
    f"{gamma_model['p5']:,.2f} | {gamma_model['p50']:,.2f} | {gamma_model['p95']:,.2f}"
    f" | P(RISK)={gamma_model['prob_gt']*100:.4f}%"
)
print(
    f"LOGNORMAL P5/P50/P95 = "
    f"{lognormal_model['p5']:,.2f} | {lognormal_model['p50']:,.2f} | {lognormal_model['p95']:,.2f}"
    f" | P(RISK)={lognormal_model['prob_gt']*100:.4f}%"
)
print()
for month, params in zip(("Sep", "Okt", "Nov", "Des"), gamma_params):
    lam, msev, cv2 = params
    print(
        f"{month}: lambda={lam:.4f} | implied mean severity/event=Rp {msev:,.2f}"
        f" | severity CV={math.sqrt(max(cv2,0)):.4f}"
    )
print()
print("INTERPRETATION:")
print("  - Pure compound Poisson Gamma/Lognormal mengubah P5/P50 sekaligus dan masih belum mereplikasi upper tail CB dengan baik.")
print("  - Jadi mengganti SARIMA baseline sepenuhnya dengan frequency-severity juga belum justified.")

print()
print("H. ONE-SIDED UPPER-TAIL SHOCK DIAGNOSTIC")
print("-" * 154)
baseline_upper = analytical["p95"]
excess = CB["p95"] - baseline_upper
print(f"BASELINE NORMAL P95           : Rp {baseline_upper:,.2f}")
print(f"CRYSTAL BALL P95             : Rp {CB['p95']:,.2f}")
print(f"EXCESS UPPER TAIL            : Rp {excess:,.2f}")
if severe_months:
    print(f"HISTORICAL SEVERE MONTH MED  : Rp {statistics.median(severe_months):,.2f}")
    print(f"HISTORICAL SEVERE MONTH RATE : {len(severe_months)/len(hist_comp)*100:.2f}%")

err, q, shock, p5s, p50s, p95s, probs = best_shock
print()
print("BEST SIMPLE ANNUAL BERNOULLI-SHOCK FIT (DIAGNOSTIC ONLY)")
print(f"Shock probability            : {q*100:.2f}%")
print(f"Shock amount                 : Rp {shock:,.2f}")
print(f"P5                            : Rp {p5s:,.2f}")
print(f"P50                           : Rp {p50s:,.2f}")
print(f"P95                           : Rp {p95s:,.2f}")
print(f"P(RISK)                       : {probs*100:.4f}%")
print("NOTE: jika model shock harus menggeser P50/probability untuk mengejar P95, benchmark saja belum cukup untuk mengidentifikasi model yang benar.")

print()
print("I. DECISION")
print("-" * 154)
p5_diff = abs((analytical["p5"] - CB["p5"]) / CB["p5"] * 100)
p50_diff = abs((analytical["p50"] - CB["p50"]) / CB["p50"] * 100)
p95_diff = abs((analytical["p95"] - CB["p95"]) / CB["p95"] * 100)
prob_diff_pp = abs((analytical["prob_gt"] - CB["prob"]) * 100)

print(f"Baseline P5 diff       : {p5_diff:.4f}%")
print(f"Baseline P50 diff      : {p50_diff:.4f}%")
print(f"Baseline P95 diff      : {p95_diff:.4f}%")
print(f"Baseline probability   : {prob_diff_pp:.4f} pp")
print()
print("MODEL DIAGNOSIS:")
if p5_diff < 0.5 and p50_diff < 0.1 and prob_diff_pp < 0.5 and p95_diff > 3.0:
    print("PASS DIAGNOSIS — SARIMA/Normal baseline menjelaskan P5/P50/probability, tetapi tidak upper tail P95.")
    print("UPPER-TAIL MODEL IS NOT IDENTIFIED YET.")
else:
    print("REVIEW — pola tidak cukup kuat untuk diagnosis baseline + upper-tail component.")

print()
print("SAFE RECOMMENDATION:")
print("  1. JANGAN import Risk #5 sebagai correlated Normal.")
print("  2. JANGAN aktifkan zero-floor bila tujuan validasi adalah mereplikasi workbook Crystal Ball.")
print("  3. Simpan workbook P95 sebagai external/reference worst-case sementara.")
print("  4. Untuk production ERM, minta/definisikan driver upper-tail yang eksplisit:")
print("       - severe blackout / meluas,")
print("       - jumlah pelanggan premium terdampak,")
print("       - durasi padam,")
print("       - feeder/event frequency,")
print("       - kompensasi per event / severity.")
print("  5. Setelah driver disepakati, baru buat V4.4 compound/hurdle model dan validasi kembali.")
print()
print("=" * 154)
print("READ ONLY AUDIT COMPLETE — NO DATABASE WRITE")
print("=" * 154)
