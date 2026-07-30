from collections import Counter

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import transaction

from risk.models import ReAssessmentItem
from risk.services.risk_level import classify_risk_level


class Command(BaseCommand):
    help = "Audit and optionally synchronize quarterly risk levels from risk scales."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist corrected risk levels. The default is a read-only dry-run.",
        )
        parser.add_argument("--profile-id", type=int)
        parser.add_argument("--unit-id", type=int)

    def handle(self, *args, **options):
        queryset = ReAssessmentItem.objects.order_by("pk")
        if options["profile_id"]:
            queryset = queryset.filter(summary_id=options["profile_id"])
        if options["unit_id"]:
            queryset = queryset.filter(unit_bisnis_id=options["unit_id"])

        totals = Counter()
        quarterly = {quarter: Counter() for quarter in range(1, 5)}
        label_variants = Counter()
        changes = {}

        with transaction.atomic():
            for item in queryset.iterator():
                totals["items"] += 1
                item_changes = {}
                for quarter in range(1, 5):
                    scale = getattr(item, f"skala_risiko_q{quarter}")
                    old_level = getattr(item, f"level_nilai_risiko_q{quarter}")
                    if old_level:
                        label_variants[str(old_level).strip()] += 1

                    if scale in (None, ""):
                        if old_level:
                            totals["level_without_scale"] += 1
                            quarterly[quarter]["level_without_scale"] += 1
                            item_changes[f"level_nilai_risiko_q{quarter}"] = None
                        else:
                            totals["matched"] += 1
                            quarterly[quarter]["matched"] += 1
                        continue

                    try:
                        expected = classify_risk_level(scale).workbook_label
                    except ValidationError:
                        totals["invalid_scale"] += 1
                        quarterly[quarter]["invalid_scale"] += 1
                        self.stdout.write(
                            f"ID {item.pk} Q{quarter}: skala={scale!r}, "
                            f"level lama={old_level!r}, hasil=INVALID"
                        )
                        continue

                    if not old_level:
                        totals["blank_with_scale"] += 1
                        quarterly[quarter]["blank_with_scale"] += 1
                    elif old_level == expected:
                        totals["matched"] += 1
                        quarterly[quarter]["matched"] += 1
                        continue
                    else:
                        totals["different"] += 1
                        quarterly[quarter]["different"] += 1

                    item_changes[f"level_nilai_risiko_q{quarter}"] = expected
                    self.stdout.write(
                        f"ID {item.pk} Q{quarter}: skala={scale!r}, "
                        f"level lama={old_level!r}, hasil={expected!r}"
                    )

                if item_changes:
                    changes[item.pk] = item_changes
                    if options["apply"]:
                        ReAssessmentItem.objects.filter(pk=item.pk).update(
                            **item_changes
                        )

            if not options["apply"]:
                transaction.set_rollback(True)

        self.stdout.write("")
        self.stdout.write(f"Mode: {'APPLY' if options['apply'] else 'DRY-RUN'}")
        self.stdout.write(
            "Profil diperiksa: "
            f"{queryset.values('summary_id').distinct().count()}"
        )
        self.stdout.write(f"Item diperiksa: {totals['items']}")
        self.stdout.write(f"Level sesuai: {totals['matched']}")
        self.stdout.write(f"Level berbeda: {totals['different']}")
        self.stdout.write(
            f"Level kosong tetapi skala tersedia: {totals['blank_with_scale']}"
        )
        self.stdout.write(
            f"Level tersedia tetapi skala kosong: {totals['level_without_scale']}"
        )
        self.stdout.write(f"Skala di luar rentang: {totals['invalid_scale']}")
        for quarter in range(1, 5):
            values = quarterly[quarter]
            self.stdout.write(
                f"Q{quarter}: sesuai={values['matched']}, "
                f"berbeda={values['different']}, "
                f"kosong_dengan_skala={values['blank_with_scale']}, "
                f"level_tanpa_skala={values['level_without_scale']}, "
                f"invalid={values['invalid_scale']}"
            )
        variants = ", ".join(
            f"{label!r}={count}"
            for label, count in sorted(label_variants.items())
        )
        self.stdout.write(f"Variasi label existing: {variants or '-'}")
        if options["apply"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{len(changes)} item disinkronkan; field lain tidak diubah."
                )
            )
