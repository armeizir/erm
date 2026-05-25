from django.core.management.base import BaseCommand, CommandError

from risk.services.kpmr_automation import (
    calculate_kpmr_for_period,
    save_kpmr_calculation,
)


class Command(BaseCommand):
    help = "Hitung otomatis KPMR resmi dari data Monthly Risk Report."

    def add_arguments(self, parser):
        parser.add_argument("--tahun", type=int, required=True)
        parser.add_argument("--triwulan", type=int, choices=[1, 2, 3, 4], required=True)
        parser.add_argument(
            "--save",
            action="store_true",
            help="Simpan hasil hitung ke tabel KPMR PLN - Periode.",
        )

    def handle(self, *args, **options):
        year = options["tahun"]
        quarter = options["triwulan"]
        calculations = calculate_kpmr_for_period(year, quarter)
        if not calculations:
            raise CommandError(f"Tidak ada laporan bulanan untuk {year} TW{quarter}.")

        for calculation in calculations:
            if options["save"]:
                save_kpmr_calculation(calculation)
            self.stdout.write(
                self.style.SUCCESS(
                    f"{calculation.unit.name} {year} TW{quarter}: "
                    f"{calculation.score_total} ({calculation.rating}), "
                    f"{calculation.report_count} laporan, {calculation.item_count} item"
                )
            )
            for indicator in calculation.indicators:
                self.stdout.write(
                    f"  - {indicator['kode']} {indicator['skor']} "
                    f"(hasil {indicator['hasil'] or '-'}) {indicator['keterangan']}"
                )
            for note in calculation.notes:
                self.stdout.write(self.style.WARNING(f"  ! {note}"))
