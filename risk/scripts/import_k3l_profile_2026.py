#!/usr/bin/env python3
"""Import Profil Risiko BID K3L 2026 from the locked June-2026 workbook.

Safety design
-------------
- Exact source SHA256 is required.
- Default mode is DRY-RUN and does not write to DB.
- --apply creates a hot-safe SQLite backup before writing.
- Creates exactly one ReAssessmentSummary and exactly 7 ReAssessmentItem rows:
  risks 1..5 plus risk 6 causes 6a and 6b.
- Never creates/borrows KM items or reference masters.
- Aborts if a K3L 2026 profile already exists.
- Source category risk is blank, therefore kategori_risiko remains NULL.
- Source has no KRI threshold direction, therefore kri_threshold_direction remains NULL.
- All source risks are qualitative. The inherent monetary impact source cell (AE) is
  asserted to be zero and stored as NULL; source probability (AG) and probability
  scale (AH) are preserved. Quarterly target residual values are preserved as source.
- R5 treatment rows 15..18 and R6b treatment rows 20..24 are aggregated without
  inventing extra treatment records, because ReAssessmentItem has one treatment slot.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sqlite3
import sys
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.prod")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth.models import Group  # noqa: E402
from django.db import transaction  # noqa: E402

from risk.models import (  # noqa: E402
    ItemKontrakManajemen,
    KontrakManajemen,
    MasterEfektivitasKontrol,
    MasterJenisExistingControl,
    MasterJenisRencanaPerlakuanRisiko,
    MasterKategoriDampak,
    MasterOpsiPerlakuanRisiko,
    MasterPosAnggaran,
    MasterSkalaDampak,
    MasterSkalaProbabilitas,
    ReAssessmentItem,
    ReAssessmentSummary,
    RiskMatrix,
    SasaranKBUMN,
    TaksonomiT3,
)

YEAR = 2026
UNIT_ID = 19
UNIT_NAME = "BID K3L"
KM_ID = 18
KM_TITLE = "VPK3L"
PROFILE_TITLE = "Profil Risiko K3L"
RISK_MATRIX_ID = 1
EXPECTED_SHA256 = "ada8cb5dcd5cdff9f021f585b538c9e472456bbea49fbd069d1ed0ce4f126bc2"
EXPECTED_ITEMS = 7

# Manual primary-KPI mapping agreed for the K3L source. The importer verifies both ID
# and title before use; it never creates a replacement KPI.
KPI_MAP = {
    (1, "1"): (305, "Optimalisasi Biaya Pemeliharaan"),
    (2, "2"): (309, "Penguatan K3L pada Level Mitra Kerja"),
    (3, "3"): (310, "Penyelesaian Program Improvement K3L"),
    (4, "4"): (307, "Kualitas Penerapan Manajemen Risiko (KPMR)"),
    (5, "5"): (306, "Maturity Level Sustainability"),
    (6, "6a"): (312, "Pengelolaan Safety Culture"),
    (6, "6b"): (312, "Pengelolaan Safety Culture"),
}

# Source layout in SUMMARY.
MAIN_ROWS = [11, 12, 13, 14, 15, 19, 20]
BASE_ROW_FOR = {11: 11, 12: 12, 13: 13, 14: 14, 15: 15, 19: 19, 20: 19}
TREATMENT_ROWS = {
    11: [11],
    12: [12],
    13: [13],
    14: [14],
    15: [15, 16, 17, 18],
    19: [19],
    20: [20, 21, 22, 23, 24],
}

XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def norm(value) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def text(value):
    if value is None:
        return None
    out = str(value).strip()
    if not out or norm(out) in {"n a", "na", "none", "nan"}:
        return None
    return out


def decimal(value):
    value = text(value)
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9eE+\-.,]", "", value)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def int_value(value):
    d = decimal(value)
    if d is None:
        return None
    return int(d)


def int_text(value):
    d = decimal(value)
    if d is None:
        return text(value)
    if d == d.to_integral_value():
        return str(int(d))
    return format(d, "f")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def qround(instance, field_name, value):
    if value is None:
        return None
    fld = instance._meta.get_field(field_name)
    places = getattr(fld, "decimal_places", None)
    if places is None:
        return value
    quantum = Decimal("1").scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def col_letters(ref: str) -> str:
    m = re.match(r"([A-Z]+)", ref)
    return m.group(1) if m else ""


class XlsxSummaryReader:
    def __init__(self, path: Path):
        self.path = path
        self.rows: dict[int, dict[str, str]] = {}
        self._load()

    def _load(self):
        ns = {"m": XLSX_NS, "r": REL_NS}
        with zipfile.ZipFile(self.path) as zf:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in zf.namelist():
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for si in root.findall(f"{{{XLSX_NS}}}si"):
                    shared.append(
                        "".join((t.text or "") for t in si.iter(f"{{{XLSX_NS}}}t"))
                    )

            wb = ET.fromstring(zf.read("xl/workbook.xml"))
            relroot = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            rels = {
                rel.attrib["Id"]: rel.attrib["Target"]
                for rel in relroot.findall(f"{{{PKG_REL_NS}}}Relationship")
            }

            target = None
            sheets = wb.find("m:sheets", ns)
            for sheet in sheets or []:
                if sheet.attrib.get("name") == "SUMMARY":
                    rid = sheet.attrib[f"{{{REL_NS}}}id"]
                    target = rels[rid]
                    break
            if not target:
                raise RuntimeError("Sheet SUMMARY tidak ditemukan di source workbook.")
            sheet_path = target if target.startswith("xl/") else "xl/" + target
            root = ET.fromstring(zf.read(sheet_path))

            def cell_value(cell):
                ctype = cell.attrib.get("t")
                if ctype == "inlineStr":
                    inline = cell.find("m:is", ns)
                    if inline is None:
                        return None
                    return "".join(
                        (t.text or "") for t in inline.iter(f"{{{XLSX_NS}}}t")
                    )
                v = cell.find("m:v", ns)
                if v is None:
                    return None
                raw = v.text or ""
                if ctype == "s":
                    try:
                        return shared[int(raw)]
                    except (ValueError, IndexError):
                        raise RuntimeError(f"Shared string index invalid: {raw!r}")
                if ctype == "b":
                    return "1" if raw == "1" else "0"
                return raw

            for row in root.findall(".//m:sheetData/m:row", ns):
                r = int(row.attrib["r"])
                if r < 11 or r > 24:
                    continue
                data = {}
                for cell in row.findall("m:c", ns):
                    value = cell_value(cell)
                    if value is not None:
                        data[col_letters(cell.attrib["r"])] = value
                self.rows[r] = data

    def get(self, row: int, col: str):
        return self.rows.get(row, {}).get(col)


@dataclass
class SourceRisk:
    seq: int
    risk_no: int
    cause_no: str
    source_row: int
    base_row: int
    objective: str
    event: str
    description: str
    cause: str
    kri: str | None
    kri_unit: str | None
    threshold_safe: str | None
    threshold_caution: str | None
    threshold_danger: str | None
    existing_control_type: str
    existing_control: str | None
    effectiveness: str
    impact_category: str
    impact_description: str | None
    exposure_period: str | None
    impact_assumption: str | None
    source_inherent_impact: Decimal | None
    inherent_probability: Decimal | None
    inherent_probability_scale: int | None
    q_impact: dict[int, Decimal | None]
    q_impact_scale: dict[int, int | None]
    q_probability: dict[int, Decimal | None]
    q_probability_scale: dict[int, int | None]
    q_exposure: dict[int, Decimal | None]
    q_score: dict[int, str | None]
    q_level: dict[int, str | None]
    treatment_option: str
    treatment_type: str
    treatment_plan: str | None
    treatment_output: str | None
    treatment_budget: Decimal | None
    budget_position: str | None
    prk: str | None
    rkap_program: str | None
    pic: str | None
    timeline: dict[int, int]


def join_rows(reader, rows, col):
    vals = [text(reader.get(r, col)) for r in rows]
    vals = [x for x in vals if x]
    return "\n".join(vals) if vals else None


def treatment_budget(reader, rows):
    seen_numeric = False
    total = Decimal("0")
    for r in rows:
        raw = reader.get(r, "CF")
        if text(raw) is None:
            continue
        d = decimal(raw)
        if d is None:
            # N.A is intentionally ignored, but any other nonnumeric value is unsafe.
            if norm(raw) not in {"n a", "na"}:
                raise RuntimeError(f"SUMMARY!CF{r}: budget tidak numerik {raw!r}")
            continue
        seen_numeric = True
        total += d
    return total if seen_numeric else None


def inherited_or_own(reader, source_row, base_row, col):
    own = text(reader.get(source_row, col))
    if own is not None:
        return own
    return text(reader.get(base_row, col))


def build_source(reader: XlsxSummaryReader) -> list[SourceRisk]:
    risks = []
    quarter_cols = {
        "impact": ["AO", "AP", "AQ", "AR"],
        "impact_scale": ["AS", "AT", "AU", "AV"],
        "prob": ["AW", "AX", "AY", "AZ"],
        "prob_scale": ["BA", "BB", "BC", "BD"],
        "exposure": ["BE", "BF", "BG", "BH"],
        "score": ["BI", "BJ", "BK", "BL"],
        "level": ["BM", "BN", "BO", "BP"],
    }

    for seq, source_row in enumerate(MAIN_ROWS, start=1):
        base_row = BASE_ROW_FOR[source_row]
        risk_no = int_value(inherited_or_own(reader, source_row, base_row, "L"))
        cause_raw = inherited_or_own(reader, source_row, base_row, "O")
        if risk_no is None or cause_raw is None:
            raise RuntimeError(f"Risk/cause tidak terbaca pada SUMMARY row {source_row}.")
        # Normalize Excel numeric '1.0' -> '1'; preserve alphanumeric 6a/6b.
        cause_text = cause_raw.strip()
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", cause_text):
            d_cause = Decimal(cause_text)
            cause_no = str(int(d_cause)) if d_cause == d_cause.to_integral_value() else cause_text
        else:
            cause_no = cause_text

        # Source K category is deliberately blank for K3L; do not invent a risk category.
        category = inherited_or_own(reader, source_row, base_row, "K")
        if category:
            raise RuntimeError(
                f"SUMMARY!K{source_row} unexpectedly contains {category!r}; importer expects blank kategori_risiko."
            )

        # Source is qualitative. AE is a numeric template field and is zero on all K3L rows.
        impact_category = inherited_or_own(reader, source_row, base_row, "Z") or ""
        if "kual" not in norm(impact_category):
            raise RuntimeError(f"SUMMARY!Z{base_row} bukan kualitatif: {impact_category!r}")
        source_inherent_impact = decimal(inherited_or_own(reader, source_row, base_row, "AE"))
        if source_inherent_impact not in (None, Decimal("0")):
            raise RuntimeError(
                f"SUMMARY!AE{base_row} berisi dampak numerik non-zero {source_inherent_impact}; tidak aman diabaikan."
            )

        tr_rows = TREATMENT_ROWS[source_row]
        # Treatment metadata is risk-level in this template; for 6b, source detail rows
        # omit CB/CC/CJ, so inherit them from risk row 19 without inventing new values.
        treatment_option = inherited_or_own(reader, source_row, base_row, "CB")
        treatment_type = inherited_or_own(reader, source_row, base_row, "CC")
        pic = inherited_or_own(reader, source_row, base_row, "CJ")
        budget_pos = inherited_or_own(reader, source_row, base_row, "CG")
        prk = inherited_or_own(reader, source_row, base_row, "CH")
        rkap_program = inherited_or_own(reader, source_row, base_row, "CI")

        # CI is blank in the K3L source and was not preflighted against a master.
        if rkap_program:
            raise RuntimeError(
                f"SUMMARY!CI{source_row} contains {rkap_program!r}; manual master mapping required before import."
            )

        timeline = {}
        cols = ["CK", "CL", "CM", "CN", "CO", "CP", "CQ", "CR", "CS", "CT", "CU", "CV"]
        for month, col in enumerate(cols, start=1):
            timeline[month] = 1 if any(int_value(reader.get(r, col)) == 1 for r in tr_rows) else 0

        risks.append(
            SourceRisk(
                seq=seq,
                risk_no=risk_no,
                cause_no=cause_no,
                source_row=source_row,
                base_row=base_row,
                objective=inherited_or_own(reader, source_row, base_row, "H") or "",
                event=inherited_or_own(reader, source_row, base_row, "M") or "",
                description=inherited_or_own(reader, source_row, base_row, "N") or "",
                cause=inherited_or_own(reader, source_row, base_row, "Q") or "",
                kri=inherited_or_own(reader, source_row, base_row, "R"),
                kri_unit=inherited_or_own(reader, source_row, base_row, "S"),
                threshold_safe=inherited_or_own(reader, source_row, base_row, "T"),
                threshold_caution=inherited_or_own(reader, source_row, base_row, "U"),
                threshold_danger=inherited_or_own(reader, source_row, base_row, "V"),
                existing_control_type=inherited_or_own(reader, source_row, base_row, "W") or "",
                existing_control=inherited_or_own(reader, source_row, base_row, "X"),
                effectiveness=inherited_or_own(reader, source_row, base_row, "Y") or "",
                impact_category=impact_category,
                impact_description=inherited_or_own(reader, source_row, base_row, "AA"),
                exposure_period=inherited_or_own(reader, source_row, base_row, "AB"),
                impact_assumption=inherited_or_own(reader, source_row, base_row, "AC"),
                source_inherent_impact=source_inherent_impact,
                inherent_probability=decimal(inherited_or_own(reader, source_row, base_row, "AG")),
                inherent_probability_scale=int_value(inherited_or_own(reader, source_row, base_row, "AH")),
                q_impact={q: decimal(reader.get(base_row, c)) for q, c in enumerate(quarter_cols["impact"], 1)},
                q_impact_scale={q: int_value(reader.get(base_row, c)) for q, c in enumerate(quarter_cols["impact_scale"], 1)},
                q_probability={q: decimal(reader.get(base_row, c)) for q, c in enumerate(quarter_cols["prob"], 1)},
                q_probability_scale={q: int_value(reader.get(base_row, c)) for q, c in enumerate(quarter_cols["prob_scale"], 1)},
                q_exposure={q: decimal(reader.get(base_row, c)) for q, c in enumerate(quarter_cols["exposure"], 1)},
                q_score={q: int_text(reader.get(base_row, c)) for q, c in enumerate(quarter_cols["score"], 1)},
                q_level={q: text(reader.get(base_row, c)) for q, c in enumerate(quarter_cols["level"], 1)},
                treatment_option=treatment_option or "",
                treatment_type=treatment_type or "",
                treatment_plan=join_rows(reader, tr_rows, "CD"),
                treatment_output=join_rows(reader, tr_rows, "CE"),
                treatment_budget=treatment_budget(reader, tr_rows),
                budget_position=budget_pos,
                prk=prk,
                rkap_program=rkap_program,
                pic=pic,
                timeline=timeline,
            )
        )

    keys = [(x.risk_no, x.cause_no) for x in risks]
    expected = [(1, "1"), (2, "2"), (3, "3"), (4, "4"), (5, "5"), (6, "6a"), (6, "6b")]
    if keys != expected:
        raise RuntimeError(f"Struktur source berbeda. Ditemukan {keys}; expected {expected}.")

    for r in risks:
        # Common K3L source structural assertions.
        if "nilai ekonomi dan sosial" not in norm(reader.get(r.base_row, "I")):
            raise RuntimeError(f"SUMMARY!I{r.base_row}: sasaran KBUMN tidak sesuai.")
        if not norm(reader.get(r.base_row, "J")).startswith("3 6 16"):
            raise RuntimeError(f"SUMMARY!J{r.base_row}: taxonomy tidak sesuai.")
        if norm(r.treatment_option) != "reduce mitigate":
            raise RuntimeError(f"R{r.risk_no}/{r.cause_no}: treatment option bukan Reduce/Mitigate.")
        if norm(r.treatment_type) != "peningkatan efektivitas pelaksanaan control":
            raise RuntimeError(f"R{r.risk_no}/{r.cause_no}: treatment type tidak sesuai.")
    return risks


def require_obj(model, pk, contains: str | None = None):
    obj = model.objects.get(pk=pk)
    if contains and norm(contains) not in norm(str(obj)):
        raise RuntimeError(f"Master {model.__name__} ID={pk} berubah: {obj!s}")
    return obj


def resolve_masters():
    unit = Group.objects.get(pk=UNIT_ID)
    if unit.name != UNIT_NAME:
        raise RuntimeError(f"Unit ID={UNIT_ID} berubah: {unit.name!r}")

    km = KontrakManajemen.objects.select_related("unit_bisnis").get(pk=KM_ID)
    if not (
        km.judul == KM_TITLE
        and km.tahun == YEAR
        and km.unit_bisnis_id == UNIT_ID
        and km.status == "Final"
    ):
        raise RuntimeError(f"KM ID={KM_ID} tidak lagi sesuai pre-flight: {km}")

    matrix = RiskMatrix.objects.get(pk=RISK_MATRIX_ID)
    sasaran = require_obj(SasaranKBUMN, 1, "Nilai ekonomi dan sosial")
    taxonomy = require_obj(TaksonomiT3, 1, "3.6.16")
    control_operation = require_obj(MasterJenisExistingControl, 1, "Kontrol operasi")
    control_reporting = require_obj(MasterJenisExistingControl, 5, "Kontrol pelaporan")
    effectiveness_numbered = require_obj(MasterEfektivitasKontrol, 7, "Cukup dan Efektif Sebagian")
    effectiveness_plain = require_obj(MasterEfektivitasKontrol, 2, "Cukup dan Efektif Sebagian")
    impact_qualitative = require_obj(MasterKategoriDampak, 2, "Kual")
    option_reduce = require_obj(MasterOpsiPerlakuanRisiko, 1, "Reduce")
    pos_operasi = require_obj(MasterPosAnggaran, 1, "Anggaran Operasi")
    treatment_type = require_obj(
        MasterJenisRencanaPerlakuanRisiko,
        1,
        "Peningkatan Efektivitas Pelaksanaan Control",
    )

    impact_scales = {i: require_obj(MasterSkalaDampak, i) for i in range(1, 6)}
    prob_scales = {i: require_obj(MasterSkalaProbabilitas, i) for i in range(1, 6)}

    kpis = {}
    for key, (pk, title_contains) in KPI_MAP.items():
        obj = ItemKontrakManajemen.objects.select_related("kontrak").get(pk=pk)
        if obj.kontrak_id != KM_ID or norm(title_contains) not in norm(obj.indikator_kinerja_kunci):
            raise RuntimeError(f"KPI mapping {key} invalid: KPI_ID={pk} -> {obj}")
        kpis[key] = obj

    return {
        "unit": unit,
        "km": km,
        "matrix": matrix,
        "sasaran": sasaran,
        "taxonomy": taxonomy,
        "control_operation": control_operation,
        "control_reporting": control_reporting,
        "effectiveness_numbered": effectiveness_numbered,
        "effectiveness_plain": effectiveness_plain,
        "impact_qualitative": impact_qualitative,
        "option_reduce": option_reduce,
        "pos_operasi": pos_operasi,
        "treatment_type": treatment_type,
        "impact_scales": impact_scales,
        "prob_scales": prob_scales,
        "kpis": kpis,
    }


def master_for_source(r: SourceRisk, masters):
    ctype = norm(r.existing_control_type)
    if "kontrol operasi" in ctype:
        control = masters["control_operation"]
    elif "kontrol pelaporan" in ctype:
        control = masters["control_reporting"]
    else:
        raise RuntimeError(f"R{r.risk_no}/{r.cause_no}: existing control type tidak dikenal: {r.existing_control_type!r}")

    # Rows 11..14 explicitly include prefix '2.'; rows 15/19 use the plain label.
    eff = (
        masters["effectiveness_numbered"]
        if norm(r.effectiveness).startswith("2 ")
        else masters["effectiveness_plain"]
    )
    if "cukup dan efektif sebagian" not in norm(r.effectiveness):
        raise RuntimeError(f"R{r.risk_no}/{r.cause_no}: effectiveness berbeda: {r.effectiveness!r}")

    pos = None
    if r.budget_position:
        if norm(r.budget_position) != "anggaran operasi":
            raise RuntimeError(f"R{r.risk_no}/{r.cause_no}: pos anggaran tidak dikenal: {r.budget_position!r}")
        pos = masters["pos_operasi"]

    return control, eff, pos


def backup_sqlite() -> Path:
    db_name = settings.DATABASES["default"].get("NAME")
    if not db_name:
        raise RuntimeError("DATABASE NAME kosong; backup tidak dapat dilakukan.")
    src = Path(str(db_name)).resolve()
    if not src.exists() or src.suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
        raise RuntimeError(f"Importer ini mensyaratkan backup SQLite; database tidak sesuai: {src}")
    backup_dir = PROJECT_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    dst = backup_dir / f"db_before_k3l_profile_2026_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite3"

    source = sqlite3.connect(str(src))
    target = sqlite3.connect(str(dst))
    try:
        source.backup(target)
        check = target.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError(f"Backup integrity_check gagal: {check}")
    finally:
        target.close()
        source.close()
    return dst


def print_preview(source, masters, source_path):
    print("=" * 126)
    print("PROFIL RISIKO BID K3L 2026 | MODE=DRY RUN")
    print("=" * 126)
    print(f"SOURCE : {source_path}")
    print(f"SHA256 : {sha256(source_path)}")
    print(f"UNIT   : {masters['unit'].pk} | {masters['unit'].name}")
    print(f"KM     : {masters['km'].pk} | {masters['km'].judul}")
    print(f"PROFILE: CREATE NEW | {PROFILE_TITLE} | RiskMatrix={masters['matrix'].pk}")
    print()
    for r in source:
        kpi = masters["kpis"][(r.risk_no, r.cause_no)]
        control, eff, pos = master_for_source(r, masters)
        months = [str(m) for m, flag in r.timeline.items() if flag]
        print(
            f"ITEM={r.seq} | R{r.risk_no}/{r.cause_no} | SOURCE=SUMMARY!{r.source_row} "
            f"| KPI_ID={kpi.pk} | {kpi.indikator_kinerja_kunci}"
        )
        print(f"  Event       : {r.event}")
        print(f"  Cause       : {r.cause}")
        print(f"  Sasaran/T3  : {masters['sasaran'].pk} / {masters['taxonomy'].pk} | kategori_risiko=NULL (source blank)")
        print(f"  Control     : ID={control.pk} | Efektivitas ID={eff.pk}")
        print(
            f"  Qualitative : kategori_dampak={masters['impact_qualitative'].pk} | "
            f"nilai_dampak inherent=NULL (source AE={r.source_inherent_impact}) | "
            f"prob={r.inherent_probability} | prob_scale={r.inherent_probability_scale}"
        )
        print(
            f"  Treatment   : {r.treatment_plan or '-'} | budget={r.treatment_budget} "
            f"| pos={(pos.pk if pos else None)} | PIC={r.pic!r} | timeline={','.join(months) or '-'}"
        )
        print()
    print("SOURCE RISKS : 6 logical")
    print("DB ITEMS     : 7 (R6 = 6a + 6b)")
    print("KRI direction: NULL (source tidak menyediakan direction)")
    print("Jenis RKAP   : NULL (source CI kosong)")
    print("DRY-RUN RESULT: CLEAN — DATABASE TIDAK DIUBAH")


def apply_profile(source, masters):
    existing = ReAssessmentSummary.objects.filter(unit_bisnis_id=UNIT_ID, tahun=YEAR)
    if existing.exists():
        rows = list(existing.values_list("id", "judul", "kontrak_manajemen_id"))
        raise RuntimeError(f"Profil K3L 2026 sudah muncul sebelum APPLY; abort: {rows}")

    with transaction.atomic():
        # Re-check inside transaction.
        km = KontrakManajemen.objects.select_for_update().get(pk=KM_ID)
        if km.unit_bisnis_id != UNIT_ID or km.tahun != YEAR or km.judul != KM_TITLE:
            raise RuntimeError("KM berubah saat transaction lock; abort.")
        if ReAssessmentSummary.objects.select_for_update().filter(unit_bisnis_id=UNIT_ID, tahun=YEAR).exists():
            raise RuntimeError("Profil K3L 2026 sudah ada saat transaction lock; abort.")

        status_draft = getattr(ReAssessmentSummary, "STATUS_DRAFT", "draft")
        profile = ReAssessmentSummary.objects.create(
            judul=PROFILE_TITLE,
            tahun=YEAR,
            unit_bisnis=masters["unit"],
            kontrak_manajemen=masters["km"],
            risk_matrix=masters["matrix"],
            status=status_draft,
        )

        created = []
        for r in source:
            control, eff, pos = master_for_source(r, masters)
            item = ReAssessmentItem(
                summary=profile,
                no_item=r.seq,
                unit_bisnis=masters["unit"],
                km_item=masters["kpis"][(r.risk_no, r.cause_no)],
                sasaran_kbumn=masters["sasaran"],
                taksonomi_t3=masters["taxonomy"],
                kategori_risiko=None,
                no_risiko=r.risk_no,
                peristiwa_risiko=r.event,
                deskripsi_peristiwa_risiko=r.description,
                no_penyebab_risiko=r.cause_no,
                penyebab_risiko=r.cause,
                key_risk_indicators=r.kri,
                unit_satuan_kri=r.kri_unit,
                threshold_aman=r.threshold_safe,
                threshold_hati_hati=r.threshold_caution,
                threshold_bahaya=r.threshold_danger,
                kri_threshold_direction=None,
                jenis_existing_control=control,
                existing_control=r.existing_control,
                penilaian_efektivitas_kontrol=eff,
                kategori_dampak=masters["impact_qualitative"],
                deskripsi_dampak=r.impact_description,
                perkiraan_waktu_terpapar_risiko=r.exposure_period,
                asumsi_perhitungan_dampak=r.impact_assumption,
                nilai_dampak=None,
                nilai_probabilitas=r.inherent_probability,
                skala_probabilitas=(
                    masters["prob_scales"].get(r.inherent_probability_scale)
                    if r.inherent_probability_scale else None
                ),
                opsi_perlakuan_risiko=masters["option_reduce"],
                rencana_perlakuan_risiko=r.treatment_plan,
                output_perlakuan_risiko=r.treatment_output,
                biaya_perlakuan_risiko=r.treatment_budget,
                pos_anggaran=pos,
                prk=r.prk,
                jenis_program_dalam_rkap=None,
                pic=r.pic,
                pic_organization_unit=None,
                pic_user_assignment=None,
                **{f"timeline_{m}": r.timeline[m] for m in range(1, 13)},
            )

            for q in range(1, 5):
                setattr(item, f"nilai_dampak_q{q}", r.q_impact[q])
                setattr(
                    item,
                    f"skala_dampak_q{q}",
                    masters["impact_scales"].get(r.q_impact_scale[q]) if r.q_impact_scale[q] else None,
                )
                setattr(item, f"nilai_probabilitas_q{q}", r.q_probability[q])
                setattr(
                    item,
                    f"skala_probabilitas_q{q}",
                    masters["prob_scales"].get(r.q_probability_scale[q]) if r.q_probability_scale[q] else None,
                )
                setattr(item, f"eksposur_risiko_q{q}", r.q_exposure[q])
                setattr(item, f"skala_risiko_q{q}", r.q_score[q])
                setattr(item, f"level_nilai_risiko_q{q}", r.q_level[q])

            # Quantize all DecimalFields using the live model definition.
            for fname in [
                "nilai_probabilitas",
                "biaya_perlakuan_risiko",
                *[f"nilai_dampak_q{q}" for q in range(1, 5)],
                *[f"nilai_probabilitas_q{q}" for q in range(1, 5)],
                *[f"eksposur_risiko_q{q}" for q in range(1, 5)],
            ]:
                setattr(item, fname, qround(item, fname, getattr(item, fname)))

            item.save()
            item.jenis_rencana_perlakuan_risiko.set([masters["treatment_type"]])
            created.append(item)

        # Hard post-check before commit.
        qs = (
            ReAssessmentItem.objects.filter(summary=profile)
            .select_related("km_item", "kategori_dampak", "summary")
            .order_by("no_item")
        )
        if qs.count() != EXPECTED_ITEMS:
            raise RuntimeError(f"POST-CHECK item count={qs.count()}, expected {EXPECTED_ITEMS}")
        keys = list(qs.values_list("no_risiko", "no_penyebab_risiko"))
        expected_keys = [(1, "1"), (2, "2"), (3, "3"), (4, "4"), (5, "5"), (6, "6a"), (6, "6b")]
        if keys != expected_keys:
            raise RuntimeError(f"POST-CHECK keys salah: {keys}")
        if any(x.km_item.kontrak_id != KM_ID for x in qs):
            raise RuntimeError("POST-CHECK: ada KPI bukan dari VPK3L.")
        if any(x.kategori_dampak_id != 2 for x in qs):
            raise RuntimeError("POST-CHECK: kategori dampak bukan kualitatif ID=2.")
        if any(x.nilai_dampak is not None for x in qs):
            raise RuntimeError("POST-CHECK: nilai_dampak inherent qualitative seharusnya NULL.")
        if any(x.kategori_risiko_id is not None for x in qs):
            raise RuntimeError("POST-CHECK: kategori_risiko source blank seharusnya NULL.")
        for x in qs:
            if list(x.jenis_rencana_perlakuan_risiko.values_list("pk", flat=True)) != [1]:
                raise RuntimeError(f"POST-CHECK: jenis treatment RE={x.pk} tidak sesuai.")

        return profile, list(qs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="Path workbook Profil Risiko K3L")
    parser.add_argument("--apply", action="store_true", help="Commit ke database")
    args = parser.parse_args()

    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        raise SystemExit(f"SOURCE TIDAK DITEMUKAN: {source_path}")
    digest = sha256(source_path)
    if digest != EXPECTED_SHA256:
        raise SystemExit(
            "SAFETY STOP: SHA256 source berbeda.\n"
            f"Expected: {EXPECTED_SHA256}\n"
            f"Actual  : {digest}"
        )

    reader = XlsxSummaryReader(source_path)
    source = build_source(reader)
    masters = resolve_masters()

    # Preflight existing profile in both modes.
    existing = list(
        ReAssessmentSummary.objects.filter(unit_bisnis_id=UNIT_ID, tahun=YEAR)
        .values_list("id", "judul", "kontrak_manajemen_id")
    )
    if existing:
        raise SystemExit(f"SAFETY STOP: Profil K3L 2026 sudah ada: {existing}")

    print_preview(source, masters, source_path)
    if not args.apply:
        return

    backup = backup_sqlite()
    print(f"\nBACKUP DB: {backup}")
    print(f"BACKUP SHA256: {sha256(backup)}")

    profile, items = apply_profile(source, masters)
    print("\n" + "=" * 126)
    print("APPLY SUCCESS")
    print("=" * 126)
    print(
        f"PROFILE ID={profile.pk} | {profile.judul} | unit={profile.unit_bisnis} "
        f"| KM={profile.kontrak_manajemen_id} | status={profile.status} | items={len(items)}"
    )
    for item in items:
        print(
            f"RE={item.pk} | ITEM={item.no_item} | R{item.no_risiko}/{item.no_penyebab_risiko} "
            f"| KPI={item.km_item_id} | {item.peristiwa_risiko}"
        )
    print("POST-CHECK: PASS")


if __name__ == "__main__":
    main()
