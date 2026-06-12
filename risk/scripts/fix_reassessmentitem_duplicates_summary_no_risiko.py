from collections import defaultdict

from django.db import transaction
from django.db.models import Count

from risk.models import ReAssessmentItem


def next_available_no_item(summary_id: int, taken: set[int]) -> int:
    candidate = 1
    while candidate in taken:
        candidate += 1
    return candidate


def main():
    # Target UNIQUE(summary_id, no_risiko)
    # Since 0047 failed at UNIQUE(summary_id, no_risiko) during table remake,
    # we ensure that for each (summary_id, no_risiko) there is only one row.

    dup_groups = (
        ReAssessmentItem.objects.values("summary_id", "no_risiko")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )

    groups = list(dup_groups)
    print(f"Found duplicate groups (summary_id,no_risiko): {len(groups)}")

    # taken no_item per (summary_id, no_risiko) pair is not sufficient.
    # We will change `no_item` for extra rows so that the final UNIQUE(summary,no_risiko)
    # is satisfied during migration remake.

    # For a given summary_id, we need no_risiko to be unique.
    # Therefore, move extra rows to free `no_risiko` values not used in that summary.

    # Preload taken no_risiko per summary
    summary_taken_risiko = defaultdict(set)
    for row in ReAssessmentItem.objects.values("summary_id", "no_risiko"):
        if row["no_risiko"] is None:
            continue
        summary_taken_risiko[row["summary_id"]].add(int(row["no_risiko"]))

    fixed_total = 0

    with transaction.atomic():
        for g in groups:
            summary_id = g["summary_id"]
            no_risiko = int(g["no_risiko"])

            qs = (
                ReAssessmentItem.objects.filter(
                    summary_id=summary_id,
                    no_risiko=no_risiko,
                ).order_by("id")
            )
            items = list(qs)
            if len(items) <= 1:
                continue

            keep = items[0]
            to_update = items[1:]

            taken = summary_taken_risiko[summary_id]

            for item in to_update:
                # pick next free no_risiko within the same summary
                candidate = 1
                while candidate in taken:
                    candidate += 1
                item.no_risiko = candidate
                item.save(update_fields=["no_risiko"])

                taken.add(candidate)
                fixed_total += 1

            print(
                f"summary_id={summary_id} no_risiko={no_risiko}: keep={keep.id} updated={len(to_update)}"
            )

        print(f"Total rows updated: {fixed_total}")

    # verify
    dup_after = (
        ReAssessmentItem.objects.values("summary_id", "no_risiko")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )
    dup_after_list = list(dup_after)
    print(f"Remaining duplicate groups after fix: {len(dup_after_list)}")
    if dup_after_list:
        print(dup_after_list[:20])


if __name__ == "__main__":
    main()

