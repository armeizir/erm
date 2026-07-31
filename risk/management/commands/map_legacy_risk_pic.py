from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from risk.models import ReAssessmentItem
from risk.services.pic import match_organization


class Command(BaseCommand):
    help = "Petakan PIC free text ReAssessmentItem ke Master Organization Unit."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Simpan hanya hasil exact/normalized yang mempunyai satu kandidat.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        counts = Counter()
        updates = []
        items = ReAssessmentItem.objects.order_by("pk")

        for item in items:
            status, candidates = match_organization(item.pic)
            if item.pic_organization_unit_id:
                counts["already_mapped"] += 1
                status = "already_mapped"
            else:
                counts[status] += 1
                if status in {"exact", "normalized"} and len(candidates) == 1:
                    updates.append((item.pk, candidates[0].pk))

            candidate_text = ", ".join(
                f"{candidate.code} - {candidate.name}"
                for candidate in candidates
            ) or "-"
            self.stdout.write(
                f"ID={item.pk} | status={status} | "
                f"legacy={item.pic!r} | kandidat={candidate_text}"
            )

        if apply_changes:
            with transaction.atomic():
                for item_id, organization_id in updates:
                    ReAssessmentItem.objects.filter(
                        pk=item_id,
                        pic_organization_unit__isnull=True,
                    ).update(pic_organization_unit_id=organization_id)

        self.stdout.write("")
        self.stdout.write(f"MODE: {'APPLY' if apply_changes else 'DRY-RUN'}")
        self.stdout.write(f"TOTAL: {items.count()}")
        for key in (
            "exact",
            "normalized",
            "ambiguous",
            "unmatched",
            "blank",
            "already_mapped",
        ):
            self.stdout.write(f"{key.upper()}: {counts[key]}")
        self.stdout.write(
            f"DIUBAH: {len(updates) if apply_changes else 0}"
        )
