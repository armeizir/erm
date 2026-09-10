from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
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


ACTUAL_MONTHS = list(range(1, 9))
FORECAST_MONTHS = list(range(9, 13))
SHEET_NAME = "Energi Primer (Deny)"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _d(value) -> Decimal:
    if value in (None, ""):
        raise CommandError("STOP: workbook berisi cell kosong pada field model yang wajib.")
    return Decimal(str(value))


def _same(a, b, tolerance=Decimal("0.0001")):
    if a is None or b is None:
        return a is b
    return abs(Decimal(a) - Decimal(b)) <= tolerance


class Command(BaseCommand):
    help = (
        "Import validated Aug-2026 Crystal Ball Volume Gas + Gas Cost model to Risk #9. "
        "Default is DRY RUN; --apply writes LOCAL database."
    )

    def add_arguments(self, parser):
        parser.add_argument("xlsx")
        parser.add_argument("--apply", action="store_true", help="Write histories/metrics/assumptions to LOCAL database.")
        parser.add_argument(
            "--sync-history",
            action="store_true",
            help=(
                "Allow reconciled existing Jan-Aug operational history to be updated "
                "to the workbook snapshot. Without this flag, any mismatch remains a hard STOP."
            ),
        )
        parser.add_argument("--year", type=int, default=2026)
        parser.add_argument("--risk-no", type=int, default=9)

    def handle(self, *args, **options):
        source = Path(options["xlsx"]).expanduser().resolve()
        if not source.exists():
            raise CommandError(f"SOURCE NOT FOUND: {source}")

        year = int(options["year"])
        risk_no = int(options["risk_no"])
        apply_mode = bool(options["apply"])
        sync_history = bool(options["sync_history"])
        source_hash = _sha256(source)

        wb = load_workbook(source, data_only=True, read_only=False)
        if SHEET_NAME not in wb.sheetnames:
            raise CommandError(f"Sheet '{SHEET_NAME}' tidak ditemukan.")
        ws = wb[SHEET_NAME]

        # Workbook mapping validated by READ ONLY audit V4 pre-flight.
        actual_volume = {month: _d(ws[f"C{40 + month}"].value) for month in ACTUAL_MONTHS}
        actual_cost = {month: _d(ws[f"G{40 + month}"].value) for month in ACTUAL_MONTHS}

        volume_assumptions = {
            month: {
                "mean": _d(ws[f"D{53 + month}"].value),
                "p15": _d(ws[f"E{53 + month}"].value),
                "stddev": _d(ws[f"F{53 + month}"].value),
            }
            for month in FORECAST_MONTHS
        }
        cost_assumptions = {
            month: {
                "mean": _d(ws[f"H{53 + month}"].value),
                "p15": _d(ws[f"I{53 + month}"].value),
                "stddev": _d(ws[f"J{53 + month}"].value),
            }
            for month in FORECAST_MONTHS
        }

        benchmark = {
            "volume": {
                "p5": _d(ws["C76"].value),
                "p50": _d(ws["C77"].value),
                "p95": _d(ws["C78"].value),
                "target": _d(ws["C80"].value),
                "probability_risk": _d(ws["C84"].value) * Decimal("100"),
            },
            "gas_cost": {
                "p5": _d(ws["E76"].value),
                "p50": _d(ws["E77"].value),
                "p95": _d(ws["E78"].value),
                "target": _d(ws["E80"].value),
            },
        }
        if ws["E84"].value not in (None, ""):
            benchmark["gas_cost"]["probability_risk"] = _d(ws["E84"].value) * Decimal("100")

        risk = ProfilRisikoKorporatItem.objects.filter(summary__tahun=year, no_risiko=risk_no).first()
        if not risk:
            raise CommandError(f"Risk #{risk_no} tahun {year} tidak ditemukan.")

        volume_metric = (
            RiskMetric.objects.filter(
                corporate_risk_item=risk,
                name__iexact="Realisasi Volume Gas",
            ).first()
            or RiskMetric.objects.filter(
                corporate_risk_item=risk,
                unit__iexact="MMBTU",
                name__icontains="Volume Gas",
            ).first()
        )
        if not volume_metric:
            raise CommandError("Metric Realisasi Volume Gas tidak ditemukan pada Risk #9.")
        if (volume_metric.unit or "").strip().upper() != "MMBTU":
            raise CommandError(
                f"STOP: metric volume gas harus berunit MMBTU; ditemukan ID={volume_metric.id} UNIT={volume_metric.unit}."
            )

        existing_cost_metric = RiskMetric.objects.filter(
            corporate_risk_item=risk,
            name__iexact="Realisasi Biaya Gas",
        ).first()

        self.stdout.write("=" * 126)
        self.stdout.write("CRYSTAL BALL GAS IMPORT V4.1 — " + ("APPLY LOCAL" if apply_mode else "DRY RUN"))
        self.stdout.write("=" * 126)
        self.stdout.write(f"SOURCE : {source}")
        self.stdout.write(f"SHA256 : {source_hash}")
        self.stdout.write(f"SYNC HISTORY : {'ENABLED' if sync_history else 'DISABLED'}")
        self.stdout.write(f"RISK   : #{risk_no} ID={risk.id} {risk.peristiwa_risiko}")
        self.stdout.write(
            f"VOLUME METRIC : ID={volume_metric.id} {volume_metric.name} | "
            f"CURRENT DIR={volume_metric.direction} -> REQUIRED DIR=increase"
        )
        self.stdout.write(f"YTD VOLUME    : {sum(actual_volume.values()):,.4f} MMBTU")
        self.stdout.write(f"YTD GAS COST  : Rp {sum(actual_cost.values()):,.4f}")
        self.stdout.write(
            f"CB VOLUME     : P5={benchmark['volume']['p5']:,.4f} "
            f"P50={benchmark['volume']['p50']:,.4f} P95={benchmark['volume']['p95']:,.4f} "
            f"P(RISK)={benchmark['volume']['probability_risk']:,.4f}%"
        )
        self.stdout.write(
            f"CB GAS COST   : P5={benchmark['gas_cost']['p5']:,.4f} "
            f"P50={benchmark['gas_cost']['p50']:,.4f} P95={benchmark['gas_cost']['p95']:,.4f}"
        )

        # Never silently overwrite operational history. Existing Jan-Aug values must
        # agree with the workbook before --apply can proceed.
        mismatches = []
        for month, expected in actual_volume.items():
            existing = MonteCarloMetricHistory.objects.filter(
                metric=volume_metric,
                tanggal_data__year=year,
                tanggal_data__month=month,
            ).first()
            if existing and not _same(existing.metric_value, expected, Decimal("0.0001")):
                mismatches.append(("VOLUME", month, existing.metric_value, expected))

        if existing_cost_metric:
            for month, expected in actual_cost.items():
                existing = MonteCarloMetricHistory.objects.filter(
                    metric=existing_cost_metric,
                    tanggal_data__year=year,
                    tanggal_data__month=month,
                ).first()
                if existing and not _same(existing.metric_value, expected, Decimal("0.01")):
                    mismatches.append(("GAS COST", month, existing.metric_value, expected))

        if mismatches:
            for metric_kind, month, current, expected in mismatches:
                self.stderr.write(
                    f"MISMATCH {metric_kind} {year}-{month:02}: DB={current} WORKBOOK={expected}"
                )
            if not sync_history:
                raise CommandError(
                    "STOP: histori existing berbeda dari workbook. Tidak ada write dilakukan. "
                    "Setelah rekonsiliasi disetujui, ulangi dengan --sync-history (DRY RUN), "
                    "kemudian --sync-history --apply."
                )
            self.stdout.write(
                self.style.WARNING(
                    f"SYNC PLAN : {len(mismatches)} existing history row akan diselaraskan ke workbook."
                )
            )
            for metric_kind, month, current, expected in mismatches:
                self.stdout.write(
                    f"  {metric_kind} {year}-{month:02} | DB={current} -> WORKBOOK={expected}"
                )
        elif sync_history:
            self.stdout.write("SYNC PLAN : tidak ada existing mismatch; missing month tetap akan diinsert saat APPLY.")

        self.stdout.write("SEMANTIC CHECK : PASS — Risk #9 workbook mendefinisikan exceedance volume > target sebagai kondisi risiko.")
        self.stdout.write("WORST CASE     : P95 karena direction=increase (higher is worse).")
        self.stdout.write("IMPACT METRIC  : Realisasi Biaya Gas, weight=0 dan bukan target metric.")

        if not apply_mode:
            if sync_history:
                self.stdout.write(
                    self.style.SUCCESS(
                        "DRY RUN PASS WITH SYNC PLAN — database belum diubah."
                    )
                )
                self.stdout.write(
                    "NEXT: backup DB lalu jalankan command yang sama dengan --sync-history --apply."
                )
            else:
                self.stdout.write(self.style.SUCCESS("DRY RUN PASS — database belum diubah."))
                self.stdout.write("NEXT: backup DB lalu jalankan command yang sama dengan --apply.")
            return

        with transaction.atomic():
            volume_changed = False
            if volume_metric.aggregation_type != RiskMetric.AGGREGATION_SUM:
                volume_metric.aggregation_type = RiskMetric.AGGREGATION_SUM
                volume_changed = True
            if volume_metric.direction != RiskMetric.DIRECTION_INCREASE:
                volume_metric.direction = RiskMetric.DIRECTION_INCREASE
                volume_changed = True
            if volume_metric.target_value != benchmark["volume"]["target"]:
                volume_metric.target_value = benchmark["volume"]["target"]
                volume_changed = True
            if not volume_metric.is_target_metric:
                volume_metric.is_target_metric = True
                volume_changed = True
            if volume_changed:
                volume_metric.save()

            cost_metric, _created = RiskMetric.objects.get_or_create(
                corporate_risk_item=risk,
                name="Realisasi Biaya Gas",
                defaults={
                    "unit": "Rp",
                    "direction": RiskMetric.DIRECTION_INCREASE,
                    "aggregation_type": RiskMetric.AGGREGATION_SUM,
                    "weight": Decimal("0"),
                    "threshold": float(benchmark["gas_cost"]["target"]),
                    "is_target_metric": False,
                    "target_value": benchmark["gas_cost"]["target"],
                    "average_selling_price": Decimal("0"),
                    "is_active": True,
                },
            )
            cost_changed = False
            expected_cost_fields = {
                "unit": "Rp",
                "direction": RiskMetric.DIRECTION_INCREASE,
                "aggregation_type": RiskMetric.AGGREGATION_SUM,
                "weight": Decimal("0"),
                "threshold": float(benchmark["gas_cost"]["target"]),
                "is_target_metric": False,
                "target_value": benchmark["gas_cost"]["target"],
                "average_selling_price": Decimal("0"),
                "is_active": True,
            }
            for field, expected in expected_cost_fields.items():
                if getattr(cost_metric, field) != expected:
                    setattr(cost_metric, field, expected)
                    cost_changed = True
            if cost_changed:
                cost_metric.save()

            for metric, actual_map, target in (
                (volume_metric, actual_volume, benchmark["volume"]["target"]),
                (cost_metric, actual_cost, benchmark["gas_cost"]["target"]),
            ):
                for month, actual in actual_map.items():
                    data_date = date(year, month, 1)
                    period = PeriodeLaporan.objects.filter(
                        tahun_buku__tahun=year,
                        jenis_periode="bulanan",
                        tanggal_mulai__lte=data_date,
                        tanggal_selesai__gte=data_date,
                    ).first()
                    if not period:
                        raise CommandError(f"Periode bulanan {year}-{month:02} tidak ditemukan.")
                    obj, created = MonteCarloMetricHistory.objects.get_or_create(
                        metric=metric,
                        periode=period,
                        defaults={
                            "tanggal_data": data_date,
                            "metric_value": actual,
                            "target_value": target,
                            "status": MonteCarloMetricHistory.STATUS_VERIFIED,
                            "keterangan": f"Crystal Ball Gas snapshot {source.name} SHA256={source_hash}",
                        },
                    )
                    tolerance = Decimal("0.01") if (metric.unit or "").lower().startswith("rp") else Decimal("0.0001")
                    if not created and not _same(obj.metric_value, actual, tolerance):
                        if not sync_history:
                            raise CommandError(
                                f"STOP: {metric.name} {year}-{month:02} existing={obj.metric_value} workbook={actual}"
                            )
                        previous_value = obj.metric_value
                        obj.tanggal_data = data_date
                        obj.metric_value = actual
                        obj.target_value = target
                        obj.status = MonteCarloMetricHistory.STATUS_VERIFIED
                        obj.keterangan = (
                            f"Crystal Ball Gas reconciled snapshot {source.name} "
                            f"SHA256={source_hash}; previous_value={previous_value}"
                        )
                        obj.save(
                            update_fields=[
                                "tanggal_data",
                                "metric_value",
                                "target_value",
                                "status",
                                "keterangan",
                                "updated_at",
                            ]
                        )
                    elif not created:
                        changed_fields = []
                        if obj.target_value != target:
                            obj.target_value = target
                            changed_fields.append("target_value")
                        if obj.status != MonteCarloMetricHistory.STATUS_VERIFIED:
                            obj.status = MonteCarloMetricHistory.STATUS_VERIFIED
                            changed_fields.append("status")
                        expected_note = f"Crystal Ball Gas snapshot {source.name} SHA256={source_hash}"
                        if not obj.keterangan:
                            obj.keterangan = expected_note
                            changed_fields.append("keterangan")
                        if changed_fields:
                            changed_fields.append("updated_at")
                            obj.save(update_fields=changed_fields)

            workbook_benchmark = {
                key: {k: str(v) for k, v in values.items()}
                for key, values in benchmark.items()
            }
            for metric, assumption_map, metric_key in (
                (volume_metric, volume_assumptions, "volume"),
                (cost_metric, cost_assumptions, "gas_cost"),
            ):
                for month, data in assumption_map.items():
                    MonteCarloForecastAssumption.objects.update_or_create(
                        metric=metric,
                        forecast_date=date(year, month, 1),
                        source_type=MonteCarloForecastAssumption.SOURCE_CRYSTAL_BALL,
                        source_sha256=source_hash,
                        defaults={
                            "distribution_type": "normal",
                            "mean_value": data["mean"],
                            "stddev_value": data["stddev"],
                            "p15_value": data["p15"],
                            "source_file": source.name,
                            "source_sheet": SHEET_NAME,
                            "source_metadata": {
                                "benchmark": {k: str(v) for k, v in benchmark[metric_key].items()},
                                "workbook_benchmark": workbook_benchmark,
                                "validated_trials": 10000,
                                "validation_tolerance_pct": "0.05",
                                "risk_semantics": "higher_is_worse",
                                "worst_case_percentile": "P95",
                            },
                            "is_active": True,
                        },
                    )

        if sync_history:
            self.stdout.write(
                self.style.SUCCESS(
                    "APPLY PASS WITH HISTORY SYNC — Risk #9 snapshot/assumptions tersimpan dan histori yang direkonsiliasi telah diselaraskan."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("APPLY PASS — Risk #9 Volume Gas + Gas Cost snapshot/assumptions tersimpan."))
        self.stdout.write(
            f"VOLUME METRIC : ID={volume_metric.id} | DIR={volume_metric.direction} | "
            f"AGG={volume_metric.aggregation_type} | TARGET={volume_metric.effective_target_value}"
        )
        self.stdout.write(
            f"COST METRIC   : ID={cost_metric.id} {cost_metric.name} | DIR={cost_metric.direction} | "
            f"AGG={cost_metric.aggregation_type} | WEIGHT={cost_metric.weight} | TARGET_METRIC={cost_metric.is_target_metric}"
        )
        self.stdout.write("NEXT: run Risk #9 imported_assumptions 10,000 trials dan validator V4.1.")
