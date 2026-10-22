from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from risk.views import _unit_profile_rows
from risk.services.kpmr_automation import calculate_kpmr_for_report
from risk.services.whatsapp import (
    WhatsAppConfigurationError,
    profile_monitoring_message,
    send_fonnte_message,
)


class Command(BaseCommand):
    help = "Monitoring laporan risiko bulanan sesuai sumber dashboard."

    def add_arguments(self, parser):
        parser.add_argument("--send", action="store_true")
        parser.add_argument("--year", type=int, default=timezone.localdate().year)
        parser.add_argument(
            "--month", type=int, choices=range(1, 13),
            help="Bulan laporan; jika kosong, gunakan laporan terbaru per profil.",
        )

    def handle(self, *args, **options):
        # WHATSAPP_MONTHLY_DASHBOARD_SOURCE_V1
        dashboard_rows = _unit_profile_rows(
            options["year"], options["month"]
        )
        rows, approved_rows, progress_rows = [], [], []
        for row in dashboard_rows:
            report = row["report"]

            coverage = (
                f'{row["coverage"]:.1f}'.rstrip("0").rstrip(".")
                .replace(".", ",") + "%"
            )
            entry = {
                "unit": row["unit"],
                "month": (
                    str(report.periode) if report is not None
                    else (
                        f'Bulan {options["month"]} {options["year"]}'
                        if options["month"] else str(options["year"])
                    )
                ),
                "status": (
                    report.get_status_display()
                    if report is not None else "Belum Ada Laporan"
                ),
                "coverage": coverage,
            }
            if report is not None and report.status in {"approved", "locked"}:
                quarter = (report.periode.tanggal_mulai.month - 1) // 3 + 1
                entry["kpmr_period"] = f"TW{quarter}"
                if report.periode.tanggal_mulai.month in {3, 6, 9, 12}:
                    result = calculate_kpmr_for_report(report)
                    if result.is_complete and result.final_score is not None:
                        entry["kpmr_text"] = str(result.final_score)
                    else:
                        entry["kpmr_text"] = (
                            f"Sementara {result.provisional_score} "
                            f"(bobot tersedia {result.assessed_weight}%; "
                            "penilaian belum lengkap)"
                        )
                else:
                    entry["kpmr_text"] = "Menunggu laporan akhir triwulan"
                approved_rows.append(entry)
            elif report is not None and report.status in {"submitted", "under_review"}:
                progress_rows.append(entry)
            else:
                rows.append(entry)
            self.stdout.write(
                f'AUDIT: profil={row["id"]}; '
                f'report={report.pk if report else "-"}; '
                f'unit={row["unit"]}; '
                f'status={report.status if report else "belum_ada"}; '
                f'coverage={coverage}'
            )

        if not (rows or approved_rows or progress_rows):
            self.stdout.write(
                "Tidak ada data monitoring pada pilihan ini. "
                "WhatsApp tidak dikirim."
            )
            return

        message = profile_monitoring_message(rows, approved_rows, progress_rows)
        self.stdout.write(message)
        if not options["send"]:
            self.stdout.write(self.style.WARNING(
                "DRY-RUN: WhatsApp tidak dikirim."
            ))
            return

        try:
            result = send_fonnte_message(message)
        except (WhatsAppConfigurationError, RuntimeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Hasil pengiriman Fonnte: {result}"
        ))
