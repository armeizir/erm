from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from awareness.models import AwarenessAttempt, AwarenessCampaign


class Command(BaseCommand):
    help = "Menampilkan daftar user yang perlu diingatkan mengikuti awareness aktif."

    def handle(self, *args, **options):
        today = timezone.localdate()
        campaigns = AwarenessCampaign.objects.filter(
            is_active=True,
            start_date__lte=today,
            end_date__gte=today,
        ).order_by("title")
        users = get_user_model().objects.filter(is_active=True).order_by("username")
        total = 0

        for campaign in campaigns:
            attempted_ids = AwarenessAttempt.objects.filter(campaign=campaign).values_list("user_id", flat=True)
            pending = users.exclude(id__in=attempted_ids)
            self.stdout.write(f"Campaign: {campaign.title}")
            for user in pending:
                total += 1
                self.stdout.write(f"- {user.get_username()} <{user.email}>")

        if total == 0:
            self.stdout.write("Tidak ada user yang perlu diingatkan.")
        else:
            self.stdout.write(self.style.WARNING(
                f"Total reminder candidate: {total}. Email/WA belum dikirim; output console saja."
            ))
