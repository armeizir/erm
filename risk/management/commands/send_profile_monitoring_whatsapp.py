from django.core.management.base import BaseCommand, CommandError

from risk.services.whatsapp import (
    WhatsAppConfigurationError,
    profile_monitoring_message,
    send_fonnte_message,
)


class Command(BaseCommand):
    help = "Kirim pesan monitoring Profil Risiko melalui WhatsApp Fonnte."

    def add_arguments(self, parser):
        parser.add_argument("--send", action="store_true", help="Kirim pesan ke WHATSAPP_TARGET.")

    def handle(self, *args, **options):
        message = profile_monitoring_message()
        if not options["send"]:
            self.stdout.write(message)
            self.stdout.write(self.style.WARNING("Mode dry-run: gunakan --send untuk mengirim."))
            return
        try:
            result = send_fonnte_message(message)
        except (WhatsAppConfigurationError, RuntimeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Pesan WhatsApp terkirim melalui Fonnte: {result}"))
