from django.contrib import admin
from django import forms

from .models import (
    KontrakManajemen,
    KontrakManajemenBagian,
    KontrakManajemenItem,
    KontrakManajemenTargetPeriode,
)


class KontrakManajemenItemForm(forms.ModelForm):
    class Meta:
        model = KontrakManajemenItem
        fields = "__all__"
        widgets = {
            "formula": forms.Textarea(attrs={"rows": 4}),
        }


@admin.register(KontrakManajemen)
class KontrakManajemenAdmin(admin.ModelAdmin):
    list_display = ("kode", "judul", "tahun_buku", "unit", "versi", "status")
    search_fields = ("kode", "judul", "unit__nama")
    list_filter = ("tahun_buku", "status", "unit")


@admin.register(KontrakManajemenBagian)
class KontrakManajemenBagianAdmin(admin.ModelAdmin):
    list_display = ("kode_bagian", "nama_bagian", "kontrak", "urutan")
    search_fields = ("kode_bagian", "nama_bagian", "kontrak__judul")
    list_filter = ("kontrak",)


@admin.register(KontrakManajemenItem)
class KontrakManajemenItemAdmin(admin.ModelAdmin):
    form = KontrakManajemenItemForm

    list_display = ("no_urut", "indikator", "bagian", "bobot", "satuan", "aktif")
    search_fields = ("no_urut", "indikator", "formula", "satuan")
    list_filter = ("aktif", "arah_pencapaian", "bagian")

    fields = (
        "bagian",
        "no_urut",
        "indikator",
        "formula",
        "satuan",
        "bobot",
        "target_tahunan",
        "target_text",
        "arah_pencapaian",
        "pic_unit",
        "keterangan",
        "aktif",
    )


@admin.register(KontrakManajemenTargetPeriode)
class KontrakManajemenTargetPeriodeAdmin(admin.ModelAdmin):
    list_display = ("km_item", "periode", "target_nilai", "realisasi_nilai", "nilai_capaian")
    list_filter = ("periode",)
    search_fields = ("km_item__indikator", "km_item__no_urut")