from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from openpyxl import load_workbook

from corporate_risk.models import (
    MonteCarloForecastAssumption,
    MonteCarloMetricHistory,
    RiskMetric,
)
from masterdata.models import PeriodeLaporan
from risk.models import ProfilRisikoKorporatItem


SHEET = "Gangguan MPP Pend."
YEAR_DEFAULT = 2026
RISK_NO_DEFAULT = 8

# Workbook:
# D:O = Jan:Dec
# row 39 = monthly actual revenue in Rp
# row 47 = RKAP monthly reference in Rp billion
# P47 = full-year RKAP in Rp billion
ACTUAL_ROW = 39
RKAP_ROW = 47
TARGET_KM_ROW = 46
MONTH_COLS = {
    1: "D", 2: "E", 3: "F", 4: "G",
    5: "H", 6: "I", 7: "J", 8: "K",
    9: "L", 10: "M", 11: "N", 12: "O",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def dec(v, label):
    if v in (None, ""):
        raise CommandError(f"STOP: workbook cell kosong untuk {label}")
    return Decimal(str(v))


def rupiah(value: Decimal) -> Decimal:
    """Normalize Excel floating-point artifacts to whole Rupiah."""
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


class Command(BaseCommand):
    help = (
        "Risk #8 MPP V4.5.1 — import actual Jan-Aug + RKAP target only. "
        "No Monte Carlo assumptions are created. Default is DRY RUN."
    )

    def add_arguments(self, parser):
        parser.add_argument("xlsx")
        parser.add_argument("--year", type=int, default=YEAR_DEFAULT)
        parser.add_argument("--risk-no", type=int, default=RISK_NO_DEFAULT)
        parser.add_argument("--sync-history", action="store_true")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **opts):
        source = Path(opts["xlsx"]).expanduser().resolve()
        if not source.exists():
            raise CommandError(f"Workbook tidak ditemukan: {source}")

        year = opts["year"]
        risk_no = opts["risk_no"]
        sync_history = bool(opts["sync_history"])
        do_apply = bool(opts["apply"])
        source_hash = sha256(source)

        wb = load_workbook(source, data_only=True, read_only=True)
        if SHEET not in wb.sheetnames:
            raise CommandError(f"Sheet '{SHEET}' tidak ditemukan.")
        ws = wb[SHEET]

        # Actual Jan-Aug only. Sep-Dec are intentionally not treated as forecast.
        actual = {}
        for month in range(1, 9):
            col = MONTH_COLS[month]
            actual[month] = dec(ws[f"{col}{ACTUAL_ROW}"].value, f"actual {year}-{month:02}")

        # Explicitly audit that actual Sep-Dec are blank.
        future_actual = {}
        for month in range(9, 13):
            col = MONTH_COLS[month]
            future_actual[month] = ws[f"{col}{ACTUAL_ROW}"].value

        # Full-year totals: prefer explicit P total if present, otherwise
        # compute from the authoritative Jan-Dec monthly row.
        rkap_p = ws["P47"].value
        if rkap_p in (None, ""):
            rkap_billion = sum(
                dec(ws[f"{MONTH_COLS[m]}{RKAP_ROW}"].value, f"RKAP {year}-{m:02}")
                for m in range(1, 13)
            )
        else:
            rkap_billion = dec(rkap_p, "RKAP full year P47")
        target_rkap = rupiah(rkap_billion * Decimal("1000000000"))

        target_km_p = ws["P46"].value
        if target_km_p in (None, ""):
            target_km_billion = sum(
                dec(ws[f"{MONTH_COLS[m]}{TARGET_KM_ROW}"].value, f"Target KM {year}-{m:02}")
                for m in range(1, 13)
            )
        else:
            target_km_billion = dec(target_km_p, "Target KM full year P46")
        target_km = rupiah(target_km_billion * Decimal("1000000000"))

        risk = (
            ProfilRisikoKorporatItem.objects
            .filter(summary__tahun=year, no_risiko=risk_no)
            .first()
        )
        if not risk:
            raise CommandError(f"Risk #{risk_no} tahun {year} tidak ditemukan.")

        metric = (
            RiskMetric.objects
            .filter(
                corporate_risk_item=risk,
                name="Realisasi Pendapatan MPP",
            )
            .first()
        )
        if not metric:
            raise CommandError("Metric 'Realisasi Pendapatan MPP' tidak ditemukan.")

        print("=" * 146)
        print(
            f"MPP ACTUAL + TARGET IMPORT V4.5.3 — "
            f"{'APPLY LOCAL' if do_apply else 'DRY RUN'}"
        )
        print("=" * 146)
        print(f"SOURCE       : {source}")
        print(f"SHA256       : {source_hash}")
        print(f"SYNC HISTORY : {'ENABLED' if sync_history else 'DISABLED'}")
        print(f"RISK         : #{risk.no_risiko} ID={risk.id} | {risk.peristiwa_risiko}")
        print(
            f"METRIC       : ID={metric.id} | {metric.name} | "
            f"DIR={metric.direction} | AGG={metric.aggregation_type}"
        )
        print(f"DB TARGET    : Rp {Decimal(str(metric.effective_target_value)):,.2f}")
        print(f"WB RKAP      : Rp {target_rkap:,.2f}")
        print(f"WB TARGET KM : Rp {target_km:,.2f} | REFERENCE ONLY")
        print(f"ACTUAL YTD   : Rp {sum(actual.values()):,.2f}")
        print("MC POLICY    : ACTUAL + TARGET ONLY; NO FORECAST ASSUMPTION; NO CB BADGE")
        print()

        db_target_normalized = rupiah(Decimal(str(metric.effective_target_value)))
        if db_target_normalized != target_rkap:
            print(
                f"TARGET REVIEW: ERM={db_target_normalized} "
                f"vs WB RKAP={target_rkap}"
            )
        else:
            print("TARGET CHECK : PASS — ERM target matches workbook RKAP at Rupiah precision.")

        populated_future = {
            m: v for m, v in future_actual.items()
            if v not in (None, "")
        }
        if populated_future:
            raise CommandError(
                f"STOP: row {ACTUAL_ROW} Sep-Dec unexpectedly populated: {populated_future}"
            )
        print("SEP-DEC ACTUAL: BLANK as expected; not treated as forecast.")

        active_assumptions = MonteCarloForecastAssumption.objects.filter(
            metric=metric,
            forecast_date__year=year,
            is_active=True,
        ).count()
        print(f"ACTIVE MC ASSUMPTIONS BEFORE IMPORT: {active_assumptions}")
        if active_assumptions:
            print(
                "REVIEW: active MC assumptions already exist. "
                "Importer will NOT delete or modify them automatically."
            )

        print()
        print("HISTORY RECONCILIATION")
        print("-" * 146)

        mismatches = []
        missing = []
        matches = []

        for month, wb_value in actual.items():
            h = (
                MonteCarloMetricHistory.objects
                .filter(
                    metric=metric,
                    tanggal_data__year=year,
                    tanggal_data__month=month,
                )
                .order_by("-id")
                .first()
            )
            if h is None:
                missing.append((month, wb_value))
                print(f"MISSING  {year}-{month:02} | WORKBOOK={wb_value}")
                continue

            db_value = Decimal(str(h.metric_value))
            if abs(db_value - wb_value) > Decimal("0.01"):
                mismatches.append((month, db_value, wb_value))
                print(
                    f"MISMATCH {year}-{month:02} | "
                    f"DB={db_value} | WORKBOOK={wb_value}"
                )
            else:
                matches.append((month, wb_value))
                print(f"MATCH    {year}-{month:02} | {wb_value}")

        if mismatches and not sync_history:
            raise CommandError(
                "STOP: histori existing berbeda dengan workbook. "
                "Tidak ada write. Review lalu ulangi dengan --sync-history."
            )

        if sync_history:
            print()
            print("SYNC PLAN")
            print("-" * 146)
            for month, old, new in mismatches:
                print(f"UPDATE {year}-{month:02}: {old} -> {new}")
            for month, new in missing:
                print(f"INSERT {year}-{month:02}: {new}")
            if not mismatches and not missing:
                print("NO HISTORY CHANGE REQUIRED.")

        if not do_apply:
            print()
            print("DRY RUN PASS — database belum diubah.")
            print(
                "NEXT: backup DB; if sync plan is correct run with "
                "--sync-history --apply."
            )
            return

        if mismatches and not sync_history:
            raise CommandError("STOP: mismatch membutuhkan --sync-history.")

        with transaction.atomic():
            # Preserve the official ERM/RKAP semantics.
            metric.unit = "Rp"
            metric.direction = RiskMetric.DIRECTION_DECREASE
            metric.aggregation_type = RiskMetric.AGGREGATION_SUM
            metric.target_value = target_rkap
            metric.is_target_metric = True
            metric.is_active = True
            metric.save()

            for month, value in actual.items():
                data_date = date(year, month, 1)
                period = (
                    PeriodeLaporan.objects
                    .filter(
                        tahun_buku__tahun=year,
                        jenis_periode="bulanan",
                        tanggal_mulai__lte=data_date,
                        tanggal_selesai__gte=data_date,
                    )
                    .first()
                )
                if not period:
                    raise CommandError(f"Periode {year}-{month:02} tidak ditemukan.")

                h = (
                    MonteCarloMetricHistory.objects
                    .filter(metric=metric, periode=period)
                    .order_by("-id")
                    .first()
                )

                note = (
                    f"MPP actual snapshot {source.name}; SHA256={source_hash}; "
                    f"source={SHEET}!{MONTH_COLS[month]}{ACTUAL_ROW}; "
                    f"RKAP target={target_rkap}; Target KM reference={target_km}; "
                    "V4.5.3 actual+target only; no Crystal Ball validation."
                )

                if h is None:
                    MonteCarloMetricHistory.objects.create(
                        metric=metric,
                        periode=period,
                        tanggal_data=data_date,
                        metric_value=value,
                        target_value=target_rkap,
                        status=MonteCarloMetricHistory.STATUS_VERIFIED,
                        keterangan=note,
                    )
                else:
                    old = Decimal(str(h.metric_value))
                    if abs(old - value) > Decimal("0.01") and not sync_history:
                        raise CommandError(
                            f"STOP: mismatch {year}-{month:02} requires --sync-history."
                        )
                    h.metric_value = value
                    h.target_value = target_rkap
                    h.status = MonteCarloMetricHistory.STATUS_VERIFIED
                    h.keterangan = note
                    h.save()

        print()
        print("APPLY PASS")
        print(f"ACTUAL JAN-AUG : Rp {sum(actual.values()):,.2f}")
        print(f"TARGET RKAP    : Rp {target_rkap:,.2f}")
        print(f"TARGET KM REF  : Rp {target_km:,.2f}")
        print("MC ASSUMPTIONS : NOT CREATED")
        print("CB VALIDATION  : NOT APPLICABLE")
        print("EXECUTIVE USE  : history/current/YTD/target only; no imported MC outlook.")


if __name__ == "__main__":
    pass
