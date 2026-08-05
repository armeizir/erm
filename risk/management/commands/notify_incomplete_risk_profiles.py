from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from risk.services.profile_completeness import (
    check_profile_completeness,
    close_resolved_notifications,
    log_undeliverable_notification,
    profile_completeness_queryset,
    profile_mail_connection,
    resolve_profile_recipients,
    send_profile_completeness_notification,
    should_send_notification,
)


class Command(BaseCommand):
    help = "Periksa kelengkapan Profil Risiko Unit/Bidang dan kirim notifikasi jika diminta."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int)
        parser.add_argument("--current-year", action="store_true")
        parser.add_argument("--profile-id", type=int)
        parser.add_argument("--unit-id", type=int)
        parser.add_argument("--status", choices=("legacy", "draft", "approved", "final"))
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--send", action="store_true")
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--verbose", action="store_true")

    def handle(self, *args, **options):
        if options["force"] and not options["send"]:
            raise CommandError("--force hanya dapat digunakan bersama --send.")
        if options["year"] and options["current_year"]:
            raise CommandError("Gunakan salah satu --year atau --current-year.")
        queryset = profile_completeness_queryset()
        if options["current_year"]:
            queryset = queryset.filter(tahun=timezone.localdate().year)
        for option, lookup in (("year", "tahun"), ("profile_id", "pk"), ("unit_id", "unit_bisnis_id"), ("status", "status")):
            if options[option] is not None:
                queryset = queryset.filter(**{lookup: options[option]})

        checked = incomplete = sent = failed = 0
        connection = profile_mail_connection() if options["send"] else None
        if connection:
            connection.open()
        try:
            for profile in queryset.iterator(chunk_size=100):
                checked += 1
                try:
                    result = check_profile_completeness(profile)
                    if result.is_complete:
                        close_resolved_notifications(profile)
                        if options["verbose"]:
                            self.stdout.write(f"{profile.pk} | {profile} | LENGKAP")
                        continue
                    incomplete += 1
                    recipients = resolve_profile_recipients(profile)
                    allowed, reason = should_send_notification(result, recipients, force=options["force"])
                    self.stdout.write("\n" + "=" * 72)
                    self.stdout.write(f"Profil Risiko : {profile}")
                    self.stdout.write(f"Unit          : {profile.unit_bisnis.name}")
                    self.stdout.write(f"To            : {', '.join(recipients['to']) or 'Belum ditetapkan'}")
                    self.stdout.write(f"CC Pairing    : {', '.join(recipients['cc']) or 'Belum ditetapkan'}")
                    self.stdout.write(f"Jumlah Temuan : {len(result.findings)} ({result.error_count} error, {result.warning_count} warning)")
                    for warning in recipients["warnings"]:
                        self.stdout.write(self.style.WARNING(f"Warning       : {warning}"))
                    self.stdout.write(f"Status Kirim  : {'Akan dikirim' if allowed else 'Lewati'} — {reason}")
                    if options["verbose"] or not options["send"]:
                        for finding in result.findings:
                            prefix = f"{finding.item_label}: " if finding.item_label else ""
                            self.stdout.write(f"  [{finding.severity.upper()}] {finding.section} — {prefix}{finding.message}")
                    if options["send"] and allowed:
                        ok, error = send_profile_completeness_notification(result, recipients, connection=connection)
                        sent += int(ok)
                        failed += int(not ok)
                        if not ok:
                            self.stderr.write(self.style.ERROR(f"Gagal profile {profile.pk}: {error}"))
                    elif options["send"] and not recipients["to"]:
                        log_undeliverable_notification(result, recipients, reason)
                        failed += 1
                except Exception as exc:
                    failed += 1
                    self.stderr.write(self.style.ERROR(f"Gagal memproses profile {profile.pk}: {exc}"))
        finally:
            if connection:
                connection.close()
        self.stdout.write("\n" + f"Ringkasan | diperiksa={checked} | tidak_lengkap={incomplete} | terkirim={sent} | gagal={failed} | mode={'send' if options['send'] else 'dry-run'}")
        if failed:
            raise CommandError(f"Terdapat {failed} kegagalan teknis.")
