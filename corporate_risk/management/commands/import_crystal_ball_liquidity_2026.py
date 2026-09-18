from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from openpyxl import load_workbook

from corporate_risk.models import MonteCarloMetricHistory, MultiMetricMonteCarloResult, RiskMetric
from masterdata.models import PeriodeLaporan
from risk.models import ProfilRisikoKorporatItem


SHEET = "Risk#1 Pendapatan (Modelling)"
MONTH_ROWS = {month: 53 + month for month in range(1, 9)}


def _d(value):
    if value in (None, ""):
        raise CommandError("STOP: workbook berisi cell kosong pada field model yang wajib.")
    return Decimal(str(value))


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Command(BaseCommand):
    help = "Import the approved Aug-2026 Risk #1 liquidity workbook. Default is DRY RUN."

    def add_arguments(self, parser):
        parser.add_argument("xlsx")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--year", type=int, default=2026)
        parser.add_argument("--risk-no", type=int, default=1)

    def handle(self, *args, **options):
        source = Path(options["xlsx"]).expanduser().resolve()
        if not source.exists():
            raise CommandError(f"SOURCE NOT FOUND: {source}")
        year = int(options["year"])
        risk_no = int(options["risk_no"])
        source_hash = _sha256(source)
        wb = load_workbook(source, data_only=True, read_only=False)
        if SHEET not in wb.sheetnames:
            raise CommandError(f"Sheet '{SHEET}' tidak ditemukan.")
        ws = wb[SHEET]

        actual = {
            "Saldo Piutang": {month: _d(ws[f"C{row}"].value) for month, row in MONTH_ROWS.items()},
            "Pendapatan s.d.": {month: _d(ws[f"D{row}"].value) for month, row in MONTH_ROWS.items()},
            "CoP": {month: _d(ws[f"E{row}"].value) for month, row in MONTH_ROWS.items()},
        }
        targets = {
            "Saldo Piutang": _d(ws["N73"].value),
            "Pendapatan s.d.": _d(ws["O73"].value),
            "CoP": _d(ws["P73"].value),
        }
        scenarios = {
            "Saldo Piutang": {"p5": _d(ws["N69"].value), "p50": _d(ws["N70"].value), "p95": _d(ws["N71"].value)},
            "Pendapatan s.d.": {"p5": _d(ws["O69"].value), "p50": _d(ws["O70"].value), "p95": _d(ws["O71"].value)},
            "CoP": {"p5": _d(ws["P69"].value), "p50": _d(ws["P70"].value), "p95": _d(ws["P71"].value)},
        }
        impact = _d(ws["R76"].value)
        probability = _d(ws["N77"].value) * Decimal("100")

        # Relationship check is the governing logic of this workbook.
        for key in ("p5", "p50", "p95"):
            derived = scenarios["Saldo Piutang"][key] / scenarios["Pendapatan s.d."][key] * Decimal("365")
            if abs(derived - scenarios["CoP"][key]) > Decimal("0.0001"):
                raise CommandError(f"STOP: CoP {key} tidak merekonsiliasi Piutang/Pendapatan x 365.")

        risk = ProfilRisikoKorporatItem.objects.filter(summary__tahun=year, no_risiko=risk_no).first()
        if not risk:
            raise CommandError(f"Risk #{risk_no} tahun {year} tidak ditemukan.")
        metrics = {metric.name: metric for metric in RiskMetric.objects.filter(corporate_risk_item=risk)}
        missing = [name for name in actual if name not in metrics]
        if missing:
            raise CommandError(f"STOP: metric belum tersedia: {', '.join(missing)}")

        self.stdout.write("=" * 120)
        self.stdout.write("CRYSTAL BALL LIQUIDITY IMPORT — " + ("APPLY LOCAL" if options["apply"] else "DRY RUN"))
        self.stdout.write(f"SOURCE : {source}")
        self.stdout.write(f"SHA256 : {source_hash}")
        self.stdout.write(f"RISK   : #{risk_no} ID={risk.id} {risk.peristiwa_risiko}")
        for name in actual:
            values = scenarios[name]
            self.stdout.write(
                f"{name}: AUG={actual[name][8]:,.4f} TARGET={targets[name]:,.4f} "
                f"P5={values['p5']:,.4f} P50={values['p50']:,.4f} P95={values['p95']:,.4f}"
            )
        self.stdout.write(f"IMPACT={impact:,.4f} | P(RISK)={probability:,.2f}%")
        if not options["apply"]:
            self.stdout.write(self.style.SUCCESS("DRY RUN PASS — database belum diubah."))
            return

        period = PeriodeLaporan.objects.filter(
            tahun_buku__tahun=year,
            jenis_periode="bulanan",
            tanggal_mulai__lte=date(year, 8, 31),
            tanggal_selesai__gte=date(year, 8, 1),
        ).order_by("tanggal_mulai").first()
        if not period:
            raise CommandError(f"Periode Agustus {year} tidak ditemukan.")

        with transaction.atomic():
            for name, monthly in actual.items():
                metric = metrics[name]
                desired_direction = RiskMetric.DIRECTION_INCREASE if name in {"Saldo Piutang", "CoP"} else RiskMetric.DIRECTION_DECREASE
                desired_target = targets[name]
                changed = []
                for field, value in {
                    "direction": desired_direction,
                    "target_value": desired_target,
                    "is_target_metric": name == "CoP",
                    "is_active": True,
                }.items():
                    if getattr(metric, field) != value:
                        setattr(metric, field, value)
                        changed.append(field)
                if changed:
                    metric.save(update_fields=changed + ["updated_at"])
                for month, value in monthly.items():
                    data_date = date(year, month, 1)
                    month_period = PeriodeLaporan.objects.filter(
                        tahun_buku__tahun=year,
                        jenis_periode="bulanan",
                        tanggal_mulai__lte=data_date,
                        tanggal_selesai__gte=data_date,
                    ).first()
                    if not month_period:
                        raise CommandError(f"Periode {year}-{month:02} tidak ditemukan.")
                    MonteCarloMetricHistory.objects.update_or_create(
                        metric=metric,
                        periode=month_period,
                        defaults={
                            "tanggal_data": data_date,
                            "metric_value": value,
                            "target_value": desired_target,
                            "status": MonteCarloMetricHistory.STATUS_VERIFIED,
                            "keterangan": f"Liquidity snapshot {source.name} SHA256={source_hash}",
                        },
                    )

            rows = []
            for name, metric in metrics.items():
                if name not in scenarios:
                    continue
                row = scenarios[name]
                rows.append({
                    "metric_id": metric.id,
                    "metric_name": name,
                    "direction": metric.direction,
                    "p5_total": float(row["p5"]),
                    "p50_total": float(row["p50"]),
                    "p95_total": float(row["p95"]),
                })
            cop = scenarios["CoP"]
            result, _ = MultiMetricMonteCarloResult.objects.update_or_create(
                corporate_risk_item=risk,
                forecast_periode=period,
                defaults={
                    "forecast_periods": 4,
                    "n_simulations": 10000,
                    "distribution_type": "normal",
                    "recommended_distribution": "normal",
                    "selected_distribution": "normal",
                    "selected_distribution_justification": "Validated Crystal Ball joint liquidity model",
                    "forecast_total": cop["p50"],
                    "target_value": targets["CoP"],
                    "target_gap": cop["p50"] - targets["CoP"],
                    "potential_loss": impact,
                    "probability_achieve_target": Decimal("0"),
                    "probability_not_achieve_target": probability,
                    "target_status": "TIDAK TERCAPAI",
                    "risk_status": "BAHAYA",
                    "worst_case_value": cop["p95"],
                    "baseline_value": cop["p50"],
                    "best_case_value": cop["p5"],
                    "requires_mitigation": True,
                    "metric_snapshot": {"metrics": rows},
                    "simulation_snapshot": {
                        "simulation_mode": "imported_assumptions",
                        "external_validation": {
                            "status": "PASS",
                            "source": "Crystal Ball Liquidity",
                            "source_file": source.name,
                            "source_sha256": [source_hash],
                            "validation_basis": "workbook_joint_model_piutang_pendapatan_cop",
                        },
                        "executive_risk": {
                            "probability_not_achieve_target": float(probability),
                            "impact_worst_case": float(impact),
                            "impact_metric_name": "Loss opportunity pendapatan",
                            "headline_worst_case_percentile": "P95",
                        },
                        "relationship": "CoP = Saldo Piutang / Pendapatan x 365",
                    },
                },
            )

        self.stdout.write(self.style.SUCCESS(f"APPLY PASS — Risk #1 imported; result ID={result.id}."))
