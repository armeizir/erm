from collections import defaultdict

from django.db import transaction
from django.db.models import Count

from risk.models import ReAssessmentItem


def next_available_no_risiko_for_summary_item(summary_id: int, no_item: int, taken: set[int]) -> int:
    candidate = 1
    while candidate in taken:
        candidate += 1
    return candidate


def main():
    # Migration 0047 introduces UNIQUE(summary, no_item, no_risiko)
    # So duplicates are groups by (summary_id, no_item, no_risiko)
    dup_groups = (
        ReAssessmentItem.objects.values("summary_id", "no_item", "no_risiko")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )

    groups = list(dup_groups)
    print(f"Found duplicate groups (summary,no_item,no_risiko): {len(groups)}")

    # Preload taken no_risiko per (summary_id, no_item)
    taken_map = defaultdict(set)
    for row in ReAssessmentItem.objects.values("summary_id", "no_item", "no_risiko"):
        if row["no_risiko"] is None:
            continue
        taken_map[(row["summary_id"], row["no_item"] )].add(int(row["no_risiko"]))

    fixed_total = 0

    with transaction.atomic():
        for g in groups:
            summary_id = g["summary_id"]
            no_item = g["no_item"]
            no_risiko = g["no_risiko"]

            qs = (
                ReAssessmentItem.objects.filter(
                    summary_id=summary_id,
                    no_item=no_item,
                    no_risiko=no_risiko,
                )
                .order_by("id")
            )
            items = list(qs)
            if len(items) <= 1:
                continue

            keep = items[0]
            to_update = items[1:]

            taken = taken_map[(summary_id, no_item)]

            for item in to_update:
                new_no = next_available_no_risiko_for_summary_item(summary_id, no_item, taken)
                item.no_risiko = new_no
                item.save(update_fields=["no_risiko"])
                taken.add(new_no)
                fixed_total += 1

            print(
                f"summary_id={summary_id} no_item={no_item} no_risiko={no_risiko}: keep={keep.id} updated={len(to_update)}"
            )

        print(f"Total rows updated: {fixed_total}")

    # Verify duplicates are gone
    dup_after = (
        ReAssessmentItem.objects.values("summary_id", "no_item", "no_risiko")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )
    dup_after_list = list(dup_after)
    print(f"Remaining duplicate groups after fix: {len(dup_after_list)}")
    if dup_after_list:
        print(dup_after_list)


if __name__ == "__main__":
    main()

