from __future__ import annotations

import glob
import hashlib
import math
import random
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

from corporate_risk.models import MonteCarloMetricHistory, RiskMetric
from risk.models import ProfilRisikoKorporatItem


YEAR = 2026
TRIALS = 10_000
SEED = 20260909
Z95 = 1.6448536269514722

DEFAULT_FILES = {
    4: "/tmp/04_KK_RISIKO_Pendapatan_Off_Grid_Agustus_2026.xlsx",
    5: "/tmp/05_KK_RISIKO_Gangguan_Padam_System_Agustus_2026.xlsx",
    8: "/tmp/08_KK_RISIKO_Kehandalan_KIT_MPP_Agustus_2026.xlsx",
    9: "/tmp/09_10_KK_RISIKO_VOLUME_HARGA_Gas_Agustus_2026.xlsx",
}

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def pct(values, p):
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


class XlsxCached:
    """Minimal XLSX cached-value reader. READ ONLY; does not evaluate formulas."""

    def __init__(self, path):
        self.path = Path(path)
        self.zf = ZipFile(self.path)
        self.ss = []
        if "xl/sharedStrings.xml" in self.zf.namelist():
            root = ET.fromstring(self.zf.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{{{NS_MAIN}}}si"):
                self.ss.append(
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
            if target.startswith("/"):
                xml_path = target.lstrip("/")
            else:
                xml_path = "xl/" + target.lstrip("/")
            self.sheet_paths[sh.attrib["name"]] = xml_path
        self._cache = {}

    @property
    def sheetnames(self):
        return list(self.sheet_paths)

    def _load_sheet(self, sheet):
        if sheet in self._cache:
            return self._cache[sheet]
        if sheet not in self.sheet_paths:
            raise KeyError(f"Sheet tidak ditemukan: {sheet}")
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
                    value = self.ss[int(vnode.text)]
                except Exception:
                    value = vnode.text
            elif typ == "inlineStr":
                value = "".join(
                    (t.text or "") for t in c.iter(f"{{{NS_MAIN}}}t")
                )
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

    def formula(self, sheet, ref):
        return self._load_sheet(sheet).get(ref, (None, None))[1]


def resolve_file(default_path, alternatives):
    p = Path(default_path)
    if p.exists():
        return p
    for pat in alternatives:
        hits = sorted(glob.glob(pat))
        if hits:
            return Path(hits[0])
    return p


def simulate_sum(actuals, means, sds, target, risk_when, floor_zero=True, seed=SEED):
    rng = random.Random(seed)
    actual_total = float(sum(actuals))
    totals = []
    for _ in range(TRIALS):
        total = actual_total
        for mean, sd in zip(means, sds):
            x = rng.gauss(float(mean), abs(float(sd)))
            if floor_zero:
                x = max(x, 0.0)
            total += x
        totals.append(total)

    p5 = pct(totals, 0.05)
    p50 = pct(totals, 0.50)
    p95 = pct(totals, 0.95)
    if risk_when == "below":
        probability = sum(1 for x in totals if x < target) / len(totals) * 100
    else:
        probability = sum(1 for x in totals if x > target) / len(totals) * 100
    return {"p5": p5, "p50": p50, "p95": p95, "prob_risk": probability}


def simulate_rate_average(actuals, means, sds, target, seed=SEED):
    rng = random.Random(seed)
    totals = []
    for _ in range(TRIALS):
        future = [rng.gauss(float(m), abs(float(s))) for m, s in zip(means, sds)]
        totals.append((sum(float(x) for x in actuals) + sum(future)) / (len(actuals) + len(future)))
    return {
        "p5": pct(totals, 0.05),
        "p50": pct(totals, 0.50),
        "p95": pct(totals, 0.95),
        "prob_risk": sum(1 for x in totals if x > target) / len(totals) * 100,
    }


def diff_pct(value, benchmark):
    if not benchmark:
        return 0.0
    return (float(value) - float(benchmark)) / float(benchmark) * 100.0


def print_compare(title, erm, benchmark, labels=("P5", "P50", "P95")):
    print(title)
    print(f"{'PCTL':<6}{'ERM MODEL':>24}{'WORKBOOK':>24}{'DIFF %':>14}{'STATUS':>12}")
    for key, label in zip(("p5", "p50", "p95"), labels):
        d = diff_pct(erm[key], benchmark[key])
        status = "PASS" if abs(d) <= 0.05 else "REVIEW"
        print(f"{label:<6}{erm[key]:>24,.6f}{benchmark[key]:>24,.6f}{d:>13,.6f}%{status:>12}")


def db_risk(no):
    risk = (
        ProfilRisikoKorporatItem.objects
        .filter(summary__tahun=YEAR, no_risiko=no)
        .first()
    )
    if not risk:
        return None
    metrics = list(
        RiskMetric.objects
        .filter(corporate_risk_item=risk)
        .order_by("id")
    )
    return risk, metrics


def show_db_mapping(no):
    obj = db_risk(no)
    if not obj:
        print(f"RISK #{no}: TIDAK DITEMUKAN DI ERM")
        return
    risk, metrics = obj
    print(f"RISK #{no} | ID={risk.id} | {risk.peristiwa_risiko}")
    for m in metrics:
        h = (
            MonteCarloMetricHistory.objects
            .filter(metric=m)
            .order_by("-tanggal_data", "-id")
            .first()
        )
        agg = getattr(m, "aggregation_type", "legacy")
        print(
            f"  METRIC ID={m.id} | {m.name} | UNIT={m.unit} | DIR={m.direction} "
            f"| AGG={agg} | TARGET={m.effective_target_value} | ACTIVE={m.is_active} "
            f"| TARGET_METRIC={m.is_target_metric} | LAST={h.tanggal_data if h else None} "
            f"| LAST_VALUE={h.metric_value if h else None}"
        )


paths = {
    4: resolve_file(
        DEFAULT_FILES[4],
        ["/tmp/*Pendapatan*Off*Grid*Agustus*2026*.xlsx", "/tmp/*Pedapatan*Off*Grid*Agustus*2026*.xlsx"],
    ),
    5: resolve_file(
        DEFAULT_FILES[5],
        ["/tmp/*Gangguan*Padam*System*Agustus*2026*.xlsx"],
    ),
    8: resolve_file(
        DEFAULT_FILES[8],
        ["/tmp/*Kehandalan*KIT*MPP*Agustus*2026*.xlsx"],
    ),
    9: resolve_file(
        DEFAULT_FILES[9],
        ["/tmp/*VOLUME*HARGA*Gas*Agustus*2026*.xlsx", "/tmp/*VOLUME*dan*HARGA*Gas*Agustus*2026*.xlsx"],
    ),
}

missing = [str(p) for p in paths.values() if not p.exists()]
if missing:
    print("SOURCE FILE BELUM ADA:")
    for p in missing:
        print(" -", p)
    raise SystemExit("STOP: copy empat workbook ke /tmp sesuai instruksi sebelum audit.")

print("=" * 150)
print("READ ONLY AUDIT — 4 RISK MODEL AGUSTUS 2026 vs ERM")
print("=" * 150)
print(f"TRIALS={TRIALS:,} | SEED={SEED} | DATABASE WRITE=NO")
for no, p in paths.items():
    print(f"RISK FILE #{no}: {p.name} | SHA256={sha256(p)}")

print()
print("A. ERM CURRENT MAPPING")
print("-" * 150)
for no in (4, 5, 8, 9, 10):
    show_db_mapping(no)

# ----------------------------------------------------------------------------------------------------------------------
# RISK #4
# ----------------------------------------------------------------------------------------------------------------------
x4 = XlsxCached(paths[4])
s4 = "Revenue Luar Batam Data Standar"
actual4 = [float(x4.value(s4, f"AE{r}") or 0) for r in range(29, 37)]
means4 = [float(x4.value(s4, f"AG{r}") or 0) for r in range(37, 41)]
p154 = [float(x4.value(s4, f"AH{r}") or 0) for r in range(37, 41)]
sd4 = [float(x4.value(s4, f"AI{r}") or 0) for r in range(37, 41)]
bench4 = {
    "p5": float(x4.value(s4, "AF44")),
    "p50": float(x4.value(s4, "AF45")),
    "p95": float(x4.value(s4, "AF46")),
}
target4 = float(x4.value(s4, "AG44"))
erm4 = simulate_sum(actual4, means4, sd4, target4, "below", floor_zero=True)

print()
print("B. RISK #4 — PENDAPATAN OFF GRID")
print("-" * 150)
print(f"Workbook target total       : Rp {target4:,.2f}")
print(f"Workbook actual Jan-Aug YTD : Rp {sum(actual4):,.2f}")
print(f"Forecast Sep-Dec P50 means  : {[round(v,2) for v in means4]}")
print(f"Forecast Sep-Dec stddev     : {[round(v,2) for v in sd4]}")
print_compare("Current ERM imported-assumption semantics (Normal + monthly floor at 0) vs workbook:", erm4, bench4)
print(f"ERM P(risk: FY < target)    : {erm4['prob_risk']:.4f}%")
print("FINDING:")
print("  REVIEW — target/model ERM existing bukan total Off Grid; workbook memakai total 3 revenue streams.")
print("  REVIEW — P50 cukup dekat, tetapi tail berbeda besar. Current ERM floor-at-zero mempersempit/menaikkan sisi bawah.")
print("  REVIEW — ARIMA/Crystal Ball workbook kemungkinan membawa dependency/autocorrelation forecast yang belum dimodelkan ERM.")

# ----------------------------------------------------------------------------------------------------------------------
# RISK #5
# ----------------------------------------------------------------------------------------------------------------------
x5 = XlsxCached(paths[5])
s5 = "Gangguan (2)"
actual5 = [float(x5.value(s5, f"B{r}") or 0) for r in range(29, 37)]
means5 = [float(x5.value(s5, f"B{r}") or 0) for r in range(47, 51)]
p155 = [float(x5.value(s5, f"C{r}") or 0) for r in range(47, 51)]
sd5 = [float(x5.value(s5, f"D{r}") or 0) for r in range(47, 51)]
bench5 = {
    "p5": float(x5.value(s5, "G47")),
    "p50": float(x5.value(s5, "G48")),
    "p95": float(x5.value(s5, "G49")),
}
target5 = float(x5.value(s5, "G51"))
wb_prob5 = float(x5.value(s5, "G55"))
erm5 = simulate_sum(actual5, means5, sd5, target5, "above", floor_zero=True)

print()
print("C. RISK #5 — GANGGUAN PADAM / KOMPENSASI SLA")
print("-" * 150)
print(f"Workbook target/max 2025    : Rp {target5:,.2f}")
print(f"Workbook actual Jan-Aug YTD : Rp {sum(actual5):,.2f}")
print_compare("Current ERM imported-assumption semantics vs workbook:", erm5, bench5)
print(f"ERM P(risk: FY > target)    : {erm5['prob_risk']:.4f}%")
print(f"Workbook probability ref    : {wb_prob5*100:.4f}%")
print("FINDING:")
print("  REVIEW — P50 relatif dekat tetapi tail berbeda; terutama P95/worst case.")
print("  REVIEW — SARIMA/Crystal Ball kemungkinan memakai dependency/skew; monthly floor-at-zero ERM juga mengubah distribusi.")

# ----------------------------------------------------------------------------------------------------------------------
# RISK #8
# ----------------------------------------------------------------------------------------------------------------------
x8 = XlsxCached(paths[8])
s8 = "Gangguan MPP Pend."
actual8 = [float(x8.value(s8, f"{col}39") or 0) for col in ("D","E","F","G","H","I","J","K")]
target_km_sepdec8 = [float(x8.value(s8, f"{col}47") or 0) * 1_000_000_000 for col in ("L","M","N","O")]
rkap8 = float(x8.value(s8, "P48") or 0) * 1_000_000_000
target_km_total8 = float(x8.value(s8, "P47") or 0) * 1_000_000_000
workbook_actual_total8 = float(x8.value(s8, "P49") or 0) * 1_000_000_000
workbook_deterministic8 = sum(actual8) + sum(target_km_sepdec8)

f50_8 = statistics.mean(actual8[-3:])
p15_8 = pct(actual8, 0.15)
sigma8 = abs(f50_8 - p15_8)
random.seed(SEED)
totals8 = []
for _ in range(TRIALS):
    total = sum(actual8)
    for __ in range(4):
        total += max(random.gauss(f50_8, sigma8), 0.0)
    totals8.append(total)
erm8 = {"p5": pct(totals8, .05), "p50": pct(totals8, .50), "p95": pct(totals8, .95)}

print()
print("D. RISK #8 — KEHANDALAN KIT MPP")
print("-" * 150)
print(f"RKAP revenue                : Rp {rkap8:,.2f}")
print(f"Target KM full year         : Rp {target_km_total8:,.2f}")
print(f"Actual Jan-Aug workbook     : Rp {sum(actual8):,.2f}")
print(f"Workbook total actual cell  : Rp {workbook_actual_total8:,.2f}")
print(f"Actual + Target KM Sep-Dec  : Rp {workbook_deterministic8:,.2f}")
print(f"ERM legacy SMA hypothetical : P5={erm8['p5']:,.2f} | P50={erm8['p50']:,.2f} | P95={erm8['p95']:,.2f}")
print("FINDING:")
print("  REFERENCE ONLY — workbook ini tidak memiliki CB_DATA_/P50-P15-StdDev forecast seperti 3 file lainnya.")
print("  Dashboard workbook Risk #8 juga masih memuat linked/template data Risk #2 (Penjualan/HJR), sehingga tidak aman diimport sebagai Monte Carlo benchmark.")
print("  Yang aman diimport saat ini: actual revenue Jan-Aug + target/RKAP; Monte Carlo harus dimodelkan terpisah.")

# ----------------------------------------------------------------------------------------------------------------------
# RISK #9/#10
# ----------------------------------------------------------------------------------------------------------------------
x9 = XlsxCached(paths[9])
s9 = "Energi Primer (Deny)"

actual_vol = [float(x9.value(s9, f"C{r}") or 0) for r in range(41, 49)]
means_vol = [float(x9.value(s9, f"D{r}") or 0) for r in range(62, 66)]
sd_vol = [float(x9.value(s9, f"F{r}") or 0) for r in range(62, 66)]
bench_vol = {
    "p5": float(x9.value(s9, "C76")),
    "p50": float(x9.value(s9, "C77")),
    "p95": float(x9.value(s9, "C78")),
}
target_vol = float(x9.value(s9, "C80"))
prob_vol_ref = float(x9.value(s9, "C84") or 0)
erm_vol = simulate_sum(actual_vol, means_vol, sd_vol, target_vol, "above", floor_zero=True)

actual_cost = [float(x9.value(s9, f"G{r}") or 0) for r in range(41, 49)]
means_cost = [float(x9.value(s9, f"H{r}") or 0) for r in range(62, 66)]
sd_cost = [float(x9.value(s9, f"J{r}") or 0) for r in range(62, 66)]
bench_cost = {
    "p5": float(x9.value(s9, "E76")),
    "p50": float(x9.value(s9, "E77")),
    "p95": float(x9.value(s9, "E78")),
}
target_cost = float(x9.value(s9, "E80"))
erm_cost = simulate_sum(actual_cost, means_cost, sd_cost, target_cost, "above", floor_zero=True)

actual_price = [float(x9.value(s9, f"N{r}") or 0) for r in range(41, 49)]
means_price = [float(x9.value(s9, f"N{r}") or 0) for r in range(62, 66)]
sd_price = [float(x9.value(s9, f"P{r}") or 0) for r in range(62, 66)]
bench_price = {
    "p5": float(x9.value(s9, "D76")),
    "p50": float(x9.value(s9, "D77")),
    "p95": float(x9.value(s9, "D78")),
}
target_price = float(x9.value(s9, "D80"))
prob_price_ref = float(x9.value(s9, "D84") or 0)
erm_price = simulate_rate_average(actual_price, means_price, sd_price, target_price)

print()
print("E. RISK #9 — VOLUME GAS")
print("-" * 150)
print(f"Target volume               : {target_vol:,.4f} MMBTU")
print(f"Actual Jan-Aug YTD          : {sum(actual_vol):,.4f} MMBTU")
print_compare("ERM imported assumptions vs workbook:", erm_vol, bench_vol)
print(f"ERM P(volume > target)      : {erm_vol['prob_risk']:.4f}%")
print(f"Workbook probability cell   : {prob_vol_ref*100:.4f}%")
print("FINDING:")
print("  NUMERIC MODEL: sangat dekat / dapat divalidasi.")
print("  SEMANTIC REVIEW: workbook memperlakukan volume LEBIH TINGGI sebagai risiko; ERM saat ini perlu dicek direction-nya sebelum import.")

print()
print("F. GAS COST — IMPACT REFERENCE")
print("-" * 150)
print(f"Target cost                 : Rp {target_cost:,.2f}")
print_compare("ERM imported assumptions vs workbook:", erm_cost, bench_cost)
print(f"ERM P(cost > target)        : {erm_cost['prob_risk']:.4f}%")
print("FINDING: PASS numeric; cocok dijadikan impact/reference metric, tetapi tidak perlu menjadi target metric baru sebelum desain attribution Risk #9/#10 disepakati.")

print()
print("G. RISK #10 — HARGA GAS TERTIMBANG (RATE)")
print("-" * 150)
print(f"Target price                : {target_price:,.6f} USD/MMBTU")
print_compare("Proposed ERM RATE = average monthly actual+forecast vs workbook:", erm_price, bench_price)
print(f"ERM P(price > target)       : {erm_price['prob_risk']:.4f}%")
print(f"Workbook probability cell   : {prob_price_ref*100:.4f}%")
print("FINDING:")
print("  P50 sangat konsisten dan probability risk dekat.")
print("  REVIEW — workbook 'Best Case/P5' lebih besar dari P50, yang secara definisi percentile tidak konsisten.")
print("  REVIEW — imported_assumptions ERM V2 saat ini hanya mendukung SUM; Risk #10 memerlukan dukungan aggregation RATE sebelum bisa di-run secara benar.")

print()
print("=" * 150)
print("OVERALL PRE-FLIGHT")
print("=" * 150)
print("RISK #4 : REVIEW — perlu aggregate Total Off Grid + treatment zero-floor/dependency.")
print("RISK #5 : REVIEW — dapat import, tetapi tail CB/SARIMA tidak identik dengan independent Normal ERM.")
print("RISK #8 : REFERENCE ONLY — import actual/target; belum ada benchmark Monte Carlo yang valid di workbook.")
print("RISK #9 : NUMERIC PASS — siap import assumptions setelah direction semantics dikonfirmasi.")
print("RISK #10: REVIEW — perlu RATE support; workbook Best/P5 tidak konsisten.")
print()
print("DATABASE WRITE : NONE")
print("NEXT SAFE STEP : buat importer LOCAL per-risk berdasarkan hasil audit; jangan import empat file secara blind.")
