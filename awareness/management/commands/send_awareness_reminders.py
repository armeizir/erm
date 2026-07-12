from django.core.management.base import BaseCommand, CommandError

from awareness.models import AwarenessCampaign
from awareness.notifications import (
    active_awareness_campaigns,
    pending_awareness_users,
    send_awareness_notification,
)


class Command(BaseCommand):
    help = "Kirim notifikasi email awareness untuk campaign aktif atau email uji coba."

    def add_arguments(self, parser):
        parser.add_argument(
            "--campaign-id",
            type=int,
            help="ID campaign awareness. Jika kosong, campaign aktif terbaru akan digunakan.",
        )
        parser.add_argument(
            "--email",
            action="append",
            default=[],
            help="Email tujuan uji coba. Bisa dipakai berulang. Jika diisi, hanya email ini yang dikirim.",
        )
        parser.add_argument(
            "--base-url",
            default=None,
            help="Base URL aplikasi untuk tombol email, misalnya https://erm.plnbatam.com.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Tampilkan kandidat penerima tanpa mengirim email.",
        )

    def _campaign(self, campaign_id):
        if campaign_id:
            return AwarenessCampaign.objects.filter(pk=campaign_id).first()
        return active_awareness_campaigns().first()

    def handle(self, *args, **options):
        campaign = self._campaign(options["campaign_id"])
        if not campaign:
            raise CommandError("Tidak ada campaign awareness aktif atau campaign_id tidak ditemukan.")

        test_emails = options["email"]
        if test_emails:
            recipients = test_emails
            label = "test recipient"
        else:
            recipients = list(pending_awareness_users(campaign).values_list("email", flat=True))
            label = "pending user"

        self.stdout.write(f"Campaign: {campaign.title}")
        self.stdout.write(f"Recipients ({label}): {len(recipients)}")
        for email in recipients:
            self.stdout.write(f"- {email}")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: email tidak dikirim."))
            return

        sent = send_awareness_notification(
            campaign,
            recipients,
            base_url=options["base_url"],
        )
        self.stdout.write(self.style.SUCCESS(f"Email awareness terkirim: {sent}"))
