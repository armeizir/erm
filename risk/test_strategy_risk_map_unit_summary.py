from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from risk.strategy_risk_map import _unit_performance_summary


class StrategyRiskMapUnitSummaryTests(SimpleTestCase):

    def test_aggregates_distinct_linked_risks_per_unit(self):
        summary_a = SimpleNamespace(
            kontrak_manajemen_id=10,
        )
        summary_b = SimpleNamespace(
            kontrak_manajemen_id=10,
        )

        kpmr = {
            "score": Decimal("3.25"),
            "score_display": "3.25",
            "rating": "Good",
            "record_status": "Final",
            "is_provisional": False,
            "quarter": 3,
        }

        nko = {
            "value": Decimal("102.50"),
            "display": "102.5%",
            "status": {
                "key": "green",
                "label": "Tercapai",
            },
            "rkm_status": "Final",
        }

        relationships = [
            {
                "supports": [
                    {
                        "unit_id": 5,
                        "unit": "UB TEST",
                        "summary": summary_a,
                        "risk_event_ids": {1, 2},
                        "kpmr": kpmr,
                        "nko": nko,
                    }
                ]
            },
            {
                "supports": [
                    {
                        "unit_id": 5,
                        "unit": "UB TEST",
                        "summary": summary_b,
                        "risk_event_ids": {2, 3},
                        "kpmr": kpmr,
                        "nko": nko,
                    }
                ]
            },
        ]

        result = _unit_performance_summary(
            relationships
        )

        self.assertEqual(len(result), 1)

        row = result[0]

        self.assertEqual(row["unit"], "UB TEST")

        # Risiko 2 muncul dua kali tetapi hanya dihitung sekali.
        self.assertEqual(row["risk_count"], 3)

        self.assertEqual(
            row["kpmr"]["score"],
            Decimal("3.25"),
        )

        self.assertEqual(
            row["nko"]["value"],
            Decimal("102.50"),
        )

        self.assertEqual(
            row["nko"]["status"]["label"],
            "Tercapai",
        )

    def test_no_nko_returns_belum_ada_data(self):
        summary = SimpleNamespace(
            kontrak_manajemen_id=None,
        )

        relationships = [
            {
                "supports": [
                    {
                        "unit_id": 7,
                        "unit": "BID TEST",
                        "summary": summary,
                        "risk_event_ids": {10},
                        "kpmr": {},
                        "nko": {},
                    }
                ]
            }
        ]

        result = _unit_performance_summary(
            relationships
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["risk_count"], 1)
        self.assertIsNone(
            result[0]["nko"]["value"]
        )
        self.assertEqual(
            result[0]["nko"]["status"]["label"],
            "Belum Ada Data",
        )
