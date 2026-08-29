#!/usr/bin/env python3
"""
IMPORT LAPORAN PROFIL RISIKO UB KITRANS - MEI 2026
V1 SAFE / SOURCE-EXACT / DEFAULT DRY-RUN

Sumber resmi:
  Laporan Manajemen Risiko UBKITRANS Mei 2026.xlsx

Target production yang divalidasi:
- ReAssessmentSummary id=14 : Profil Risiko UBKITRANS
- Unit                      : UB KITRAN
- KM id=10                  : SMUPKITRANS (2026)
- Prepared by id=176
- Mei 2026 MRR              : wajib belum ada
- Juni 2026 MRR id=84       : wajib tetap utuh (guard histori)

Prinsip import:
1. Default DRY-RUN. Database hanya berubah dengan --apply.
2. SHA256 sumber wajib sama dengan file yang diaudit.
3. III.A:
   - 19 risk event.
   - Mei berada pada Q2, tetapi seluruh kolom residual Q2 sumber kosong.
   - Tidak fallback ke Q1. Nilai residual Mei tetap NULL.
4. III.B:
   - 40 unique cause group.
   - 106 activity resmi = baris yang memiliki Rencana Perlakuan di kolom H.
   - Baris actual-only tanpa H tidak dijadikan activity baru; dicatat sebagai
     continuation rows dan sengaja tidak digabung ke canonical 106 activities.
   - Narasi realisasi bulan ini hanya mengambil activity H yang memang memiliki
     realisasi di K/L.
   - Progress Q2 = rata-rata hanya cell Q2 yang benar-benar terisi.
   - Timeline untuk report Mei hanya Jan-Mei; Jun-Des dipaksa 0.
5. III.D = 0 dan III.E = 0.
6. KRI:
   Workbook Mei ini masih memberi judul pasangan kolom AM/AN sebagai
   "Realisasi Threshold KRI Maret". Karena label bulan tidak cocok, data tersebut
   TIDAK diklaim sebagai realisasi KRI Mei. Nama/satuan/band/status/nilai sumber
   tetap dipreservasi di realisasi_kri_text dengan catatan label sumber.
   realisasi_nilai_kri dan realisasi_threshold_kri tetap NULL.
7. Import tidak mengubah Profil Risiko/ReAssessmentItem/KM.
8. SQLite backup + integrity_check sebelum APPLY, transaction.atomic, dan
   postcheck setelah commit.

Pemakaian:
  python monthly_report/scripts/import_mrr_ubkitrans_mei_2026_v1_safe.py \
    --source "/tmp/Laporan Manajemen Risiko UBKITRANS Mei 2026.xlsx"

Setelah DRY-RUN direview:
  python monthly_report/scripts/import_mrr_ubkitrans_mei_2026_v1_safe.py \
    --source "/tmp/Laporan Manajemen Risiko UBKITRANS Mei 2026.xlsx" \
    --apply
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import os
import re
import sqlite3
import sys
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.prod")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.db import transaction  # noqa: E402
from django.db.models import Sum  # noqa: E402
from django.utils import timezone  # noqa: E402

from masterdata.models import PeriodeLaporan, TahunBuku  # noqa: E402
from monthly_report.models import (  # noqa: E402
    MonthlyRiskReport,
    MonthlyRiskReportChange,
    MonthlyRiskReportItem,
    MonthlyRiskReportLossEvent,
)
from risk.models import ReAssessmentItem, ReAssessmentSummary  # noqa: E402


YEAR = 2026
MONTH = 5
PERIOD_CODE = "2026-05"
REPORT_CODE = "MRR-KITRANS-2026-05"

PROFILE_ID = 14
KM_ID = 10
PREPARED_BY_ID = 176

JUNE_REPORT_ID = 84
JUNE_REPORT_CODE = "MRR-KITRANS-2026-06"

EXPECTED_SHA256 = "93b484db525f044252c9638c36bab79c22ecf3a69817d9aea323f9d7620c97fd"
EXPECTED_EVENTS = 19
EXPECTED_CAUSES = 40
EXPECTED_TREATMENT_ROWS = 106
EXPECTED_ACTUAL_ONLY_CONTINUATION = 29
EXPECTED_FORMAL_ACTUAL_PLAN_ROWS = 93
EXPECTED_FORMAL_ACTUAL_OUTPUT_ROWS = 11
EXPECTED_Q2_PROGRESS_GROUPS = 14
EXPECTED_NUMERIC_KRI_GROUPS = 19
EXPECTED_PLANNED_COST = Decimal("558910040366.41")
EXPECTED_ACTUAL_COST = Decimal("940000000.00")

# Current canonical rows after the audited June import.
REPRESENTATIVE_IDS = {
    1: 267, 2: 275, 3: 276, 4: 278, 5: 282, 6: 283, 7: 297, 8: 302,
    9: 518, 10: 325, 11: 333, 12: 334, 13: 340, 14: 345, 15: 348,
    16: 351, 17: 353, 18: 354, 19: 355, 20: 356, 21: 360, 22: 364,
    23: 366, 24: 368, 25: 370, 26: 371, 27: 374, 28: 375, 29: 379,
    30: 380, 31: 381, 32: 382, 33: 387, 34: 389, 35: 390, 36: 391,
    37: 395, 38: 398, 39: 399, 40: 400,
}

Q2_IIIA_COLUMNS = (15, 19, 23, 27, 31, 35, 39, 43, 47, 51, 55)

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL_DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def banner(text: str, width: int = 158):
    print("\n" + "=" * width)
    print(text)
    print("=" * width)


def norm(value) -> str:
    value = "" if value is None else str(value)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold().replace("–", "-").replace("—", "-")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


RISK6_PROFILE_EVENT = (
    "Heatrate gas (BTU/kWh) pada pembangkit sendiri dan sewa "
    "melebihi asumsi yang ditetapkan"
)

RISK6_MONTHLY_EVENT = (
    "Penyerapan gas dalam BTU/kWh oleh pembangkit sendiri dan sewa "
    "melebihi asumsi yang ditetapkan"
)


def event_norm(value) -> str:
    """
    Normalisasi event untuk pencocokan source bulanan vs profil canonical.

    Risk 6 mempunyai wording berbeda:
    - Profil/SUMMARY : Heatrate gas ...
    - III.A/III.B    : Penyerapan gas ...
    Keduanya merupakan risk event yang sama.
    """
    n = norm(value)
    if n == norm(RISK6_MONTHLY_EVENT):
        return norm(RISK6_PROFILE_EVENT)
    return n


def text(value):
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def D(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value

    s = str(value).strip()
    if not s or s in {"-", "–", "—"}:
        return None

    s = s.replace("\xa0", " ").strip()
    s = re.sub(r"^(Rp|IDR|USD)\s*", "", s, flags=re.I).strip()
    s = s.replace("%", "").strip()

    # Scientific/numeric XML values.
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        pass

    # Indonesian-style display values: 95.445.091.701,06
    if "," in s:
        s2 = s.replace(".", "").replace(",", ".").replace(" ", "")
        try:
            return Decimal(s2)
        except (InvalidOperation, ValueError):
            return None

    # Thousands separated by dots with no decimal comma.
    if s.count(".") > 1:
        s2 = s.replace(".", "").replace(" ", "")
        try:
            return Decimal(s2)
        except (InvalidOperation, ValueError):
            return None

    return None


def money(value):
    d = D(value)
    if d is None:
        return None
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def first_unique(rows, key):
    out = []
    for row in rows:
        value = row.get(key)
        if value not in (None, "") and value not in out:
            out.append(value)
    return out


def numeric_values(rows, key):
    out = []
    for row in rows:
        d = D(row.get(key))
        if d is not None:
            out.append(d)
    return out


def nonnumeric_values(rows, key):
    out = []
    for row in rows:
        raw = row.get(key)
        if raw in (None, ""):
            continue
        if D(raw) is None:
            out.append(str(raw).strip())
    return out


def col_number(cell_ref: str) -> int:
    letters = re.match(r"([A-Z]+)", cell_ref)
    if not letters:
        raise RuntimeError(f"Invalid XLSX cell ref: {cell_ref!r}")
    n = 0
    for ch in letters.group(1):
        n = n * 26 + ord(ch) - 64
    return n


class RawWorkbook:
    """Minimal stdlib XLSX reader; values only, no formula recalculation."""

    def __init__(self, path: Path):
        self.path = path
        self.zf = zipfile.ZipFile(path)
        self.shared_strings = self._shared_strings()
        self.sheet_paths = self._sheet_paths()
        self._cache = {}

    def close(self):
        self.zf.close()

    def _shared_strings(self):
        if "xl/sharedStrings.xml" not in self.zf.namelist():
            return []
        root = ET.fromstring(self.zf.read("xl/sharedStrings.xml"))
        out = []
        for si in root.findall(f"{{{NS_MAIN}}}si"):
            out.append(
                "".join(t.text or "" for t in si.iter(f"{{{NS_MAIN}}}t"))
            )
        return out

    def _sheet_paths(self):
        wb = ET.fromstring(self.zf.read("xl/workbook.xml"))
        rels = ET.fromstring(self.zf.read("xl/_rels/workbook.xml.rels"))
        relmap = {r.attrib["Id"]: r.attrib["Target"] for r in rels}

        sheets = {}
        sheet_parent = wb.find(f"{{{NS_MAIN}}}sheets")
        if sheet_parent is None:
            return sheets

        for sheet in sheet_parent:
            name = sheet.attrib["name"]
            rid = sheet.attrib[f"{{{NS_REL_DOC}}}id"]
            target = relmap[rid]
            if target.startswith("/"):
                target = target.lstrip("/")
            elif not target.startswith("xl/"):
                target = "xl/" + target
            sheets[name] = target
        return sheets

    def rows(self, sheet_name: str):
        if sheet_name in self._cache:
            return self._cache[sheet_name]
        path = self.sheet_paths.get(sheet_name)
        if not path:
            raise RuntimeError(f"STOP: sheet {sheet_name!r} tidak ditemukan.")

        root = ET.fromstring(self.zf.read(path))
        out = {}
        for row in root.iter(f"{{{NS_MAIN}}}row"):
            row_no = int(row.attrib["r"])
            values = {}
            for cell in row.findall(f"{{{NS_MAIN}}}c"):
                ref = cell.attrib["r"]
                typ = cell.attrib.get("t")
                value_node = cell.find(f"{{{NS_MAIN}}}v")

                if typ == "inlineStr":
                    inline = cell.find(f"{{{NS_MAIN}}}is")
                    value = (
                        "".join(
                            t.text or ""
                            for t in inline.iter(f"{{{NS_MAIN}}}t")
                        )
                        if inline is not None
                        else ""
                    )
                elif value_node is None:
                    value = None
                elif typ == "s":
                    value = self.shared_strings[int(value_node.text)]
                elif typ == "b":
                    value = value_node.text == "1"
                else:
                    value = value_node.text

                values[col_number(ref)] = value
            out[row_no] = values

        self._cache[sheet_name] = out
        return out

    def all_text(self):
        parts = []
        parts.extend(self.shared_strings)
        for sheet_name in self.sheet_paths:
            rows = self.rows(sheet_name)
            for row in rows.values():
                for value in row.values():
                    if isinstance(value, str):
                        parts.append(value)
        return "\n".join(parts)


def source_sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_iiia(wb: RawWorkbook):
    rows = wb.rows("III.A")
    events = []

    for row_no in sorted(rows):
        if row_no < 11:
            continue
        row = rows[row_no]
        event = text(row.get(3))
        if not event:
            continue

        events.append({
            "row": row_no,
            "source_code": text(row.get(2)),
            "event": event,
            "jenis": text(row.get(4)),
            "assumption": text(row.get(13)),
            "effectiveness_raw": text(row.get(58)),
            "q2_values": [row.get(c) for c in Q2_IIIA_COLUMNS],
        })

    if len(events) != EXPECTED_EVENTS:
        raise RuntimeError(
            f"STOP source: III.A events={len(events)}, expected={EXPECTED_EVENTS}."
        )

    event_names = {norm(x["event"]) for x in events}
    if len(event_names) != EXPECTED_EVENTS:
        raise RuntimeError("STOP source: III.A event names tidak unique 19/19.")

    q2_populated = [
        (x["row"], x["event"], x["q2_values"])
        for x in events
        if any(v not in (None, "") for v in x["q2_values"])
    ]
    if q2_populated:
        raise RuntimeError(
            "STOP source: Q2 III.A seharusnya kosong, tetapi ada nilai: "
            + repr(q2_populated[:5])
        )

    return events


def parse_iiib(wb: RawWorkbook):
    rows = wb.rows("III.B")

    current = {
        "risk_no": None,
        "event": None,
        "cause_no": None,
        "cause_text": None,
    }
    formal = []
    actual_only_rows = []

    for row_no in sorted(rows):
        if row_no < 10:
            continue

        row = rows[row_no]
        has_new_risk = row.get(2) not in (None, "") or row.get(3) not in (None, "")
        if has_new_risk:
            current["cause_no"] = None
            current["cause_text"] = None

        for col, name in (
            (2, "risk_no"),
            (3, "event"),
            (5, "cause_no"),
            (7, "cause_text"),
        ):
            value = row.get(col)
            if value not in (None, ""):
                current[name] = value

        plan = row.get(8)
        actual_plan = row.get(11)

        if plan not in (None, ""):
            formal.append({
                "source_row": row_no,
                "risk_no": current["risk_no"],
                "event": current["event"],
                "cause_no": current["cause_no"],
                "cause_text": current["cause_text"],
                "plan": row.get(8),
                "planned_output": row.get(9),
                "planned_cost": row.get(10),
                "actual_plan": row.get(11),
                "actual_output": row.get(12),
                "actual_cost": row.get(13),
                "source_absorption": row.get(14),
                "pic": row.get(15),
                "timeline": [row.get(c) for c in range(16, 28)],
                "source_status": row.get(28),
                "source_status_explanation": row.get(29),
                "progress_q1": row.get(30),
                "progress_q2": row.get(31),
                "progress_q3": row.get(32),
                "progress_q4": row.get(33),
                "kri": row.get(34),
                "kri_unit": row.get(35),
                "kri_safe": row.get(36),
                "kri_caution": row.get(37),
                "kri_danger": row.get(38),
                "kri_source_status": row.get(39),
                "kri_source_value": row.get(40),
            })
        elif actual_plan not in (None, ""):
            actual_only_rows.append(row_no)

    if len(formal) != EXPECTED_TREATMENT_ROWS:
        raise RuntimeError(
            f"STOP source: formal III.B rows={len(formal)}, "
            f"expected={EXPECTED_TREATMENT_ROWS}."
        )
    if len(actual_only_rows) != EXPECTED_ACTUAL_ONLY_CONTINUATION:
        raise RuntimeError(
            f"STOP source: actual-only continuation={len(actual_only_rows)}, "
            f"expected={EXPECTED_ACTUAL_ONLY_CONTINUATION}."
        )

    groups = []
    for row in formal:
        key = (
            norm(row["event"]),
            norm(row["cause_no"]),
            norm(row["cause_text"]),
        )
        if not groups or groups[-1]["key"] != key:
            groups.append({
                "key": key,
                "source_risk_no": row["risk_no"],
                "event": row["event"],
                "cause_no": row["cause_no"],
                "cause_text": row["cause_text"],
                "rows": [],
            })
        groups[-1]["rows"].append(row)

    if len(groups) != EXPECTED_CAUSES:
        raise RuntimeError(
            f"STOP source: cause groups={len(groups)}, expected={EXPECTED_CAUSES}."
        )

    actual_plan_count = sum(
        1 for row in formal if text(row["actual_plan"]) is not None
    )
    actual_output_count = sum(
        1 for row in formal if text(row["actual_output"]) is not None
    )
    if actual_plan_count != EXPECTED_FORMAL_ACTUAL_PLAN_ROWS:
        raise RuntimeError(
            f"STOP source: formal rows with actual plan={actual_plan_count}, "
            f"expected={EXPECTED_FORMAL_ACTUAL_PLAN_ROWS}."
        )
    if actual_output_count != EXPECTED_FORMAL_ACTUAL_OUTPUT_ROWS:
        raise RuntimeError(
            f"STOP source: formal rows with actual output={actual_output_count}, "
            f"expected={EXPECTED_FORMAL_ACTUAL_OUTPUT_ROWS}."
        )

    return groups, actual_only_rows


def rows_after_start_are_blank(wb: RawWorkbook, sheet_name: str):
    rows = wb.rows(sheet_name)
    start = None
    for row_no, row in rows.items():
        if norm(row.get(1)) == "start pengisian":
            start = row_no
            break
    if start is None:
        raise RuntimeError(
            f"STOP source: marker 'Start pengisian' tidak ditemukan di {sheet_name}."
        )

    populated = []
    for row_no in sorted(rows):
        if row_no <= start:
            continue
        values = [
            v for v in rows[row_no].values()
            if text(v) is not None
        ]
        if values:
            populated.append((row_no, values))
    return populated


def event_source(source_events, event_text):
    matches = [
        x for x in source_events
        if norm(x["event"]) == norm(event_text)
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"STOP: III.A event match count={len(matches)} for {event_text!r}."
        )
    return matches[0]


def source_effectiveness(source_events, event_text):
    evt = event_source(source_events, event_text)
    raw = text(evt["effectiveness_raw"])
    n = norm(raw)
    if n == "efektif":
        return "efektif", None
    if n == "tidak efektif":
        return "tidak_efektif", None
    if raw:
        return None, "Catatan efektivitas sumber III.A: " + raw
    return None, None


def aggregate_group(group, source_events):
    rows = group["rows"]

    # Monthly actual narrative: only formal H rows with a real actual value.
    treatment_lines = []
    output_lines = []

    actual_rows = [r for r in rows if text(r["actual_plan"]) is not None]
    for idx, row in enumerate(actual_rows, start=1):
        treatment_lines.append(
            f"{idx}. Rencana: {str(row['plan']).strip()}\n"
            f"   Realisasi: {str(row['actual_plan']).strip()}"
        )

    actual_output_rows = [
        r for r in rows if text(r["actual_output"]) is not None
    ]
    for idx, row in enumerate(actual_output_rows, start=1):
        planned_output = text(row["planned_output"]) or "-"
        output_lines.append(
            f"{idx}. Output rencana: {planned_output}\n"
            f"   Realisasi output: {str(row['actual_output']).strip()}"
        )

    plan_nums = [money(r["planned_cost"]) for r in rows]
    plan_nums = [x for x in plan_nums if x is not None]
    actual_nums = [money(r["actual_cost"]) for r in rows]
    actual_nums = [x for x in actual_nums if x is not None]

    planned_cost = sum(plan_nums, Decimal("0.00")) if plan_nums else None
    actual_cost = sum(actual_nums, Decimal("0.00")) if actual_nums else None

    absorption = None
    if planned_cost is not None and actual_cost is not None:
        if planned_cost > 0:
            absorption = (
                actual_cost / planned_cost * Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif planned_cost == 0 and actual_cost == 0:
            absorption = Decimal("0.00")

    progress_values = numeric_values(rows, "progress_q2")
    progress = None
    if progress_values:
        progress = (
            sum(progress_values, Decimal("0"))
            / Decimal(len(progress_values))
            * Decimal("100")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Period consistency: Jan-May only.
    timeline = []
    for month_idx in range(12):
        if month_idx >= 5:
            timeline.append(0)
            continue
        vals = []
        for row in rows:
            raw = row["timeline"][month_idx]
            vals.append(int(D(raw) or 0))
        timeline.append(1 if any(vals) else 0)

    source_statuses = first_unique(rows, "source_status")
    status_text = " | ".join(str(x) for x in source_statuses)
    low = status_text.casefold()
    status_choice = None
    if "discontinue" in low:
        status_choice = "discontinue"
    elif "continue" in low:
        status_choice = "continue"

    all_statuses_lower = [str(x).casefold() for x in source_statuses]
    if all_statuses_lower and all("selesai" in x for x in all_statuses_lower):
        mitigation_status = "done"
    elif (
        actual_rows
        or any(x > 0 for x in progress_values)
        or source_statuses
    ):
        mitigation_status = "on_progress"
    else:
        mitigation_status = "not_started"

    status_notes = []
    for idx, row in enumerate(rows, start=1):
        st = text(row["source_status"])
        ex = text(row["source_status_explanation"])
        if st or ex:
            line = f"{idx}. Status sumber: {st or '-'}"
            if ex:
                line += f" | Penjelasan: {ex}"
            status_notes.append(line)

    plan_non = nonnumeric_values(rows, "planned_cost")
    actual_non = nonnumeric_values(rows, "actual_cost")
    if plan_non:
        status_notes.append(
            "Catatan nilai non-numerik pada kolom rencana biaya sumber: "
            + " | ".join(plan_non)
        )
    if actual_non:
        status_notes.append(
            "Catatan nilai non-numerik pada kolom realisasi biaya sumber: "
            + " | ".join(actual_non)
        )

    effectiveness, effectiveness_note = source_effectiveness(
        source_events, group["event"]
    )
    if effectiveness_note:
        status_notes.append(effectiveness_note)

    pics = first_unique(rows, "pic")
    pic_text = "\n".join(str(x).strip() for x in pics) if pics else None

    # KRI is preserved as source evidence only because header is "Maret",
    # not asserted as current May realization.
    kri_names = first_unique(rows, "kri")
    kri_units = first_unique(rows, "kri_unit")
    safe = first_unique(rows, "kri_safe")
    caution = first_unique(rows, "kri_caution")
    danger = first_unique(rows, "kri_danger")
    source_status = first_unique(rows, "kri_source_status")
    source_value = first_unique(rows, "kri_source_value")

    kri_lines = []
    if any([kri_names, kri_units, safe, caution, danger, source_status, source_value]):
        kri_lines.append(
            "CATATAN: pasangan status/nilai KRI pada workbook sumber berlabel "
            "'Realisasi Threshold KRI Maret'; data dipreservasi sebagai referensi "
            "dan tidak diklaim sebagai realisasi KRI Mei."
        )
    if kri_names:
        kri_lines.append("KRI sumber: " + " | ".join(map(str, kri_names)))
    if kri_units:
        kri_lines.append("Satuan: " + " | ".join(map(str, kri_units)))
    if safe:
        kri_lines.append("Aman: " + " | ".join(map(str, safe)))
    if caution:
        kri_lines.append("Hati-hati: " + " | ".join(map(str, caution)))
    if danger:
        kri_lines.append("Bahaya: " + " | ".join(map(str, danger)))
    if source_status:
        kri_lines.append(
            "Status KRI sumber (kolom berlabel Maret): "
            + " | ".join(map(str, source_status))
        )
    if source_value:
        kri_lines.append(
            "Nilai KRI sumber (kolom berlabel Maret): "
            + " | ".join(map(str, source_value))
        )

    return {
        "treatment_text": "\n".join(treatment_lines) if treatment_lines else None,
        "output_text": "\n".join(output_lines) if output_lines else None,
        "planned_cost": planned_cost,
        "actual_cost": actual_cost,
        "absorption": absorption,
        "pic": pic_text,
        "status_choice": status_choice,
        "status_explanation": "\n".join(status_notes) if status_notes else None,
        "progress": progress,
        "mitigation_status": mitigation_status,
        "timeline": timeline,
        "effectiveness": effectiveness,
        "kri_text": "\n".join(kri_lines) if kri_lines else None,
        "numeric_kri_present": any(D(x) is not None for x in source_value),
        "formal_actual_plan_rows": len(actual_rows),
        "formal_actual_output_rows": len(actual_output_rows),
    }


def source_audit(source_path: Path):
    sha = source_sha256(source_path)
    if sha != EXPECTED_SHA256:
        raise RuntimeError(
            f"STOP source SHA256 mismatch.\n"
            f"Actual  : {sha}\nExpected: {EXPECTED_SHA256}"
        )

    wb = RawWorkbook(source_path)
    try:
        required = {"III.A", "III.B", "III.D", "III.E"}
        missing = required - set(wb.sheet_paths)
        if missing:
            raise RuntimeError(f"STOP source: sheet missing {sorted(missing)}.")

        events = parse_iiia(wb)
        groups, actual_only_rows = parse_iiib(wb)

        iiid = rows_after_start_are_blank(wb, "III.D")
        iiie = rows_after_start_are_blank(wb, "III.E")
        if iiid:
            raise RuntimeError(
                f"STOP source: III.D punya data setelah Start pengisian: {iiid[:5]}"
            )
        if iiie:
            raise RuntimeError(
                f"STOP source: III.E punya data setelah Start pengisian: {iiie[:5]}"
            )

        source_events = {norm(x["event"]) for x in events}
        group_events = {norm(x["event"]) for x in groups}
        if group_events != source_events:
            raise RuntimeError(
                "STOP source: event set III.B tidak sama dengan 19 event III.A."
            )

        # Explicit legacy KRI header check.
        iiib_rows = wb.rows("III.B")
        kri_header = text(iiib_rows.get(4, {}).get(39))
        if norm(kri_header) != "realisasi threshold kri maret":
            raise RuntimeError(
                f"STOP source: KRI header col AM berubah: {kri_header!r}. "
                "Importer V1 dibuat khusus untuk workbook yang diaudit."
            )

        aggs = [aggregate_group(g, events) for g in groups]

        total_plan = sum(
            (a["planned_cost"] or Decimal("0.00")) for a in aggs
        )
        total_actual = sum(
            (a["actual_cost"] or Decimal("0.00")) for a in aggs
        )
        if total_plan != EXPECTED_PLANNED_COST:
            raise RuntimeError(
                f"STOP source: planned total={total_plan}, "
                f"expected={EXPECTED_PLANNED_COST}."
            )
        if total_actual != EXPECTED_ACTUAL_COST:
            raise RuntimeError(
                f"STOP source: actual total={total_actual}, "
                f"expected={EXPECTED_ACTUAL_COST}."
            )

        progress_groups = sum(1 for a in aggs if a["progress"] is not None)
        if progress_groups != EXPECTED_Q2_PROGRESS_GROUPS:
            raise RuntimeError(
                f"STOP source: Q2 progress groups={progress_groups}, "
                f"expected={EXPECTED_Q2_PROGRESS_GROUPS}."
            )

        numeric_kri_groups = sum(
            1 for a in aggs if a["numeric_kri_present"]
        )
        if numeric_kri_groups != EXPECTED_NUMERIC_KRI_GROUPS:
            raise RuntimeError(
                f"STOP source: numeric KRI groups={numeric_kri_groups}, "
                f"expected={EXPECTED_NUMERIC_KRI_GROUPS}."
            )

        # Workbook-level month evidence.
        all_text = wb.all_text().casefold()
        may_mentions = all_text.count("mei 2026")
        june_mentions = all_text.count("juni 2026")
        if may_mentions < 1:
            raise RuntimeError("STOP source: tidak ditemukan evidence 'Mei 2026'.")

        banner("SOURCE AUDIT - UB KITRANS MEI 2026")
        print("Source SHA256                    :", sha)
        print("III.A risk events               :", len(events))
        print("III.A Q2 residual               : BLANK 19/19")
        print("III.B cause groups              :", len(groups))
        print("III.B formal treatment rows (H) :", sum(len(g["rows"]) for g in groups))
        print("Formal rows with actual plan K  :", sum(a["formal_actual_plan_rows"] for a in aggs))
        print("Formal rows with actual output L:", sum(a["formal_actual_output_rows"] for a in aggs))
        print("Actual-only continuation rows   :", len(actual_only_rows), "(tidak dijadikan activity baru)")
        print("Q2 progress populated           :", progress_groups, "/ 40 groups")
        print("Planned cost total              :", total_plan)
        print("Actual cost total               :", total_actual)
        print("III.D                           : 0")
        print("III.E                           : 0")
        print("KRI numeric source groups       :", numeric_kri_groups)
        print("KRI source header               :", repr(kri_header))
        print("KRI policy                      : PRESERVE TEXT ONLY (header=Maret, report=Mei)")
        print("Workbook mentions 'Mei 2026'    :", may_mentions)
        print("Workbook mentions 'Juni 2026'   :", june_mentions)
        print("Timeline policy                 : Jan-Mei copied; Jun-Des = 0")

        return events, groups, aggs
    finally:
        wb.close()


def resolve_baseline():
    profile = (
        ReAssessmentSummary.objects
        .select_related("unit_bisnis", "kontrak_manajemen")
        .get(pk=PROFILE_ID)
    )
    if str(profile) != "Profil Risiko UBKITRANS":
        raise RuntimeError(f"STOP baseline: unexpected profile={profile!r}.")
    if profile.kontrak_manajemen_id != KM_ID:
        raise RuntimeError(
            f"STOP baseline: KM id={profile.kontrak_manajemen_id}, expected={KM_ID}."
        )
    if str(profile.unit_bisnis) != "UB KITRAN":
        raise RuntimeError(
            f"STOP baseline: unexpected unit={profile.unit_bisnis!r}."
        )

    tahun = TahunBuku.objects.filter(tahun=YEAR).first()
    if tahun is None:
        raise RuntimeError("STOP baseline: TahunBuku 2026 tidak ditemukan.")

    period = PeriodeLaporan.objects.filter(
        tahun_buku=tahun,
        kode_periode=PERIOD_CODE,
    ).first()

    user = get_user_model().objects.filter(
        pk=PREPARED_BY_ID,
        is_active=True,
    ).first()
    if user is None:
        raise RuntimeError(
            f"STOP baseline: prepared_by id={PREPARED_BY_ID} tidak ditemukan/aktif."
        )

    existing_may = (
        MonthlyRiskReport.objects
        .filter(
            reassessment=profile,
            tahun_buku__tahun=YEAR,
            periode__kode_periode=PERIOD_CODE,
        )
        .order_by("id")
        .first()
    )
    if existing_may:
        raise RuntimeError(
            f"STOP duplicate: MRR Mei sudah ada: id={existing_may.id} "
            f"kode={existing_may.kode!r} status={existing_may.status!r}."
        )

    june = (
        MonthlyRiskReport.objects
        .select_related("periode")
        .filter(pk=JUNE_REPORT_ID)
        .first()
    )
    if june is None:
        raise RuntimeError(
            f"STOP guard: June MRR id={JUNE_REPORT_ID} tidak ditemukan."
        )
    if june.kode != JUNE_REPORT_CODE or june.reassessment_id != PROFILE_ID:
        raise RuntimeError(
            f"STOP guard: June MRR identity berubah: id={june.id}, "
            f"kode={june.kode!r}, profile={june.reassessment_id}."
        )
    if june.items.count() != 40:
        raise RuntimeError(
            f"STOP guard: June MRR items={june.items.count()}, expected=40."
        )

    return profile, tahun, period, user, june


def validate_representatives(profile, groups):
    if len(REPRESENTATIVE_IDS) != EXPECTED_CAUSES:
        raise RuntimeError("STOP internal: REPRESENTATIVE_IDS bukan 40.")

    reps = {}
    for idx, group in enumerate(groups, start=1):
        expected_id = REPRESENTATIVE_IDS[idx]
        try:
            obj = ReAssessmentItem.objects.get(
                pk=expected_id,
                summary=profile,
                is_active=True,
            )
        except ReAssessmentItem.DoesNotExist:
            raise RuntimeError(
                f"STOP mapping: SRC {idx:02d} expected RE={expected_id} "
                "tidak aktif/tidak ada."
            )

        if event_norm(obj.peristiwa_risiko) != event_norm(group["event"]):
            raise RuntimeError(
                f"STOP mapping: SRC {idx:02d} RE={expected_id} event mismatch."
            )

        if norm(obj.penyebab_risiko) != norm(group["cause_text"]):
            raise RuntimeError(
                f"STOP mapping: SRC {idx:02d} RE={expected_id} cause mismatch.\n"
                f"DB    : {obj.penyebab_risiko!r}\n"
                f"Source: {group['cause_text']!r}"
            )

        source_cause_no = norm(group["cause_no"])
        db_cause_no = norm(obj.no_penyebab_risiko)
        if source_cause_no and db_cause_no != source_cause_no:
            raise RuntimeError(
                f"STOP mapping: SRC {idx:02d} RE={expected_id} "
                f"cause_no DB={obj.no_penyebab_risiko!r} "
                f"source={group['cause_no']!r}."
            )

        reps[idx] = obj

    if len({x.id for x in reps.values()}) != EXPECTED_CAUSES:
        raise RuntimeError("STOP mapping: representative RE tidak unique 40/40.")

    return reps


def preview(profile, tahun, period, user, june, groups, aggs, reps):
    banner("IMPORT PREVIEW - MRR UB KITRANS MEI 2026 V1 SAFE")
    print("Mode                         : DRY RUN")
    print("Profile                      :", profile.id, profile)
    print("Unit                         :", profile.unit_bisnis)
    print("KM                           :", profile.kontrak_manajemen_id, profile.kontrak_manajemen)
    print("TahunBuku                    :", tahun.id, tahun)
    print("Periode Mei                  :", getattr(period, "id", None), period)
    print("Prepared by                  :", user.id, user)
    print("Existing May MRR             : None")
    print("June historical guard        :", june.id, june.kode, "| items=", june.items.count())
    print("Profile rows current         :", profile.item.count())
    print("Database                     : BELUM DIUBAH")

    banner("REPRESENTATIVE MAPPING")
    for idx, (group, agg) in enumerate(zip(groups, aggs), start=1):
        re_obj = reps[idx]
        print(
            f"SRC {idx:02d} -> RE={re_obj.id:<4} | "
            f"activity={len(group['rows']):<2} | "
            f"actual_plan={agg['formal_actual_plan_rows']:<2} | "
            f"actual_output={agg['formal_actual_output_rows']:<2} | "
            f"Q2_progress={str(agg['progress']):<8} | "
            f"plan_cost={str(agg['planned_cost']):<16} | "
            f"actual_cost={str(agg['actual_cost']):<14} | "
            f"event={group['event'][:64]!r}"
        )

    print()
    print("DRY-RUN V1 SAFE OK. Database belum diubah.")
    print("Jangan jalankan --apply sebelum output ini direview.")


def backup_sqlite():
    cfg = settings.DATABASES["default"]
    if "sqlite" not in cfg.get("ENGINE", ""):
        print("BACKUP: skipped; DB bukan SQLite.")
        return None

    src = Path(str(cfg["NAME"])).resolve()
    dst_dir = Path("/home/adminsvr/backup")
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / (
        "db_before_import_mrr_ubkitrans_may_2026_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".sqlite3"
    )

    with sqlite3.connect(src) as source:
        with sqlite3.connect(dst) as target:
            source.backup(target)

    with sqlite3.connect(dst) as con:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk = con.execute("PRAGMA foreign_key_check").fetchall()

    print("BACKUP    :", dst)
    print("INTEGRITY :", integrity)
    print("FK CHECK  :", len(fk), "error")

    if integrity != "ok" or fk:
        raise RuntimeError(
            f"STOP backup health: integrity={integrity}, fk={fk[:5]}."
        )

    return dst


def ensure_period(tahun, period):
    if period is not None:
        return period

    last_day = calendar.monthrange(YEAR, MONTH)[1]
    return PeriodeLaporan.objects.create(
        tahun_buku=tahun,
        kode_periode=PERIOD_CODE,
        nama_periode="Mei 2026",
        jenis_periode="bulanan",
        tanggal_mulai="2026-05-01",
        tanggal_selesai=f"2026-05-{last_day:02d}",
        is_locked=False,
    )


def db_health():
    cfg = settings.DATABASES["default"]
    if "sqlite" not in cfg.get("ENGINE", ""):
        return None, None

    with sqlite3.connect(str(cfg["NAME"])) as con:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
    return integrity, fk


def apply_import(profile, tahun, period, user, june, events, groups, aggs, reps):
    backup_sqlite()

    profile_row_count_before = profile.item.count()
    june_item_ids_before = list(
        june.items.order_by("id").values_list("id", flat=True)
    )
    june_snapshot_before = list(
        june.items.order_by("id").values(
            "id",
            "risk_event_id",
            "realisasi_rencana_perlakuan",
            "realisasi_output_perlakuan",
            "realisasi_biaya_perlakuan",
            "progress_pelaksanaan_percent",
            "realisasi_threshold_kri",
            "realisasi_nilai_kri",
            "realisasi_kri_text",
        )
    )

    with transaction.atomic():
        locked_profile = (
            ReAssessmentSummary.objects
            .select_for_update()
            .select_related("kontrak_manajemen", "unit_bisnis")
            .get(pk=PROFILE_ID)
        )

        if MonthlyRiskReport.objects.filter(
            reassessment=locked_profile,
            tahun_buku__tahun=YEAR,
            periode__kode_periode=PERIOD_CODE,
        ).exists():
            raise RuntimeError("STOP race guard: MRR Mei muncul sebelum create.")

        # Lock and revalidate all 40 canonical representatives.
        locked_reps = {}
        for idx, group in enumerate(groups, start=1):
            rid = REPRESENTATIVE_IDS[idx]
            obj = (
                ReAssessmentItem.objects
                .select_for_update()
                .get(pk=rid, summary=locked_profile, is_active=True)
            )
            if event_norm(obj.peristiwa_risiko) != event_norm(group["event"]):
                raise RuntimeError(
                    f"STOP lock mapping: SRC {idx:02d} RE={rid} event changed."
                )
            if norm(obj.penyebab_risiko) != norm(group["cause_text"]):
                raise RuntimeError(
                    f"STOP lock mapping: SRC {idx:02d} RE={rid} cause changed."
                )
            locked_reps[idx] = obj

        period = ensure_period(tahun, period)

        report = MonthlyRiskReport.objects.create(
            kode=REPORT_CODE,
            tahun_buku=tahun,
            periode=period,
            unit=None,
            kontrak_manajemen=locked_profile.kontrak_manajemen,
            reassessment=locked_profile,
            versi=1,
            status="draft",
            prepared_by=user,
        )

        created_items = []

        for idx, (group, agg) in enumerate(zip(groups, aggs), start=1):
            risk_event = locked_reps[idx]

            # Initial save with KRI NULL so model-level KRI evaluator is not invoked.
            item = MonthlyRiskReportItem.objects.create(
                report=report,
                risk_event=risk_event,
                km_item=risk_event.km_item,
            )

            created_items.append(item)

        # Build source event map once. All write values come from the exact
        # audited in-memory source snapshot.
        evt_by_norm = {norm(x["event"]): x for x in events}

        for idx, (group, agg, item) in enumerate(
            zip(groups, aggs, created_items),
            start=1,
        ):
            evt = evt_by_norm[norm(group["event"])]
            jenis_norm = norm(evt["jenis"])
            jenis = (
                "kuantitatif" if jenis_norm == "kuantitatif"
                else "kualitatif" if jenis_norm == "kualitatif"
                else None
            )

            update = {
                "jenis_risiko": jenis,
                "realisasi_asumsi_dampak": text(evt["assumption"]),

                # Q2 source is explicitly blank.
                "realisasi_nilai_dampak": None,
                "realisasi_skala_dampak_id": None,
                "realisasi_nilai_probabilitas": None,
                "realisasi_skala_probabilitas_id": None,
                "realisasi_skala_dampak_kbumn": None,
                "realisasi_skala_probabilitas_kbumn": None,
                "realisasi_eksposur": None,
                "realisasi_skor_risiko": None,
                "realisasi_skala_nilai_risiko_kbumn": None,
                "realisasi_level_risiko": None,
                "realisasi_level_risiko_bumn": None,
                "realisasi_level_risiko_kbumn": None,

                "efektivitas_perlakuan_risiko": agg["effectiveness"],
                "realisasi_rencana_perlakuan": agg["treatment_text"],
                "realisasi_output_perlakuan": agg["output_text"],
                "rencana_biaya_perlakuan": agg["planned_cost"],
                "realisasi_biaya_perlakuan": agg["actual_cost"],
                "persentase_serapan_biaya": agg["absorption"],
                "realisasi_pic": agg["pic"],
                "realisasi_pic_organization_unit_id": None,
                "status_rencana_perlakuan": agg["status_choice"],
                "penjelasan_status_rencana": agg["status_explanation"],
                "progress_pelaksanaan_percent": agg["progress"],
                "mitigation_progress_percent": agg["progress"],
                "mitigation_status": agg["mitigation_status"],

                # Conservative KRI month policy: source columns are labelled Maret.
                "realisasi_threshold_kri": None,
                "realisasi_nilai_kri": None,
                "realisasi_kri_text": agg["kri_text"],
                "realisasi_threshold_kri_skor": None,

                "trend": None,
                "issue_summary": None,
                "next_action": None,
                "escalation_note": None,
                "updated_at": timezone.now(),
            }

            for month_no, flag in enumerate(agg["timeline"], start=1):
                update[f"realisasi_timeline_{month_no}"] = int(flag)

            MonthlyRiskReportItem.objects.filter(pk=item.pk).update(**update)

        # Source III.D and III.E are empty; enforce empty report children.
        if MonthlyRiskReportChange.objects.filter(report=report).exists():
            raise RuntimeError("STOP: unexpected III.D objects created.")
        if MonthlyRiskReportLossEvent.objects.filter(report=report).exists():
            raise RuntimeError("STOP: unexpected III.E objects created.")

        report.total_risiko = EXPECTED_EVENTS
        report.total_high = 0
        report.total_mitigasi_terlambat = 0
        report.total_selesai = 0
        report.save(update_fields=[
            "total_risiko",
            "total_high",
            "total_mitigasi_terlambat",
            "total_selesai",
            "updated_at",
        ])

        postcheck_in_transaction(
            locked_profile,
            report,
            groups,
            aggs,
            locked_reps,
            profile_row_count_before,
            june_item_ids_before,
            june_snapshot_before,
        )

    integrity, fk = db_health()
    if integrity is not None:
        if integrity != "ok" or fk:
            raise RuntimeError(
                f"POST-COMMIT DB HEALTH FAILED: integrity={integrity}, fk={fk[:5]}."
            )

    report.refresh_from_db()
    checked = list(
        report.items.select_related("risk_event").order_by("id")
    )

    banner("APPLY BERHASIL - MRR UB KITRANS MEI 2026")
    print("Profile ID                  :", report.reassessment_id)
    print("MRR ID                      :", report.id)
    print("MRR code                    :", report.kode)
    print("Period                      :", report.periode)
    print("Status                      :", report.status)
    print("Prepared by                 :", report.prepared_by)
    print("Source risk events          :", EXPECTED_EVENTS)
    print("Monthly cause items         :", len(checked))
    print("Source treatment rows       :", EXPECTED_TREATMENT_ROWS)
    print("Q2 residual imported        : 0/40 (source blank)")
    print("III.D changes               : 0")
    print("III.E loss events           : 0")
    print("Planned cost total          :", sum(
        (x.rencana_biaya_perlakuan or Decimal("0")) for x in checked
    ))
    print("Actual cost total           :", sum(
        (x.realisasi_biaya_perlakuan or Decimal("0")) for x in checked
    ))
    print("KRI policy                  : text evidence only; header source=Maret")
    print("June report id=84           : unchanged")
    print("Profile rows                : unchanged")
    print("integrity_check             :", integrity)
    print("foreign_key_check           :", len(fk or []), "error")

    for x in checked:
        print(
            f"MRI={x.id:<5} | RE={x.risk_event_id:<4} | "
            f"cause={str(x.risk_event.no_penyebab_risiko):<4} | "
            f"progress={str(x.progress_pelaksanaan_percent):<8} | "
            f"plan={str(x.rencana_biaya_perlakuan):<16} | "
            f"actual={str(x.realisasi_biaya_perlakuan):<14} | "
            f"event={x.risk_event.peristiwa_risiko[:65]!r}"
        )


def postcheck_in_transaction(
    profile,
    report,
    groups,
    aggs,
    reps,
    profile_row_count_before,
    june_item_ids_before,
    june_snapshot_before,
):
    items = list(
        MonthlyRiskReportItem.objects
        .filter(report=report)
        .select_related("risk_event")
        .order_by("id")
    )
    if len(items) != EXPECTED_CAUSES:
        raise RuntimeError(
            f"STOP postcheck: items={len(items)}, expected={EXPECTED_CAUSES}."
        )

    ids = [x.risk_event_id for x in items]
    expected_ids = [REPRESENTATIVE_IDS[i] for i in range(1, 41)]
    if ids != expected_ids:
        raise RuntimeError(
            f"STOP postcheck: RE order/set mismatch.\nDB={ids}\nExpected={expected_ids}"
        )
    if len(set(ids)) != EXPECTED_CAUSES:
        raise RuntimeError("STOP postcheck: duplicate risk_event in May MRR.")

    distinct_events = {event_norm(x.risk_event.peristiwa_risiko) for x in items}
    source_events = {event_norm(g["event"]) for g in groups}
    if distinct_events != source_events or len(distinct_events) != EXPECTED_EVENTS:
        raise RuntimeError(
            "STOP postcheck: distinct event set != 19 source events."
        )

    # No legacy non-source rows.
    if MonthlyRiskReportItem.objects.filter(
        report=report,
        risk_event_id__in=[386, 388],
    ).exists():
        raise RuntimeError("STOP postcheck: RE386/RE388 should not be imported.")

    # Q2 residual must remain fully blank.
    for item in items:
        residual_values = [
            item.realisasi_nilai_dampak,
            item.realisasi_skala_dampak_id,
            item.realisasi_nilai_probabilitas,
            item.realisasi_skala_probabilitas_id,
            item.realisasi_skala_dampak_kbumn,
            item.realisasi_skala_probabilitas_kbumn,
            item.realisasi_eksposur,
            item.realisasi_skor_risiko,
            item.realisasi_skala_nilai_risiko_kbumn,
            item.realisasi_level_risiko,
            item.realisasi_level_risiko_bumn,
            item.realisasi_level_risiko_kbumn,
        ]
        if any(v not in (None, "") for v in residual_values):
            raise RuntimeError(
                f"STOP postcheck: MRI={item.id} invented Q2 residual values."
            )

        # Future timeline must not leak into May.
        for month_no in range(6, 13):
            if int(getattr(item, f"realisasi_timeline_{month_no}", 0) or 0) != 0:
                raise RuntimeError(
                    f"STOP postcheck: MRI={item.id} timeline month={month_no} != 0."
                )

        # KRI current May fields intentionally blank due source header mismatch.
        if item.realisasi_threshold_kri not in (None, ""):
            raise RuntimeError(
                f"STOP postcheck: MRI={item.id} has May KRI status despite Maret header."
            )
        if item.realisasi_nilai_kri is not None:
            raise RuntimeError(
                f"STOP postcheck: MRI={item.id} has numeric May KRI despite Maret header."
            )
        if item.realisasi_threshold_kri_skor not in (None, ""):
            raise RuntimeError(
                f"STOP postcheck: MRI={item.id} has KRI range despite Maret header."
            )

    agg = MonthlyRiskReportItem.objects.filter(report=report).aggregate(
        planned=Sum("rencana_biaya_perlakuan"),
        actual=Sum("realisasi_biaya_perlakuan"),
    )
    # SUM ignores NULL; compare exact source totals.
    if agg["planned"] != EXPECTED_PLANNED_COST:
        raise RuntimeError(
            f"STOP postcheck: planned={agg['planned']}, "
            f"expected={EXPECTED_PLANNED_COST}."
        )
    if agg["actual"] != EXPECTED_ACTUAL_COST:
        raise RuntimeError(
            f"STOP postcheck: actual={agg['actual']}, "
            f"expected={EXPECTED_ACTUAL_COST}."
        )

    if MonthlyRiskReportChange.objects.filter(report=report).exists():
        raise RuntimeError("STOP postcheck: III.D should be empty.")
    if MonthlyRiskReportLossEvent.objects.filter(report=report).exists():
        raise RuntimeError("STOP postcheck: III.E should be empty.")

    # Profile is read-only in this importer.
    if profile.item.count() != profile_row_count_before:
        raise RuntimeError(
            "STOP postcheck: profile item count changed; rollback."
        )

    # June historical report must be byte-for-business-field unchanged.
    june = MonthlyRiskReport.objects.get(pk=JUNE_REPORT_ID)
    june_ids_after = list(
        june.items.order_by("id").values_list("id", flat=True)
    )
    if june_ids_after != june_item_ids_before:
        raise RuntimeError("STOP postcheck: June MRR item IDs changed.")

    june_snapshot_after = list(
        june.items.order_by("id").values(
            "id",
            "risk_event_id",
            "realisasi_rencana_perlakuan",
            "realisasi_output_perlakuan",
            "realisasi_biaya_perlakuan",
            "progress_pelaksanaan_percent",
            "realisasi_threshold_kri",
            "realisasi_nilai_kri",
            "realisasi_kri_text",
        )
    )
    if june_snapshot_after != june_snapshot_before:
        raise RuntimeError("STOP postcheck: June MRR business data changed.")

    report.refresh_from_db()
    if report.kode != REPORT_CODE:
        raise RuntimeError("STOP postcheck: report code changed.")
    if report.reassessment_id != PROFILE_ID:
        raise RuntimeError("STOP postcheck: profile changed.")
    if report.kontrak_manajemen_id != KM_ID:
        raise RuntimeError("STOP postcheck: KM changed.")
    if report.periode.kode_periode != PERIOD_CODE:
        raise RuntimeError("STOP postcheck: period is not 2026-05.")
    if report.total_risiko != EXPECTED_EVENTS:
        raise RuntimeError(
            f"STOP postcheck: total_risiko={report.total_risiko}, expected=19."
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help="Path source XLSX Laporan Manajemen Risiko UBKITRANS Mei 2026.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit import. Default adalah DRY-RUN.",
    )
    args = parser.parse_args()

    source_path = args.source.expanduser().resolve()
    if not source_path.exists():
        raise RuntimeError(f"STOP: source file tidak ditemukan: {source_path}")

    events, groups, aggs = source_audit(source_path)

    profile, tahun, period, user, june = resolve_baseline()
    reps = validate_representatives(profile, groups)

    if not args.apply:
        preview(profile, tahun, period, user, june, groups, aggs, reps)
        return

    banner("APPLY MODE")
    print("Source:", source_path)
    print("Target: UB KITRANS / Mei 2026")
    print("Database akan dibackup sebelum transaksi.")

    apply_import(profile, tahun, period, user, june, events, groups, aggs, reps)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print("\nERROR:", exc, file=sys.stderr)
        raise SystemExit(2)
