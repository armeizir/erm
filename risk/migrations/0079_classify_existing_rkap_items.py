from django.db import migrations


def classify_existing_rkap(apps, schema_editor):
    RKAPItem = apps.get_model("risk", "RKAPItem")

    for item in RKAPItem.objects.all().iterator():
        source = (item.sumber_dokumen or "").lower()
        subkategori = (item.subkategori or "").lower()
        kategori = (item.kategori or "").strip().lower()
        kode = (item.kode or "").strip()
        sasaran = (item.sasaran or "").strip()

        updates = {}

        if "neraca non isak" in source or "neraca non isak" in subkategori:
            updates["jenis_rkap"] = "NERACA"
            if kategori == "header":
                updates["tipe_baris"] = "GROUP"
            elif kategori == "total" or kode.endswith(".T") or kode in {"A.T", "E.K.T"}:
                updates["tipe_baris"] = "SUBTOTAL"
            else:
                updates["tipe_baris"] = "DATA"

        elif (
            item.tahun == 2026
            and kode == "3.1.3"
            and sasaran.casefold() == "pendapatan penjualan tenaga listrik batam".casefold()
        ):
            updates["jenis_rkap"] = "TARGET"
            updates["tipe_baris"] = "DATA"

        if updates:
            RKAPItem.objects.filter(pk=item.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ("risk", "0078_add_rkap_structure_metadata"),
    ]

    operations = [
        migrations.RunPython(
            classify_existing_rkap,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
