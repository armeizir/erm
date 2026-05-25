from collections import defaultdict

from django.db import transaction
from django.db.models import Count

from risk.models import ReAssessmentItem


def next_available_no_risiko(summary_id: int, taken: set[int]) -> int:
    candidate = 1
    while candidate in taken:
        candidate += 1
    return candidate


def main():
    # Find duplicate groups for the constraint (summary_id, no_risiko)
    dup_groups = (
        ReAssessmentItem.objects.values("summary_id", "no_risiko")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )

    groups = list(dup_groups)
    print(f"Found duplicate groups: {len(groups)}")

    # Preload by summary_id the set of taken numbers
    summary_to_taken = defaultdict(set)
    for row in (
        ReAssessmentItem.objects.values("summary_id", "no_risiko")
    ):
        if row["no_risiko"] is not None:
            summary_to_taken[row["summary_id"]].add(int(row["no_risiko"]))

    with transaction.atomic():
        fixed_total = 0
        for g in groups:
            summary_id = g["summary_id"]
            no_risiko = int(g["no_risiko"])

            # Keep the smallest id, update the rest
            qs = (
                ReAssessmentItem.objects.filter(
                    summary_id=summary_id,
                    no_risiko=no_risiko,
                )
                .order_by("id")
            )
            items = list(qs)
            if len(items) <= 1:
                continue

            keep = items[0]
            to_update = items[1:]

            taken = summary_to_taken[summary_id]

            for item in to_update:
                new_no = next_available_no_risiko(summary_id, taken)
                item.no_risiko = new_no
                item.save(update_fields=["no_risiko"])

                taken.add(new_no)
                fixed_total += 1

            print(
                f"summary_id={summary_id} no_risiko={no_risiko}: keep={keep.id} updated={len(to_update)}"
            )

        print(f"Total rows updated: {fixed_total}")

    # Final verification
    dup_after = (
        ReAssessmentItem.objects.values("summary_id", "no_risiko")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )
    dup_after_list = list(dup_after)
    print(f"Remaining duplicate groups: {len(dup_after_list)}")
    if dup_after_list:
        print(dup_after_list)


if __name__ == "__main__":
    main()

