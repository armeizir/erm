#!/usr/bin/env python3
"""
FINAL REPAIR PROFIL RISIKO SETPER 2026 - V2 SAFE

Berdasarkan audit production:
- Profil Risiko SETPER 2026 = ReAssessmentSummary id=13.
- Total active ReAssessmentItem = 23.
- Konfigurasi KRI utama (nama/unit/threshold) sudah terisi.
- Kekurangan KRI berasal dari kri_threshold_direction pada sebagian cause-row.
- Item 7 di source resmi adalah KUALITATIF, tetapi production masih tersimpan
  sebagai kuantitatif / Dampak Kuantitatif.
- Nilai Dampak residual Item 7 Q1-Q4 pada source resmi = 0.

Scope perubahan HANYA:
1) Isi kri_threshold_direction yang kosong untuk Item 1..8.
2) Ubah Item 7 menjadi jenis_risiko='kualitatif' dan kategori_dampak=master Kualitatif.
3) Biarkan nilai_dampak inheren Item 7 tetap NULL/kosong.
4) Isi nilai_dampak_q1..q4 Item 7 = 0 hanya bila masih NULL.

TIDAK mengubah:
- Nama KRI.
- Satuan KRI.
- Threshold aman/hati-hati/bahaya.
- Nilai dampak inheren.
- Probabilitas/skala/eksposur.
- KM/RKM.
- Monthly Report/Reassessment history lain.
- Cause/event/treatment/control/PIC/timeline.

Safety:
- Default DRY RUN + rollback.
- --apply wajib menyertakan --source workbook resmi dan SHA256 harus match.
- Stop jika profil/unit/year/event/row-count tidak sesuai baseline audit.
- Stop jika kri_threshold_direction existing bertentangan dengan expected direction.
- Stop jika Item 7 punya nilai dampak residual nonzero.
- SQLite backup + PRAGMA quick_check sebelum APPLY.
- QuerySet.update() agar tidak memicu save()/recalculation side effect.
- Completeness dihitung ulang sebelum/selesai.
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

PROFILE_ID = 13
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

EXPECTED_EVENTS = {
    1: "Kendala Pemenuhan Parameter Sustainability (Enviromental, Social Governance) ESG Risk Rating",
    2: "Penerapan Good Corporate Governance (GCG) belum berjalan efektif dan berkelanjutan sehingga maturity level GCG tidak meningkat atau menurun.",
    3: "Tidak akurat dalam penerbitan pendapat hukum",
    4: "Terjadinya dispute antara Para Pihak di dalam Perjanjian",
    5: "Distorsi informasi publik atau komunikasi krisis yang tidak tertangani secara cepat dan tepat.",
    6: "Realisasi Biaya administrasi tidak sesuai rencana bayar yang disampaikan",
    7: "Munculnya risiko baru diluar profil risiko yang telah dicapture",
    8: "Tidak optimalnya implementasi Sistem Manajemen Terintegrasi",
}

EXPECTED_DIRECTIONS = {
    1: "higher_better",
    2: "higher_better",
    3: "lower_better",
    4: "higher_better",
    5: "lower_better",
    6: "lower_better",
    7: "lower_better",
    8: "higher_better",
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


def norm(value) -> str:
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = value.casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


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
            raise RuntimeError("STOP: --apply wajib menyertakan --source workbook resmi.")
        print("Source file     : tidak diberikan")
        print("DRY RUN         : diizinkan tanpa source file")
        return

    path = path.expanduser().resolve()
    if not path.is_file():
        raise RuntimeError(f"STOP: source workbook tidak ditemukan: {path}")

    actual = sha256_file(path)
    print("Source file     :", path)
    print("Actual SHA256   :", actual)

    if actual != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("STOP: SHA256 source berbeda dari workbook yang sudah direview.")

    print("SOURCE SHA256   : PASS")


def field_exists(model, name: str) -> bool:
    try:
        model._meta.get_field(name)
        return True
    except Exception:
        return False


def active_items(profile):
    qs = ReAssessmentItem.objects.filter(summary=profile)
    if field_exists(ReAssessmentItem, "is_active"):
        qs = qs.filter(is_active=True)
    return qs


def get_profile():
    try:
        p = (
            ReAssessmentSummary.objects
            .select_related("unit_bisnis", "kontrak_manajemen", "rkm")
            .get(pk=PROFILE_ID)
        )
    except ReAssessmentSummary.DoesNotExist:
        raise RuntimeError(f"STOP: profile id={PROFILE_ID} tidak ditemukan.")

    unit = str(getattr(getattr(p, "unit_bisnis", None), "name", "") or "")
    if p.tahun != YEAR:
        raise RuntimeError(f"STOP: profile id={p.pk} tahun={p.tahun}, expected={YEAR}.")
    if "setper" not in norm(unit) and "sekper" not in norm(unit):
        raise RuntimeError(f"STOP: profile id={p.pk} unit={unit!r}, bukan SETPER/SEKPER.")

    return p


def build_mapping(profile):
    rows = list(active_items(profile).order_by("no_item", "no_risiko", "pk"))

    banner("PROFILE / ITEM PREFLIGHT")
    print(
        f"Profile : id={profile.pk} | {profile.judul!r} | tahun={profile.tahun} "
        f"| unit={profile.unit_bisnis!r} | KM={profile.kontrak_manajemen_id} "
        f"| RKM={getattr(profile, 'rkm_id', None)}"
    )
    print("Active rows:", len(rows))

    if len(rows) != 23:
        raise RuntimeError(f"STOP: active rows={len(rows)}, expected=23.")

    mapping = {}
    for no_item in range(1, 9):
        group = [x for x in rows if int(x.no_item or 0) == no_item]
        expected_count = EXPECTED_ROW_COUNTS[no_item]

        if len(group) != expected_count:
            raise RuntimeError(
                f"STOP: Item {no_item} row count={len(group)}, expected={expected_count}."
            )

        for x in group:
            if norm(x.peristiwa_risiko) != norm(EXPECTED_EVENTS[no_item]):
                raise RuntimeError(
                    f"STOP: Item {no_item} RE={x.pk} event berbeda.\n"
                    f"DB ={x.peristiwa_risiko!r}\n"
                    f"EXP={EXPECTED_EVENTS[no_item]!r}"
                )

        mapping[no_item] = group
        print(
            f"Item {no_item}: rows={len(group)} | "
            f"RE={','.join(str(x.pk) for x in group)} | "
            f"DIR={EXPECTED_DIRECTIONS[no_item]}"
        )

    return mapping


def get_qualitative_category():
    """
    Production master audit 2026-08-28:
      ID=1 -> Dampak Kuantitatif
      ID=2 -> Dampak Kualilatif

    ID=2 contains a legacy typo ("Kualilatif"), but is the active
    qualitative impact master. Do not create or rename master data here.
    """
    try:
        obj = MasterKategoriDampak.objects.get(pk=2)
    except MasterKategoriDampak.DoesNotExist:
        raise RuntimeError(
            "STOP: MasterKategoriDampak id=2 tidak ditemukan."
        )

    if not getattr(obj, "aktif", False):
        raise RuntimeError(
            "STOP: MasterKategoriDampak id=2 tidak aktif."
        )

    name = norm(str(obj))

    accepted = (
        "kualitatif" in name
        or "kualilatif" in name
    )

    if not accepted:
        raise RuntimeError(
            "STOP: MasterKategoriDampak id=2 tidak dikenali sebagai "
            f"kualitatif: {obj!r}"
        )

    print(
        f"Qualitative master: id={obj.pk} | {obj} "
        "(legacy typo accepted)"
    )

    return obj


def completeness(profile_id):
    p = profile_completeness_queryset().get(pk=profile_id)
    return check_profile_completeness(p)


def finding_text(finding) -> str:
    label = (
        getattr(finding, "item_label", None)
        or getattr(finding, "label", None)
        or ""
    )
    section = getattr(finding, "section", None) or ""
    message = getattr(finding, "message", None) or str(finding)
    return f"{section} | {label} | {message}".strip(" |")


def show_completeness(label, result):
    banner(label)
    print("Required   :", getattr(result, "required_count", "?"))
    print("Completed  :", getattr(result, "completed_count", "?"))
    print("Incomplete :", getattr(result, "incomplete_count", "?"))
    print("Percentage :", getattr(result, "percentage", "?"))
    print("Status     :", getattr(result, "status_label", "?"))
    print("Errors     :", getattr(result, "error_count", "?"))
    print("Warnings   :", getattr(result, "warning_count", "?"))

    findings = list(getattr(result, "findings", []) or [])
    print("Findings   :", len(findings))
    for f in findings:
        print(" -", finding_text(f))


def sqlite_backup() -> Path:
    db = settings.DATABASES["default"]
    engine = str(db.get("ENGINE", ""))

    if "sqlite3" not in engine:
        raise RuntimeError(
            "STOP: automated backup V2 hanya mendukung SQLite. "
            f"ENGINE={engine!r}"
        )

    src_path = Path(db["NAME"]).expanduser().resolve()
    if not src_path.is_file():
        raise RuntimeError(f"STOP: DB SQLite tidak ditemukan: {src_path}")

    backup_dir = ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst_path = backup_dir / f"db_before_setper_completeness_v2_{stamp}.sqlite3"

    with sqlite3.connect(str(src_path), timeout=30) as src:
        check = src.execute("PRAGMA quick_check").fetchone()
        if not check or str(check[0]).lower() != "ok":
            raise RuntimeError(f"STOP: source DB quick_check gagal: {check}")

        with sqlite3.connect(str(dst_path), timeout=30) as dst:
            src.backup(dst)
            dst.commit()

    with sqlite3.connect(str(dst_path), timeout=30) as verify:
        check = verify.execute("PRAGMA quick_check").fetchone()
        if not check or str(check[0]).lower() != "ok":
            raise RuntimeError(f"STOP: backup DB quick_check gagal: {check}")

    return dst_path


def plan_direction_updates(mapping):
    banner("KRI DIRECTION PLAN")
    changes = []
    blank_count = 0

    for no_item, rows in mapping.items():
        expected = EXPECTED_DIRECTIONS[no_item]
        for item in rows:
            current = getattr(item, "kri_threshold_direction", None)
            if is_blank(current):
                blank_count += 1
                changes.append((item.pk, {"kri_threshold_direction": expected}))
                print(f"RE={item.pk:<4} | Item={no_item} | {current!r} -> {expected!r}")
            elif str(current).strip() != expected:
                raise RuntimeError(
                    f"STOP: KRI direction conflict Item {no_item} RE={item.pk}: "
                    f"DB={current!r}, expected={expected!r}"
                )
            else:
                print(f"RE={item.pk:<4} | Item={no_item} | already {expected!r}")

    print("\nBlank direction rows :", blank_count)
    print("Planned updates      :", len(changes))

    # User's completeness report showed 15 incomplete KRI rows.
    if blank_count != 15:
        raise RuntimeError(
            f"STOP: expected 15 blank kri_threshold_direction rows, found {blank_count}. "
            "Audit ulang sebelum APPLY."
        )

    return changes


def plan_item7_updates(mapping, qualitative):
    banner("ITEM 7 QUALITATIVE + RESIDUAL IMPACT PLAN")
    changes = []

    for item in mapping[7]:
        updates = {}

        current_kind = getattr(item, "jenis_risiko", None)
        if current_kind == "kualitatif":
            pass
        elif current_kind in (None, "", "kuantitatif"):
            updates["jenis_risiko"] = "kualitatif"
        else:
            raise RuntimeError(
                f"STOP: RE={item.pk} jenis_risiko={current_kind!r} tidak dikenali."
            )

        current_cat_id = getattr(item, "kategori_dampak_id", None)
        if current_cat_id != qualitative.pk:
            current_cat = getattr(item, "kategori_dampak", None)
            # We allow conversion from the audited current state:
            # Dampak Kuantitatif -> Dampak Kualitatif.
            if current_cat is None or "kuantitatif" in norm(str(current_cat)):
                updates["kategori_dampak_id"] = qualitative.pk
            else:
                raise RuntimeError(
                    f"STOP: RE={item.pk} kategori_dampak={current_cat!r} "
                    "bukan state yang aman untuk dikonversi."
                )

        # Important: inherent nilai_dampak must remain empty for this qualitative risk.
        if item.nilai_dampak is not None:
            raise RuntimeError(
                f"STOP: RE={item.pk} nilai_dampak inheren={item.nilai_dampak!r}. "
                "V2 tidak akan menghapus nilai existing."
            )

        for field, expected in RISK7_Q_IMPACT.items():
            current = getattr(item, field)
            if current is None:
                updates[field] = expected
            elif Decimal(str(current)) != expected:
                raise RuntimeError(
                    f"STOP: RE={item.pk} {field}={current!r}; expected source=0."
                )

        if updates:
            changes.append((item.pk, updates))
            print(
                f"RE={item.pk}: "
                + ", ".join(f"{k}={v!r}" for k, v in updates.items())
            )
        else:
            print(f"RE={item.pk}: already aligned")

    return changes


def apply_changes(direction_changes, item7_changes):
    for pk, updates in direction_changes:
        count = ReAssessmentItem.objects.filter(pk=pk).update(**updates)
        if count != 1:
            raise RuntimeError(f"STOP: update direction RE={pk} affected rows={count}")

    for pk, updates in item7_changes:
        count = ReAssessmentItem.objects.filter(pk=pk).update(**updates)
        if count != 1:
            raise RuntimeError(f"STOP: update Item7 RE={pk} affected rows={count}")


def verify_after(profile, qualitative):
    mapping = build_mapping(profile)

    banner("TARGET VERIFICATION")

    for no_item, rows in mapping.items():
        expected_dir = EXPECTED_DIRECTIONS[no_item]
        for item in rows:
            if item.kri_threshold_direction != expected_dir:
                raise RuntimeError(
                    f"STOP VERIFY: Item {no_item} RE={item.pk} direction "
                    f"{item.kri_threshold_direction!r} != {expected_dir!r}"
                )
        print(f"KRI direction Item {no_item}: PASS ({len(rows)} rows)")

    for item in mapping[7]:
        if item.jenis_risiko != "kualitatif":
            raise RuntimeError(
                f"STOP VERIFY: Item7 RE={item.pk} jenis_risiko={item.jenis_risiko!r}"
            )
        if item.kategori_dampak_id != qualitative.pk:
            raise RuntimeError(
                f"STOP VERIFY: Item7 RE={item.pk} kategori_dampak_id="
                f"{item.kategori_dampak_id}, expected={qualitative.pk}"
            )
        if item.nilai_dampak is not None:
            raise RuntimeError(
                f"STOP VERIFY: Item7 RE={item.pk} nilai_dampak harus tetap NULL."
            )
        for field in RISK7_Q_IMPACT:
            if Decimal(str(getattr(item, field))) != Decimal("0"):
                raise RuntimeError(
                    f"STOP VERIFY: Item7 RE={item.pk} {field} bukan 0."
                )

    print("Item 7 qualitative classification: PASS")
    print("Item 7 inherent numeric impact remains NULL: PASS")
    print("Item 7 residual impact Q1-Q4 = 0: PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY RUN"
    banner("FINAL REPAIR PROFIL RISIKO SETPER 2026 - V2 SAFE")
    print("Mode     :", mode)
    print("Settings :", os.environ.get("DJANGO_SETTINGS_MODULE"))

    verify_source(args.source, required=args.apply)

    profile = get_profile()
    mapping = build_mapping(profile)
    qualitative = get_qualitative_category()

    before = completeness(profile.pk)
    show_completeness("COMPLETENESS BEFORE", before)

    direction_changes = plan_direction_updates(mapping)
    item7_changes = plan_item7_updates(mapping, qualitative)

    print("\nDirection updates planned :", len(direction_changes))
    print("Item 7 updates planned     :", len(item7_changes))

    backup = None
    if args.apply:
        backup = sqlite_backup()
        banner("DATABASE BACKUP")
        print("Backup      :", backup)
        print("quick_check : PASS")

    with transaction.atomic():
        if args.apply:
            ReAssessmentSummary.objects.select_for_update().get(pk=profile.pk)
            ids = sorted(
                {pk for pk, _ in direction_changes}
                | {pk for pk, _ in item7_changes}
            )
            if ids:
                list(
                    ReAssessmentItem.objects
                    .select_for_update()
                    .filter(pk__in=ids)
                    .values_list("pk", flat=True)
                )

        apply_changes(direction_changes, item7_changes)
        verify_after(profile, qualitative)

        after = completeness(profile.pk)
        show_completeness("COMPLETENESS AFTER (IN TRANSACTION)", after)

        incomplete = int(getattr(after, "incomplete_count", 0) or 0)
        errors = int(getattr(after, "error_count", 0) or 0)

        if args.apply and (incomplete or errors):
            raise RuntimeError(
                f"STOP: APPLY dibatalkan karena completeness masih incomplete={incomplete}, "
                f"errors={errors}."
            )

        if not args.apply:
            transaction.set_rollback(True)

    banner("RESULT")
    if args.apply:
        print("APPLY BERHASIL.")
        print("Database committed.")
        print("Backup:", backup)
    else:
        print("DRY RUN BERHASIL.")
        print("Database TIDAK berubah — transaction rollback.")
        print("Review COMPLETENESS AFTER sebelum menjalankan --apply.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
