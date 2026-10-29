"""Uses the same latest-report selection as the morning WhatsApp monitor."""
import hashlib
import json
import os
from pathlib import Path
from contextlib import contextmanager
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from risk.views import _unit_profile_rows
from risk.services.kpmr_automation import calculate_kpmr_for_report
from risk.services.kpmr_incomplete_email import prepare_notification, send_notification


@contextmanager
def delivery_lock(path):
    import fcntl  # Supported on deployment Linux and local macOS.
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'r+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


class Command(BaseCommand):
    help = 'Email perbaikan KPMR belum lengkap. Default simulasi; --send untuk mengirim.'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, default=timezone.localdate().year)
        parser.add_argument('--month', type=int, choices=range(1, 13))
        parser.add_argument('--report-id', type=int, help='Batasi ke laporan dalam hasil monitoring dashboard.')
        parser.add_argument('--base-url')
        parser.add_argument('--send', action='store_true')

    def handle(self, *args, **options):
        count, failures = 0, []
        rows = _unit_profile_rows(options['year'], options['month'])
        seen = set()
        for row in rows:
            report = row['report']
            if report is None or report.pk in seen:
                continue
            seen.add(report.pk)
            if options['report_id'] and report.pk != options['report_id']:
                continue
            if report.status not in {'approved', 'locked'}:
                continue
            if report.periode.tanggal_mulai.month not in {3, 6, 9, 12}:
                continue
            try:
                result = calculate_kpmr_for_report(report)
                if result.is_complete:
                    continue
                prepared = prepare_notification(report, result, options['base_url'])
                count += 1
                self.stdout.write(f"\nLAPORAN #{report.pk}\nTo: {', '.join(prepared['to']) or '-'}\nCC: {', '.join(prepared['cc']) or '-'}")
                for warning in prepared['warnings']:
                    self.stdout.write('PERINGATAN: ' + warning)
                self.stdout.write(prepared['subject'] + '\n' + prepared['body'])
                if not options['send']:
                    continue
                # Fail closed: all required roles must be resolved before live sending.
                if prepared['warnings']:
                    raise ValueError('Perbaiki pemetaan penerima di atas sebelum pengiriman.')
                folder = Path(getattr(settings, 'KPMR_EMAIL_LOG_ROOT', Path(settings.BASE_DIR) / 'private_notification_logs'))
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                key = hashlib.sha256(f'{timezone.localdate()}:{report.pk}'.encode()).hexdigest()
                marker = folder / (key + '.json')
                with delivery_lock(folder / (key + '.lock')):
                    if marker.exists():
                        self.stdout.write('SKIP: email laporan ini sudah dikirim hari ini.')
                        continue
                    send_notification(prepared)
                    # Contains delivery metadata, never SMTP passwords or full risk details.
                    fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    with os.fdopen(fd, 'w') as stream:
                        json.dump({'report_id': report.pk, 'sent_at': timezone.now().isoformat(),
                                   'to': prepared['to'], 'cc': prepared['cc']}, stream)
                self.stdout.write('TERKIRIM: diterima backend SMTP.')
            except Exception as exc:
                failures.append(f'Laporan {report.pk}: {exc}')
                self.stderr.write(f'ERROR laporan {report.pk}: {exc}')
        self.stdout.write(f'Jumlah laporan belum lengkap yang disiapkan: {count}')
        if not options['send']:
            self.stdout.write('SIMULASI: email tidak dikirim; database dan status laporan tidak diubah.')
        if failures:
            raise CommandError('\n'.join(failures))
