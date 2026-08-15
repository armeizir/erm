from django.core.management import call_command
from django.test import TestCase
from risk.models import RKAPItem

class RKAPPhase2ImportTests(TestCase):
    def test_dry_run_rolls_back(self):
        before = RKAPItem.objects.count()
        call_command("import_rkap_phase2_2026", "--scope", "lr")
        self.assertEqual(RKAPItem.objects.count(), before)

    def test_apply_creates_key_items(self):
        call_command("import_rkap_phase2_2026", "--scope", "all", "--apply")
        harga = RKAPItem.objects.get(tahun=2026, kode="LR.1.5", sasaran="Harga Jual Rata-rata")
        self.assertEqual(harga.jenis_rkap, "LABA_RUGI")
        self.assertEqual(harga.target, 1640)
        self.assertEqual(harga.satuan, "Rp/kWh")
        self.assertEqual(harga.polaritas, "POSITIF")
        kurs = RKAPItem.objects.get(tahun=2026, kode="TGT.POSTUR.01", sasaran="Kurs USD")
        self.assertEqual(kurs.target, 16500)

    def test_existing_legacy_item_is_not_overwritten(self):
        legacy = RKAPItem.objects.create(
            id=47, tahun=2026, kode="3.1.3",
            sasaran="Pendapatan Penjualan Tenaga Listrik Batam",
            jenis_rkap="TARGET", tipe_baris="DATA",
            target=7951210, satuan="Rp Jt",
        )
        call_command("import_rkap_phase2_2026", "--scope", "all", "--apply")
        legacy.refresh_from_db()
        self.assertEqual(legacy.id, 47)
        self.assertEqual(legacy.kode, "3.1.3")
        self.assertEqual(legacy.target, 7951210)
