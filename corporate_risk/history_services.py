import calendar
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from masterdata.models import PeriodeLaporan

from .models import MonteCarloMetricHistory


def _next_month(value):
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    return year, month


@transaction.atomic
def duplicate_metric_history_to_next_month(source, user):
    source = MonteCarloMetricHistory.objects.select_for_update().select_related(
        "metric", "periode__tahun_buku"
    ).get(pk=source.pk)
    if source.status == source.STATUS_UNUPDATED:
        raise ValidationError("Data hasil salinan harus diperbarui sebelum membuat bulan berikutnya.")
    if MonteCarloMetricHistory.objects.filter(copied_from=source).exists():
        raise ValidationError("Data bulan berikutnya sudah pernah dibuat.")

    year, month = _next_month(source.tanggal_data)
    if MonteCarloMetricHistory.objects.filter(
        metric=source.metric,
        tanggal_data__year=year,
        tanggal_data__month=month,
    ).exists():
        raise ValidationError("Data histori untuk bulan berikutnya sudah tersedia.")

    tahun_buku = source.periode.tahun_buku
    if tahun_buku.tahun != year:
        from masterdata.models import TahunBuku
        tahun_buku, _ = TahunBuku.objects.get_or_create(tahun=year)
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    month_names = (
        "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember",
    )
    period, _ = PeriodeLaporan.objects.get_or_create(
        tahun_buku=tahun_buku,
        kode_periode=f"{year}-{month:02d}",
        defaults={
            "nama_periode": f"{month_names[month]} {year}",
            "jenis_periode": "bulanan",
            "tanggal_mulai": start,
            "tanggal_selesai": end,
        },
    )
    return MonteCarloMetricHistory.objects.create(
        metric=source.metric,
        periode=period,
        tanggal_data=start,
        metric_value=source.metric_value,
        target_value=source.target_value,
        keterangan=f"Salinan awal dari {source.periode.nama_periode}. Harap perbarui nilai aktual.",
        status=MonteCarloMetricHistory.STATUS_UNUPDATED,
        copied_from=source,
        copied_by=user,
        copied_at=timezone.now(),
        assigned_to=source.assigned_to,
    )
