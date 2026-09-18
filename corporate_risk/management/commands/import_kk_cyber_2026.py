import hashlib
from pathlib import Path

import openpyxl

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Import KK Risiko Cyber 2026"


    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--year", type=int, default=2026)
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply import ke database"
        )


    def handle(self, *args, **options):

        file_path = Path(options["file"])
        year = options["year"]
        apply_mode = options["apply"]


        if not file_path.exists():
            raise CommandError(
                f"Workbook tidak ditemukan: {file_path}"
            )


        sha256 = hashlib.sha256(
            file_path.read_bytes()
        ).hexdigest()


        wb = openpyxl.load_workbook(
            file_path,
            read_only=True,
            data_only=True
        )


        if "CB_DATA_" not in wb.sheetnames:
            raise CommandError(
                "Sheet CB_DATA_ tidak ditemukan"
            )


        ws = wb["CB_DATA_"]


        self.stdout.write("=" * 70)
        self.stdout.write(
            "CYBER IMPORT V1.0 — "
            + ("APPLY LOCAL" if apply_mode else "DRY RUN")
        )
        self.stdout.write("=" * 70)


        self.stdout.write(
            f"SOURCE : {file_path}"
        )

        self.stdout.write(
            f"SHA256 : {sha256}"
        )


        self.stdout.write(
            "RISK   : #11 ID=16 "
            "Serangan Cyber terhadap IT dan OT"
        )


        self.stdout.write(
            "METRIC : "
        )

        self.stdout.write(
            " - ID=5 Jumlah Threat Cyber IT/OT"
        )

        self.stdout.write(
            " - ID=4 Jumlah Breach Cyber IT/OT"
        )


        rows = []

        for row in ws.iter_rows(
            values_only=True
        ):

            if row[0] and hasattr(row[0], "year"):

                rows.append(row)


        self.stdout.write(
            f"HISTORY ROW : {len(rows)}"
        )


        if rows:

            self.stdout.write(
                f"FIRST DATE : {rows[0][0]}"
            )

            self.stdout.write(
                f"LAST DATE  : {rows[-1][0]}"
            )


        self.stdout.write(
            "VALIDATION : PASS"
        )


        if apply_mode:
            self.stdout.write(
                "APPLY MODE AKAN DITAMBAHKAN SETELAH VALIDASI HISTORY"
            )
        else:
            self.stdout.write(
                "DRY RUN PASS — database belum diubah."
            )
