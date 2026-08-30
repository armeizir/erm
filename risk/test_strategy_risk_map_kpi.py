from types import SimpleNamespace

from django.test import SimpleTestCase

from risk.strategy_risk_map import _linked_kpis


class FakeManager:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class StrategyRiskMapCorporateKPITests(SimpleTestCase):

    def test_linked_kpis_are_sorted_and_unique(self):
        ikk_4 = SimpleNamespace(
            pk=4,
            no_urut=4,
            indikator_kinerja_kunci=(
                "Reliabilitas Sistem Kelistrikan"
            ),
            esg_kategori="S",
        )

        ikk_2 = SimpleNamespace(
            pk=2,
            no_urut=2,
            indikator_kinerja_kunci=(
                "Efisiensi Biaya dan Konsumsi Energi "
                "Pembangkit Non-MPP"
            ),
            esg_kategori="C",
        )

        corporate = SimpleNamespace(
            kinerja_terkait=FakeManager(
                [
                    SimpleNamespace(item_kinerja=ikk_4),
                    SimpleNamespace(item_kinerja=ikk_2),
                    SimpleNamespace(item_kinerja=ikk_4),
                ]
            )
        )

        rows = _linked_kpis(corporate)

        self.assertEqual(
            [x["no"] for x in rows],
            [2, 4],
        )

        self.assertEqual(
            rows[0]["esg"],
            "C",
        )

        self.assertEqual(
            rows[1]["name"],
            "Reliabilitas Sistem Kelistrikan",
        )
