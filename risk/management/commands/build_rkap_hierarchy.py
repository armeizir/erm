from risk.models import RKAPItem
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Build hierarchy RKAP"

    def handle(self, *args, **kwargs):

        items = RKAPItem.objects.filter(
            tahun=2026,
            subkategori="Lampiran 2 Neraca Non ISAK"
        ).order_by("kode")

        mapping = {}

        for item in items:
            mapping[item.kode] = item

        for item in items:

            kode = item.kode

            parent = None

            if "." in kode:

                parent_code = ".".join(kode.split(".")[:-1])

                if parent_code in mapping:
                    parent = mapping[parent_code]

            item.parent = parent
            item.save(update_fields=["parent"])

            self.stdout.write(
                f"{item.kode} -> {parent.kode if parent else 'ROOT'}"
            )

        self.stdout.write(
            self.style.SUCCESS("Hierarchy selesai dibuat")
        )
