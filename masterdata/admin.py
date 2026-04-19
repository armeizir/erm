from django.contrib import admin

from .models import TahunBuku, PeriodeLaporan
from masterdata.models import TahunBuku, PeriodeLaporan


@admin.register(TahunBuku)
class TahunBukuAdmin(admin.ModelAdmin):
    list_display = ("tahun", "aktif")
    list_filter = ("aktif",)
    ordering = ("-tahun",)

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        try:
            if search_term:
                queryset |= self.model.objects.filter(tahun=int(search_term))
        except ValueError:
            pass
        return queryset, use_distinct


@admin.register(PeriodeLaporan)
class PeriodeLaporanAdmin(admin.ModelAdmin):
    list_display = (
        "nama_periode",
        "tahun_buku",
        "kode_periode",
        "jenis_periode",
        "tanggal_mulai",
        "tanggal_selesai",
        "is_locked",
    )
    list_filter = ("jenis_periode", "tahun_buku", "is_locked")
    search_fields = ("nama_periode", "kode_periode", "tahun_buku__tahun")
    ordering = ("tahun_buku__tahun", "tanggal_mulai")