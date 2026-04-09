from django.core.management.base import BaseCommand
from django.db import transaction

from risk.models import (
    RiskMatrix,
    RiskMatrixCell,
    MasterLevelRisiko,
    MasterSkalaDampak,
    MasterSkalaProbabilitas,
)


class Command(BaseCommand):
    help = "Seed default risk matrix 5x5 PLN Batam"

    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite existing default matrix cells",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        overwrite = options["overwrite"]

        level_definitions = [
            ("LOW", "Low", "#5B8F3A", 1),
            ("LOW_TO_MODERATE", "Low to Moderate", "#B8D4A2", 2),
            ("MODERATE", "Moderate", "#F3EF19", 3),
            ("MODERATE_TO_HIGH", "Moderate to High", "#F2B01E", 4),
            ("HIGH", "High", "#D50F0F", 5),
        ]

        level_map = {}
        for kode, nama, warna_hex, urutan in level_definitions:
            obj, _ = MasterLevelRisiko.objects.update_or_create(
                kode=kode,
                defaults={
                    "nama": nama,
                    "warna_hex": warna_hex,
                    "urutan": urutan,
                    "aktif": True,
                },
            )
            level_map[kode] = obj

        matrix, created = RiskMatrix.objects.get_or_create(
            kode="MATRIX-5X5-DEFAULT",
            defaults={
                "nama": "Matriks Risiko 5x5 Default PLN Batam",
                "ukuran": 5,
                "aktif": True,
                "is_default": True,
            },
        )

        if not created:
            matrix.nama = "Matriks Risiko 5x5 Default PLN Batam"
            matrix.ukuran = 5
            matrix.aktif = True
            matrix.is_default = True
            matrix.save()

        dampak_list = list(MasterSkalaDampak.objects.order_by("urutan", "id")[:5])
        probabilitas_list = list(MasterSkalaProbabilitas.objects.order_by("urutan", "id")[:5])

        if len(dampak_list) < 5:
            self.stdout.write(
                self.style.ERROR(
                    "MasterSkalaDampak kurang dari 5 data. Isi dulu master dampak 1-5."
                )
            )
            return

        if len(probabilitas_list) < 5:
            self.stdout.write(
                self.style.ERROR(
                    "MasterSkalaProbabilitas kurang dari 5 data. Isi dulu master probabilitas 1-5."
                )
            )
            return

        def get_level(score):
            if 1 <= score <= 4:
                return level_map["LOW"]
            elif 5 <= score <= 9:
                return level_map["LOW_TO_MODERATE"]
            elif 10 <= score <= 15:
                return level_map["MODERATE"]
            elif 16 <= score <= 19:
                return level_map["MODERATE_TO_HIGH"]
            return level_map["HIGH"]

        if overwrite:
            RiskMatrixCell.objects.filter(matrix=matrix).delete()

        created_count = 0
        updated_count = 0

        for p_index, probabilitas in enumerate(probabilitas_list, start=1):
            for d_index, dampak in enumerate(dampak_list, start=1):
                skor = d_index * p_index
                level = get_level(skor)

                obj, was_created = RiskMatrixCell.objects.update_or_create(
                    matrix=matrix,
                    skala_dampak=dampak,
                    skala_probabilitas=probabilitas,
                    defaults={
                        "skor": skor,
                        "level_risiko": level,
                        "warna_hex": level.warna_hex,
                        "aktif": True,
                    },
                )

                if was_created:
                    created_count += 1
                else:
                    updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed selesai. Matrix={matrix.kode}, created={created_count}, updated={updated_count}"
            )
        )