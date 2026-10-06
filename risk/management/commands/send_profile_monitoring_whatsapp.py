from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from risk.models import KPMRPeriode
from risk.services.profile_completeness import check_profile_completeness, latest_profile_revisions, profile_completeness_queryset

from risk.services.whatsapp import (
    WhatsAppConfigurationError,
    profile_monitoring_message,
    send_fonnte_message,
)


class Command(BaseCommand):
    help = "Kirim pesan monitoring Profil Risiko melalui WhatsApp Fonnte."

    def add_arguments(self, parser):
        parser.add_argument("--send", action="store_true", help="Kirim pesan ke WHATSAPP_TARGET.")
        parser.add_argument("--year", type=int, default=timezone.localdate().year)

    def handle(self, *args, **options):
        queryset = latest_profile_revisions(profile_completeness_queryset().filter(tahun=options["year"]))
        month_names = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
        pending_rows, approved_rows, progress_rows = [], [], []
        for profile in queryset.order_by("unit_bisnis__name", "pk"):
            result = check_profile_completeness(profile)
            row = {
                "unit": profile.unit_bisnis.name,
                "month": month_names[profile.rkm.bulan] if profile.rkm and profile.rkm.bulan else "-",
                "status": profile.get_status_display(),
                "coverage": result.percentage_display.replace(",00%", "%"),
            }
            monthly = profile.monthly_reports.order_by("-periode__tanggal_mulai", "-versi", "-pk").first()
            if monthly and monthly.status in {"submitted", "under_review"}:
                row["status"] = monthly.get_status_display()
                progress_rows.append(row)
            elif profile.status in {"approved", "final"} or (monthly and monthly.status in {"approved", "locked"}):
                quarter = ((monthly.periode.tanggal_mulai.month - 1) // 3 + 1) if monthly else 1
                kpmr = KPMRPeriode.objects.filter(tahun=options["year"], triwulan=quarter, unit_bisnis_id=profile.unit_bisnis_id).first()
                row.update({"kpmr_period": f"TW{quarter}", "kpmr_score": kpmr.skor_total if kpmr else None})
                approved_rows.append(row)
            else:
                pending_rows.append(row)
        message = profile_monitoring_message(pending_rows, approved_rows, progress_rows)
        if not options["send"]:
            self.stdout.write(message)
            self.stdout.write(self.style.WARNING("Mode dry-run: gunakan --send untuk mengirim."))
            return
        try:
            result = send_fonnte_message(message)
        except (WhatsAppConfigurationError, RuntimeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Pesan WhatsApp terkirim melalui Fonnte: {result}"))
