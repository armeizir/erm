from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import transaction

from risk.models import ReAssessmentItem
from risk.services.risk_exposure import calculate_item_quarterly_exposures


class Command(BaseCommand):
    help = "Audit or recalculate persisted quarterly risk exposure values."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")
        parser.add_argument("--profile-id", type=int)
        parser.add_argument("--unit-id", type=int)

    def handle(self, *args, **options):
        queryset = ReAssessmentItem.objects.order_by("pk")
        if options["profile_id"]:
            queryset = queryset.filter(summary_id=options["profile_id"])
        if options["unit_id"]:
            queryset = queryset.filter(unit_bisnis_id=options["unit_id"])

        profile_count = queryset.values("summary_id").distinct().count()
        checked = matched = different = unavailable = 0
        changes = []
        with transaction.atomic():
            for item in queryset.iterator():
                checked += 1
                partial_quarters = [
                    quarter
                    for quarter in range(1, 5)
                    if (
                        getattr(item, f"nilai_dampak_q{quarter}") is None
                    )
                    != (
                        getattr(item, f"nilai_probabilitas_q{quarter}") is None
                    )
                ]
                if partial_quarters:
                    unavailable += 1
                    self.stdout.write(
                        f"ID {item.pk}: sumber tidak lengkap pada "
                        + ", ".join(f"Q{quarter}" for quarter in partial_quarters)
                    )
                try:
                    calculated = calculate_item_quarterly_exposures(item)
                except ValidationError as exc:
                    if not partial_quarters:
                        unavailable += 1
                    self.stdout.write(
                        f"ID {item.pk}: tidak dapat dihitung ({'; '.join(exc.messages)})"
                    )
                    continue

                delta = {
                    field: (getattr(item, field), expected)
                    for field, expected in calculated.items()
                    if getattr(item, field) != expected
                }
                if not delta:
                    matched += 1
                    continue
                different += 1
                changes.append((item.pk, delta))
                details = ", ".join(
                    f"{field}: {before} -> {after}"
                    for field, (before, after) in delta.items()
                )
                self.stdout.write(f"ID {item.pk}: {details}")
                if options["apply"]:
                    ReAssessmentItem.objects.filter(pk=item.pk).update(
                        **calculated
                    )

            if options["dry_run"]:
                transaction.set_rollback(True)

        mode = "APPLY" if options["apply"] else "DRY-RUN"
        self.stdout.write("")
        self.stdout.write(f"Mode: {mode}")
        self.stdout.write(f"Profil Risiko diperiksa: {profile_count}")
        self.stdout.write(f"Item Profil Risiko diperiksa: {checked}")
        self.stdout.write(f"Exposure sudah sesuai: {matched}")
        self.stdout.write(f"Exposure berbeda: {different}")
        self.stdout.write(f"Tidak dapat dihitung: {unavailable}")
        if options["apply"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{len(changes)} item diperbarui; field lain tidak diubah."
                )
            )
