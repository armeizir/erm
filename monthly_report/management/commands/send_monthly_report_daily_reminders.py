from __future__ import annotations

from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from monthly_report.models import MonthlyRiskReport
from monthly_report.notifications import (
    monthly_report_notification_stage,
    resolve_monthly_report_notification_recipients,
    send_monthly_report_notification,
)


FINAL_STATUSES = {"approved", "locked"}


def previous_month(value: date) -> tuple[int, int]:
    """Return the year and month immediately before *value*."""
    previous_day = value.replace(day=1) - timedelta(days=1)
    return previous_day.year, previous_day.month


def select_latest_pending_reports(reports):
    """
    Keep only the newest version for each risk profile, then exclude final reports.

    The queryset must be ordered by:
        reassessment_id, -versi, -pk
    """
    seen_reassessments: set[int] = set()

    for report in reports:
        if report.reassessment_id in seen_reassessments:
            continue

        seen_reassessments.add(report.reassessment_id)

        if report.status in FINAL_STATUSES:
            continue

        yield report


def latest_pending_reports(year: int, month: int, report_ids=None):
    queryset = (
        MonthlyRiskReport.objects.select_related(
            "reassessment",
            "periode",
            "reviewed_by",
            "approved_by",
        )
        .filter(
            periode__tanggal_mulai__year=year,
            periode__tanggal_mulai__month=month,
        )
    )

    if report_ids:
        queryset = queryset.filter(pk__in=report_ids)

    ordered = queryset.order_by(
        "reassessment_id",
        "-versi",
        "-pk",
    )
    return list(select_latest_pending_reports(ordered))


class Command(BaseCommand):
    help = (
        "Kirim pengingat harian untuk laporan risiko bulan sebelumnya "
        "yang versi terbarunya belum berstatus Approved."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            dest="run_date",
            help=(
                "Tanggal eksekusi YYYY-MM-DD untuk pengujian. "
                "Default: tanggal lokal aplikasi."
            ),
        )
        parser.add_argument(
            "--base-url",
            default="https://erm.plnbatam.com",
            help="Base URL yang dipakai pada tombol Buka Laporan.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Tampilkan laporan dan penerima tanpa mengirim email.",
        )
        parser.add_argument(
            "--test-email",
            default="",
            help=(
                "Alihkan seluruh pengiriman ke satu email uji coba. "
                "Jangan gunakan opsi ini pada timer produksi."
            ),
        )
        parser.add_argument(
            "--report-id",
            action="append",
            type=int,
            dest="report_ids",
            help=(
                "Batasi ke ID laporan tertentu. Dapat ditulis berulang. "
                "Ditujukan untuk pengujian."
            ),
        )

    def handle(self, *args, **options):
        run_date = self._resolve_run_date(options.get("run_date"))
        target_year, target_month = previous_month(run_date)
        base_url = (options.get("base_url") or "").strip().rstrip("/")
        dry_run = bool(options.get("dry_run"))
        test_email = (options.get("test_email") or "").strip()
        report_ids = options.get("report_ids") or []

        reports = latest_pending_reports(
            target_year,
            target_month,
            report_ids=report_ids,
        )

        self.stdout.write(
            "Pengingat laporan risiko bulanan"
            f" | tanggal proses={run_date.isoformat()}"
            f" | periode target={target_year:04d}-{target_month:02d}"
            f" | kandidat={len(reports)}"
        )

        if not reports:
            self.stdout.write(
                self.style.SUCCESS(
                    "Tidak ada laporan versi terbaru yang perlu diingatkan."
                )
            )
            return

        sent_count = 0
        failed_count = 0
        skipped_count = 0

        for report in reports:
            stage = monthly_report_notification_stage(report)
            if not stage:
                skipped_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"SKIP report={report.pk}: status "
                        f"{report.status!r} tidak memiliki tahap notifikasi."
                    )
                )
                continue

            subject = (
                f"[PENGINGAT OTOMATIS] {stage['title']} - "
                f"{report.reassessment} {report.periode.nama_periode}"
            )
            instruction = (
                "Pengingat otomatis harian: laporan risiko "
                f"{report.periode.nama_periode} masih berstatus "
                f"{report.get_status_display()} dan belum Approved. "
                f"{stage['instruction']}"
            )

            try:
                if dry_run:
                    delivery = resolve_monthly_report_notification_recipients(
                        report,
                        stage=stage,
                        delivery_mode=(
                            "test" if test_email else "final"
                        ),
                        test_email_override=test_email,
                    )
                    self.stdout.write(
                        f"DRY-RUN report={report.pk}"
                        f" | {report.reassessment}"
                        f" | status={report.status}"
                        f" | TO={delivery['recipients']}"
                        f" | CC={delivery['cc_recipients']}"
                        f" | BCC={delivery['bcc_recipients']}"
                    )
                    continue

                sent = send_monthly_report_notification(
                    report,
                    base_url=base_url,
                    delivery_mode=(
                        "test" if test_email else "final"
                    ),
                    test_email_override=test_email,
                    subject_override=subject,
                    instruction_override=instruction,
                )

                if sent:
                    sent_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"SENT report={report.pk}"
                            f" | {report.reassessment}"
                            f" | status={report.status}"
                        )
                    )
                else:
                    failed_count += 1
                    self.stderr.write(
                        self.style.ERROR(
                            f"FAILED report={report.pk}: "
                            "backend email mengembalikan 0."
                        )
                    )
            except ValidationError as exc:
                failed_count += 1
                message = (
                    "; ".join(exc.messages)
                    if hasattr(exc, "messages")
                    else str(exc)
                )
                self.stderr.write(
                    self.style.ERROR(
                        f"FAILED report={report.pk}: {message}"
                    )
                )
            except Exception as exc:
                failed_count += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"FAILED report={report.pk}: "
                        f"{type(exc).__name__}: {exc}"
                    )
                )

        self.stdout.write(
            "Ringkasan"
            f" | sent={sent_count}"
            f" | failed={failed_count}"
            f" | skipped={skipped_count}"
            f" | dry_run={dry_run}"
        )

        if failed_count:
            raise CommandError(
                f"{failed_count} laporan gagal dikirim. "
                "Periksa log dan konfigurasi penerima/SMTP."
            )

    @staticmethod
    def _resolve_run_date(raw_value: str | None) -> date:
        if not raw_value:
            return timezone.localdate()

        value = parse_date(raw_value)
        if value is None:
            raise CommandError(
                "--date harus menggunakan format YYYY-MM-DD."
            )
        return value
