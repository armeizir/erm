#!/usr/bin/env python3
"""
REPAIR PROFIL RISIKO SETPER 2026 - KELENGKAPAN JULI 2026 - V1 SAFE

Tujuan
------
Memperbaiki HANYA kekurangan profil SETPER 2026 yang sudah direview terhadap
workbook resmi:

    Laporan Mitigasi Risiko Bidang Setper s.d Juli 2026 (1).xlsx
    SHA256:
    30f3135b18d92e2ab259e1d3072835a57d5385ffe12f5eff721d7eed6cdc1fb5

Scope perubahan:
1. Propagasi konfigurasi KRI resmi ke seluruh cause-row untuk Item 1..8.
2. Item 7 adalah risiko KUALITATIF:
   - kategori_dampak dipastikan ke master kualitatif bila masih kosong;
   - jenis_risiko='kualitatif' bila field tersebut tersedia dan masih kosong;
   - nilai_dampak inheren TIDAK diisi/direkayasa.
3. Item 7 target residual Nilai Dampak Q1..Q4 yang kosong diisi 0 sesuai source.

Yang TIDAK diubah:
- KM / RKM.
- MonthlyRiskReport dan historinya.
- Peristiwa, penyebab, kontrol, perlakuan, PIC, timeline.
- Nilai dampak inheren kualitatif.
- Nilai residual selain nilai_dampak_q1..q4 Item 7.
- KRI direction, karena workbook source tidak memberikan field arah secara eksplisit.

Safety:
- Default = DRY RUN; seluruh perubahan rollback.
- --apply = commit.
- --apply WAJIB menyertakan --source dan SHA256 harus exact.
- SQLite online backup + PRAGMA quick_check sebelum commit.
- Mapping dikunci dengan no_item + normalized exact event.
- Expected cause-row count Item 1..8 diverifikasi.
- Existing nonblank KRI yang berbeda dari source menyebabkan STOP.
- Existing nonzero nilai_dampak_q1..q4 Item 7 menyebabkan STOP.
- Existing kategori Item 7 yang bukan kualitatif menyebabkan STOP.
- Menggunakan QuerySet.update() agar tidak memicu kalkulasi otomatis model.
- Setelah perubahan, profile completeness dihitung ulang di dalam transaksi.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path("/home/adminsvr/erm")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.prod")

import django  # noqa: E402
django.setup()

from django.conf import settings  # noqa: E402
from django.db import transaction  # noqa: E402

from risk.models import (  # noqa: E402
    MasterKategoriDampak,
    ReAssessmentItem,
    ReAssessmentSummary,
)
from risk.services.profile_completeness import (  # noqa: E402
    check_profile_completeness,
    profile_completeness_queryset,
)

YEAR = 2026
EXPECTED_SOURCE_SHA256 = (
    "30f3135b18d92e2ab259e1d3072835a57d5385ffe12f5eff721d7eed6cdc1fb5"
)

EXPECTED_ROW_COUNTS = {
    1: 2,
    2: 5,
    3: 3,
    4: 3,
    5: 4,
    6: 2,
    7: 2,
    8: 2,
}

SOURCE = {
    1: {
        "event": (
            "Kendala Pemenuhan Parameter Sustainability "
            "(Enviromental, Social Governance) ESG Risk Rating"
        ),
        "kri": (
            "Realisasi Program Keterlibatan Masyarakat dalam Kegiatan "
            "Ketenagalistrikan sesuai Indikator Kinerja Maturity Level Sustainability"
        ),
        "unit": "Persen",
        "safe": ">100%",
        "caution": "70-92%",
        "danger": "<70%",
    },
    2: {
        "event": (
            "Penerapan Good Corporate Governance (GCG) belum berjalan efektif "
            "dan berkelanjutan sehingga maturity level GCG tidak meningkat atau menurun."
        ),
        "kri": "Skor maturity GCG tahunan",
        "unit": "Nilai",
        "safe": ">2,2",
        "caution": "<2,2-2,0",
        "danger": "<2,0",
    },
    3: {
        "event": "Tidak akurat dalam penerbitan pendapat hukum",
        "kri": "Jumlah sengketa/temuan hukum yang terkait advis hukum",
        "unit": "Jumlah",
        "safe": "0",
        "caution": "1",
        "danger": ">1",
    },
    4: {
        "event": "Terjadinya dispute antara Para Pihak di dalam Perjanjian",
        "kri": "Penyelesaian Pendampingan",
        "unit": "%",
        "safe": "100",
        "caution": "≤100%-90%",
        "danger": "≤ 90%",
    },
    5: {
        "event": (
            "Distorsi informasi publik atau komunikasi krisis yang tidak "
            "tertangani secara cepat dan tepat."
        ),
        "kri": "Rasio Jumlah pemberitaan negatif dibandingkan total berita",
        "unit": "%",
        "safe": "0",
        "caution": "0.01",
        "danger": ">1%",
    },
    6: {
        "event": "Realisasi Biaya administrasi tidak sesuai rencana bayar yang disampaikan",
        "kri": "Realisasi Penggunaan Anggaran dibandingkan dengan SKAO Terbit",
        "unit": "%",
        "safe": "<90%",
        "caution": ">90% s.d 95%",
        "danger": ">95%",
    },
    7: {
        "event": "Munculnya risiko baru diluar profil risiko yang telah dicapture",
        "kri": "Frekuensi perubahan atau penambahan risiko dalam risk register.",
        "unit": "Jumlah",
        "safe": "0",
        "caution": "1",
        "danger": ">1",
    },
    8: {
        "event": "Tidak optimalnya implementasi Sistem Manajemen Terintegrasi",
        "kri": "Persentase penyelesaian rencana aksi perbaikan dari hasil audit.",
        "unit": "%",
        "safe": "1",
        "caution": "<100% s.d 95%",
        "danger": "<95%",
    },
}

KRI_FIELDS = {
    "key_risk_indicators": "kri",
    "unit_satuan_kri": "unit",
    "threshold_aman": "safe",
    "threshold_hati_hati": "caution",
    "threshold_bahaya": "danger",
}

RISK7_Q_IMPACT = {
    "nilai_dampak_q1": Decimal("0"),
    "nilai_dampak_q2": Decimal("0"),
    "nilai_dampak_q3": Decimal("0"),
    "nilai_dampak_q4": Decimal("0"),
}


def banner(text: str, width: int = 132) -> None:
    print("\n" + "=" * width)
    print(text)
    print("=" * width)


def norm_event(value) -> str:
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = value.casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def cmp_value(value) -> str:
    """Comparison that ignores whitespace/case but preserves operators/punctuation."""
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", "", value)


def cmp_unit(value) -> str:
    """
    Normalize equivalent KRI units.

    Official Excel may use 'Persen', while existing ERM data uses '%'.
    They are semantically identical and must not be treated as a conflict.
    """
    value = cmp_value(value)

    aliases = {
        "persen": "%",
        "percent": "%",
        "percentage": "%",
        "%": "%",
    }
    return aliases.get(value, value)


def cmp_threshold(value) -> str:
    """
    Normalize threshold representation ONLY for comparison.

    Examples treated as equivalent:
      >2,2  == >2.2
      <2,2-2,0 == <2.2-2.0
      ≤90%  == <=90%
      ≥95%  == >=95%
      ' > 90% s.d 95% ' == '>90%s.d95%'

    Existing database values are not rewritten.
    """
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()

    value = (
        value
        .replace("≤", "<=")
        .replace("≥", ">=")
        .replace("–", "-")
        .replace("—", "-")
    )

    # Indonesian decimal comma -> decimal point,
    # but only when comma occurs between digits.
    value = re.sub(r"(?<=\d),(?=\d)", ".", value)

    # Ignore whitespace differences.
    value = re.sub(r"\s+", "", value)

    # Controlled semantic aliases that have been verified against
    # the official SETPER source.
    #
    # GCG Hati-Hati:
    # Excel : <2,2-2,0
    # ERM   : 2.0-2.2
    # Meaning: interval 2.0 s.d. 2.2.
    aliases = {
        "<2.2-2.0": "2.0-2.2",
        "2.0-2.2": "2.0-2.2",
    }

    return aliases.get(value, value)


def canonical_unit_value(value):
    """Keep ERM percentage unit convention as '%'."""
    if cmp_unit(value) == "%":
        return "%"
    return value


def is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_source(path: Path | None, *, required: bool) -> None:
    banner("SOURCE PREFLIGHT")
    print("Expected SHA256 :", EXPECTED_SOURCE_SHA256)
    if path is None:
        if required:
            raise RuntimeError(
                "STOP: mode --apply wajib menyertakan --source workbook resmi."
            )
        print("Source file     : tidak diberikan")
        print("Mode            : embedded locked values; DRY RUN masih diizinkan")
        return

    path = path.expanduser().resolve()
    if not path.is_file():
        raise RuntimeError(f"STOP: source workbook tidak ditemukan: {path}")
    actual = sha256_file(path)
    print("Source file     :", path)
    print("Actual SHA256   :", actual)
    if actual != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(
            "STOP: SHA256 source berbeda. Jangan gunakan workbook yang belum direview."
        )
    print("SOURCE SHA256   : PASS")


def field_exists(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False


def active_items_qs(profile):
    qs = ReAssessmentItem.objects.filter(summary=profile)
    if field_exists(ReAssessmentItem, "is_active"):
        qs = qs.filter(is_active=True)
    return qs


def resolve_profile():
    """
    Resolve SETPER 2026 conservatively.

    Prefer historical production profile id=13 only if unit/year semantics still match.
    Otherwise require exactly one SETPER/SEKPER 2026 candidate.
    """
    candidates = list(
        ReAssessmentSummary.objects
        .select_related("unit_bisnis", "kontrak_manajemen", "rkm")
        .filter(tahun=YEAR)
        .order_by("pk")
    )

    def is_setper(p):
        unit = str(getattr(getattr(p, "unit_bisnis", None), "name", "") or "")
        title = str(getattr(p, "judul", "") or "")
        n = norm_event(unit + " " + title)
        return "setper" in n or "sekper" in n

    candidates = [p for p in candidates if is_setper(p)]

    preferred = [p for p in candidates if p.pk == 13]
    if len(preferred) == 1:
        profile = preferred[0]
    elif len(candidates) == 1:
        profile = candidates[0]
    else:
        detail = ", ".join(
            f"id={p.pk}/{p.judul!r}/unit={p.unit_bisnis}"
            for p in candidates
        )
        raise RuntimeError(
            "STOP: profil SETPER 2026 tidak dapat dipilih secara unique. "
            f"Candidates={len(candidates)} [{detail}]"
        )

    unit_name = str(getattr(getattr(profile, "unit_bisnis", None), "name", "") or "")
    if "setper" not in norm_event(unit_name) and "sekper" not in norm_event(unit_name):
        raise RuntimeError(
            f"STOP: unit profil id={profile.pk} bukan SETPER/SEKPER: {unit_name!r}"
        )

    return profile


def resolve_mapping(profile):
    qs = active_items_qs(profile).order_by("no_item", "no_risiko", "pk")
    rows = list(qs)

    banner("PROFILE / ITEM PREFLIGHT")
    print(
        f"Profile : id={profile.pk} | {profile.judul!r} | tahun={profile.tahun} "
        f"| unit={profile.unit_bisnis!r} | KM={profile.kontrak_manajemen_id} "
        f"| RKM={getattr(profile, 'rkm_id', None)}"
    )
    print("Active rows:", len(rows))

    mapping = {}
    for no_item in range(1, 9):
        expected = SOURCE[no_item]
        group = [x for x in rows if int(x.no_item or 0) == no_item]

        if len(group) != EXPECTED_ROW_COUNTS[no_item]:
            raise RuntimeError(
                f"STOP: Item {no_item} row count={len(group)}, "
                f"expected={EXPECTED_ROW_COUNTS[no_item]}."
            )

        bad = [
            x for x in group
            if norm_event(x.peristiwa_risiko) != norm_event(expected["event"])
        ]
        if bad:
            detail = "; ".join(
                f"RE={x.pk} event={x.peristiwa_risiko!r}" for x in bad
            )
            raise RuntimeError(
                f"STOP: event Item {no_item} berbeda dari source resmi. {detail}"
            )

        mapping[no_item] = group
        print(
            f"Item {no_item}: rows={len(group)} | "
            f"RE={','.join(str(x.pk) for x in group)} | {expected['event']}"
        )

    return mapping


def resolve_qualitative_category():
    candidates = []
    for obj in MasterKategoriDampak.objects.filter(aktif=True).order_by("pk"):
        name = str(getattr(obj, "nama", "") or "")
        if "kual" in norm_event(name):
            candidates.append(obj)

    if len(candidates) != 1:
        detail = ", ".join(f"{x.pk}:{x}" for x in candidates)
        raise RuntimeError(
            "STOP: master kategori dampak kualitatif tidak unique. "
            f"Candidates={len(candidates)} [{detail}]"
        )

    return candidates[0]


def completeness(profile_id):
    profile = profile_completeness_queryset().get(pk=profile_id)
    return check_profile_completeness(profile)


def finding_text(finding) -> str:
    label = (
        getattr(finding, "item_label", None)
        or getattr(finding, "label", None)
        or ""
    )
    message = getattr(finding, "message", None) or str(finding)
    section = getattr(finding, "section", None) or ""
    return f"{section} | {label} | {message}".strip(" |")


def show_completeness(label: str, result) -> None:
    banner(label)
    print("Required   :", getattr(result, "required_count", "?"))
    print("Completed  :", getattr(result, "completed_count", "?"))
    print("Incomplete :", getattr(result, "incomplete_count", "?"))
    print("Percentage :", getattr(result, "percentage", "?"))
    print("Status     :", getattr(result, "status_label", "?"))
    print("Errors     :", getattr(result, "error_count", "?"))
    print("Warnings   :", getattr(result, "warning_count", "?"))

    findings = list(getattr(result, "findings", []) or [])
    if findings:
        print("\nFindings:")
        for finding in findings:
            print(" -", finding_text(finding))
    else:
        print("\nFindings: NONE")


def sqlite_backup() -> Path:
    db = settings.DATABASES["default"]
    engine = str(db.get("ENGINE", ""))
    if "sqlite3" not in engine:
        raise RuntimeError(
            "STOP: automatic backup script ini hanya untuk SQLite. "
            f"ENGINE={engine!r}"
        )

    db_path = Path(db["NAME"]).expanduser().resolve()
    if not db_path.is_file():
        raise RuntimeError(f"STOP: SQLite DB tidak ditemukan: {db_path}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"db_before_setper_profile_repair_{stamp}.sqlite3"

    with sqlite3.connect(str(db_path), timeout=30) as src:
        check = src.execute("PRAGMA quick_check").fetchone()
        if not check or str(check[0]).lower() != "ok":
            raise RuntimeError(f"STOP: source DB quick_check gagal: {check}")
        with sqlite3.connect(str(backup_path), timeout=30) as dst:
            src.backup(dst)
            dst.commit()

    with sqlite3.connect(str(backup_path), timeout=30) as verify:
        check = verify.execute("PRAGMA quick_check").fetchone()
        if not check or str(check[0]).lower() != "ok":
            raise RuntimeError(f"STOP: backup DB quick_check gagal: {check}")

    return backup_path


def plan_kri_updates(mapping):
    changes = []
    missing_rows_before = 0

    banner("KRI REPAIR PLAN")
    for no_item, rows in mapping.items():
        source = SOURCE[no_item]

        for item in rows:
            row_missing = any(
                is_blank(getattr(item, field))
                for field in KRI_FIELDS
            )
            missing_rows_before += int(row_missing)

            updates = {}
            for field, source_key in KRI_FIELDS.items():
                old = getattr(item, field)
                new = source[source_key]

                if field == "unit_satuan_kri":
                    old_cmp = cmp_unit(old)
                    new_cmp = cmp_unit(new)
                    fill_value = canonical_unit_value(new)

                elif field in {
                    "threshold_aman",
                    "threshold_hati_hati",
                    "threshold_bahaya",
                }:
                    old_cmp = cmp_threshold(old)
                    new_cmp = cmp_threshold(new)
                    fill_value = new

                else:
                    old_cmp = cmp_value(old)
                    new_cmp = cmp_value(new)
                    fill_value = new

                if is_blank(old):
                    updates[field] = fill_value
                elif old_cmp != new_cmp:
                    raise RuntimeError(
                        f"STOP: KRI conflict Item {no_item} RE={item.pk} field={field}.\n"
                        f"DB ={old!r}\nSRC={new!r}"
                    )

            if updates:
                changes.append((item.pk, no_item, updates))
                print(
                    f"RE={item.pk:<4} | Item={no_item} | "
                    f"fill={','.join(updates.keys())}"
                )

    if missing_rows_before > 15:
        raise RuntimeError(
            f"STOP: KRI incomplete rows={missing_rows_before}, melebihi baseline 15."
        )

    print("\nKRI rows incomplete before :", missing_rows_before)
    print("KRI rows to update         :", len(changes))
    return changes


def plan_risk7_updates(mapping, qualitative_category):
    changes = []
    rows = mapping[7]
    has_jenis_risiko = field_exists(ReAssessmentItem, "jenis_risiko")

    banner("ITEM 7 QUALITATIVE / Q1-Q4 REPAIR PLAN")
    print(
        f"Qualitative master: id={qualitative_category.pk} | "
        f"{qualitative_category}"
    )
    print("Field jenis_risiko:", "AVAILABLE" if has_jenis_risiko else "NOT PRESENT")

    for item in rows:
        updates = {}

        # Source says inherent impact is qualitative / not mandatory.
        # Never fabricate a monetary impact.
        if item.nilai_dampak is not None:
            print(
                f"WARNING RE={item.pk}: nilai_dampak inheren sudah berisi "
                f"{item.nilai_dampak!r}; script tidak mengubahnya."
            )

        current_cat = getattr(item, "kategori_dampak", None)
        if current_cat is None:
            updates["kategori_dampak_id"] = qualitative_category.pk
        else:
            current_name = str(current_cat)
            if "kual" not in norm_event(current_name):
                raise RuntimeError(
                    f"STOP: RE={item.pk} Item 7 kategori_dampak saat ini "
                    f"{current_cat!r}, bukan kualitatif."
                )

        if has_jenis_risiko:
            current_kind = getattr(item, "jenis_risiko", None)
            if is_blank(current_kind):
                updates["jenis_risiko"] = "kualitatif"
            elif str(current_kind).strip().casefold() != "kualitatif":
                raise RuntimeError(
                    f"STOP: RE={item.pk} Item 7 jenis_risiko={current_kind!r}, "
                    "bukan kualitatif."
                )

        for field, new in RISK7_Q_IMPACT.items():
            old = getattr(item, field)
            if old is None:
                updates[field] = new
            elif Decimal(str(old)) != Decimal("0"):
                raise RuntimeError(
                    f"STOP: RE={item.pk} {field}={old!r}, "
                    "source resmi yang direview adalah 0."
                )

        if updates:
            changes.append((item.pk, updates))
            print(
                f"RE={item.pk:<4} | fill="
                + ",".join(f"{k}={v}" for k, v in updates.items())
            )
        else:
            print(f"RE={item.pk:<4} | already aligned")

    return changes


def apply_updates(kri_changes, risk7_changes):
    for pk, _no_item, updates in kri_changes:
        updated = ReAssessmentItem.objects.filter(pk=pk).update(**updates)
        if updated != 1:
            raise RuntimeError(f"STOP: gagal update KRI RE={pk}; rows={updated}")

    for pk, updates in risk7_changes:
        updated = ReAssessmentItem.objects.filter(pk=pk).update(**updates)
        if updated != 1:
            raise RuntimeError(f"STOP: gagal update Item7 RE={pk}; rows={updated}")


def verify_targets(profile, mapping):
    # Refresh objects after QuerySet.update().
    refreshed = resolve_mapping(profile)

    banner("TARGET VERIFICATION")
    for no_item, rows in refreshed.items():
        source = SOURCE[no_item]
        for item in rows:
            for field, source_key in KRI_FIELDS.items():
                actual = getattr(item, field)
                expected = source[source_key]

                if field == "unit_satuan_kri":
                    matched = cmp_unit(actual) == cmp_unit(expected)

                elif field in {
                    "threshold_aman",
                    "threshold_hati_hati",
                    "threshold_bahaya",
                }:
                    matched = (
                        cmp_threshold(actual)
                        == cmp_threshold(expected)
                    )

                else:
                    matched = cmp_value(actual) == cmp_value(expected)

                if not matched:
                    raise RuntimeError(
                        f"STOP VERIFY: Item {no_item} RE={item.pk} field={field} mismatch."
                    )
        print(f"KRI Item {no_item}: PASS ({len(rows)} rows)")

    qualitative = resolve_qualitative_category()
    for item in refreshed[7]:
        if getattr(item, "kategori_dampak_id", None) != qualitative.pk:
            raise RuntimeError(
                f"STOP VERIFY: Item7 RE={item.pk} kategori_dampak belum kualitatif."
            )

        if field_exists(ReAssessmentItem, "jenis_risiko"):
            if getattr(item, "jenis_risiko", None) != "kualitatif":
                raise RuntimeError(
                    f"STOP VERIFY: Item7 RE={item.pk} jenis_risiko belum kualitatif."
                )

        # Inherent numeric impact is intentionally not required/filled by this repair.
        for field in RISK7_Q_IMPACT:
            if Decimal(str(getattr(item, field))) != Decimal("0"):
                raise RuntimeError(
                    f"STOP VERIFY: Item7 RE={item.pk} {field} bukan 0."
                )

    print("Item 7 qualitative + Nilai Dampak Q1-Q4: PASS")
    return refreshed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help=(
            "Path workbook resmi. Wajib untuk --apply; SHA256 harus sama "
            "dengan source yang direview."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit perubahan. Default adalah DRY RUN / rollback.",
    )
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY RUN"
    banner("REPAIR PROFIL RISIKO SETPER 2026 - JULI 2026 - V1 SAFE")
    print("Mode     :", mode)
    print("Settings :", os.environ.get("DJANGO_SETTINGS_MODULE"))

    verify_source(args.source, required=args.apply)

    profile = resolve_profile()
    mapping = resolve_mapping(profile)

    before = completeness(profile.pk)
    show_completeness("COMPLETENESS BEFORE", before)

    qualitative_category = resolve_qualitative_category()
    kri_changes = plan_kri_updates(mapping)
    risk7_changes = plan_risk7_updates(mapping, qualitative_category)

    print("\nPlanned KRI row updates :", len(kri_changes))
    print("Planned Item7 updates   :", len(risk7_changes))

    backup = None
    if args.apply:
        backup = sqlite_backup()
        banner("DATABASE BACKUP")
        print("Backup:", backup)
        print("quick_check: PASS")

    with transaction.atomic():
        if args.apply:
            # Lock profile + target rows before writing.
            ReAssessmentSummary.objects.select_for_update().get(pk=profile.pk)
            target_ids = sorted(
                {pk for pk, _, _ in kri_changes}
                | {pk for pk, _ in risk7_changes}
            )
            if target_ids:
                list(
                    ReAssessmentItem.objects
                    .select_for_update()
                    .filter(pk__in=target_ids)
                    .values_list("pk", flat=True)
                )

        apply_updates(kri_changes, risk7_changes)

        verify_targets(profile, mapping)

        after = completeness(profile.pk)
        show_completeness("COMPLETENESS AFTER (IN TRANSACTION)", after)

        # The user's reviewed baseline has 25 incomplete components.
        # We do NOT hard-code 718/718 because correct qualitative handling may
        # legitimately change the denominator. Require only that all errors are gone.
        remaining_errors = int(getattr(after, "error_count", 0) or 0)
        remaining_incomplete = int(getattr(after, "incomplete_count", 0) or 0)

        if remaining_errors or remaining_incomplete:
            print(
                "\nNOTE: target repair berhasil, tetapi profile completeness "
                "masih memiliki temuan lain."
            )
            print(
                "DRY RUN akan tetap rollback. Jangan APPLY sampai output "
                "remaining findings direview."
            )
            if args.apply:
                raise RuntimeError(
                    "STOP: --apply dibatalkan karena completeness belum 100%."
                )

        if not args.apply:
            transaction.set_rollback(True)

    banner("RESULT")
    if args.apply:
        print("APPLY BERHASIL.")
        print("Database changes committed.")
        print("Backup:", backup)
    else:
        print("DRY RUN BERHASIL.")
        print("Database TIDAK berubah — transaction rollback.")
        print("Review COMPLETENESS AFTER di atas.")
        print("Jika 100% / tanpa error, jalankan ulang dengan --apply.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
