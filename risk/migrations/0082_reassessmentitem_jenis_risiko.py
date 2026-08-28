from django.db import migrations, models


def _norm(value):
    return " ".join(str(value or "").split()).casefold()


def _type_from_category(value):
    label = _norm(value)
    if "kual" in label:
        return "kualitatif"
    if "kuant" in label:
        return "kuantitatif"
    return None


def classify_legacy_risk_types(apps, schema_editor):
    ReAssessmentItem = apps.get_model("risk", "ReAssessmentItem")

    # 1) Kategori Dampak adalah bukti utama.
    rows = list(
        ReAssessmentItem.objects.select_related("kategori_dampak")
        .all()
        .values(
            "id",
            "summary_id",
            "peristiwa_risiko",
            "kategori_dampak__nama",
        )
    )

    direct = {}
    for row in rows:
        risk_type = _type_from_category(row["kategori_dampak__nama"])
        if risk_type:
            direct[row["id"]] = risk_type

    for pk, risk_type in direct.items():
        ReAssessmentItem.objects.filter(pk=pk).update(jenis_risiko=risk_type)

    # 2) Kategori Dampak kosong hanya diinfer jika peer pada profil yang sama
    # + peristiwa risiko yang sama mempunyai SATU jenis yang konsisten.
    # Peer campuran / tanpa bukti tetap NULL (unresolved), bukan dipaksa kuantitatif.
    peer_types = {}
    for row in rows:
        risk_type = _type_from_category(row["kategori_dampak__nama"])
        if not risk_type:
            continue
        key = (row["summary_id"], _norm(row["peristiwa_risiko"]))
        peer_types.setdefault(key, set()).add(risk_type)

    for row in rows:
        if row["id"] in direct:
            continue
        key = (row["summary_id"], _norm(row["peristiwa_risiko"]))
        types = peer_types.get(key, set())
        if len(types) == 1:
            ReAssessmentItem.objects.filter(pk=row["id"]).update(
                jenis_risiko=next(iter(types))
            )


def reverse_classification(apps, schema_editor):
    # Klasifikasi legacy tidak direkonstruksi pada rollback.
    pass


class Migration(migrations.Migration):

    dependencies = [
        (
            "risk",
            "0081_remove_reassessmentitem_unik_reassessment_item_risiko_per_summary_and_more",
        ),
    ]

    operations = [
        # Tambah sebagai nullable tanpa default agar legacy unknown tidak otomatis
        # menjadi Kuantitatif.
        migrations.AddField(
            model_name="reassessmentitem",
            name="jenis_risiko",
            field=models.CharField(
                blank=True,
                choices=[
                    ("kuantitatif", "Kuantitatif"),
                    ("kualitatif", "Kualitatif"),
                ],
                default=None,
                help_text=(
                    "Kuantitatif: eksposur dihitung otomatis dari Nilai Dampak × "
                    "Nilai Probabilitas. Kualitatif: nilai dampak/probabilitas "
                    "numerik tidak wajib dan Nilai Eksposur Risiko diisi langsung."
                ),
                max_length=20,
                null=True,
                verbose_name="Jenis Risiko",
            ),
        ),
        migrations.RunPython(classify_legacy_risk_types, reverse_classification),
        # Objek baru tetap default Kuantitatif, tetapi legacy unresolved yang telah
        # menjadi NULL tetap NULL.
        migrations.AlterField(
            model_name="reassessmentitem",
            name="jenis_risiko",
            field=models.CharField(
                blank=True,
                choices=[
                    ("kuantitatif", "Kuantitatif"),
                    ("kualitatif", "Kualitatif"),
                ],
                default="kuantitatif",
                help_text=(
                    "Kuantitatif: eksposur dihitung otomatis dari Nilai Dampak × "
                    "Nilai Probabilitas. Kualitatif: nilai dampak/probabilitas "
                    "numerik tidak wajib dan Nilai Eksposur Risiko diisi langsung. "
                    "Data legacy yang belum terklasifikasi harus ditetapkan "
                    "Jenis Risikonya saat diedit."
                ),
                max_length=20,
                null=True,
                verbose_name="Jenis Risiko",
            ),
        ),
    ]
