from django.test import TestCase

from risk.models import RKAPItem


class RKAPStructurePhase1Tests(TestCase):
    def test_new_metadata_defaults_are_backward_compatible(self):
        item = RKAPItem.objects.create(
            tahun=2026,
            kode="TEST-1",
            sasaran="Test RKAP",
        )
        self.assertEqual(item.jenis_rkap, "LAINNYA")
        self.assertEqual(item.tipe_baris, "DATA")
        self.assertEqual(item.polaritas, "NETRAL")

    def test_hierarchy_still_uses_same_rkapitem_model(self):
        parent = RKAPItem.objects.create(
            tahun=2026,
            kode="TEST-P",
            sasaran="Parent",
            jenis_rkap="LABA_RUGI",
            tipe_baris="GROUP",
        )
        child = RKAPItem.objects.create(
            tahun=2026,
            kode="TEST-C",
            sasaran="Child",
            parent=parent,
            jenis_rkap="LABA_RUGI",
            tipe_baris="DATA",
            polaritas="POSITIF",
            target=100,
        )
        self.assertEqual(child.parent_id, parent.id)
        self.assertEqual(parent.children.get().id, child.id)
        self.assertEqual(child.target, 100)
