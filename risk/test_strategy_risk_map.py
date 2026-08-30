# STRATEGY_RISK_RELATIONSHIP_V4
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from .strategy_risk_map import (
    _support_risk_status,
    _base_relationships,
    _nko_status,
    _risk_status_from_level,
)


class StrategyRiskMapHelperTests(SimpleTestCase):
    def test_risk_level_summary_mapping(self):
        self.assertEqual(_risk_status_from_level("Low")["label"], "Aman")
        self.assertEqual(_risk_status_from_level("Low to Moderate")["label"], "Aman")
        self.assertEqual(_risk_status_from_level("Moderate")["label"], "Perlu Perhatian")
        self.assertEqual(_risk_status_from_level("Moderate to High")["label"], "Tidak Aman")
        self.assertEqual(_risk_status_from_level("High")["label"], "Tidak Aman")
        self.assertEqual(_risk_status_from_level(None)["label"], "Belum Ada Data")

    def test_support_status_distinguishes_missing_report(self):
        self.assertEqual(
            _support_risk_status(None, None)["label"],
            "Belum Ada Laporan",
        )

        self.assertEqual(
            _support_risk_status(object(), None)["label"],
            "Penilaian Belum Diisi",
        )

        self.assertEqual(
            _support_risk_status(object(), "Moderate")["label"],
            "Perlu Perhatian",
        )

    def test_nko_status_mapping(self):
        self.assertEqual(_nko_status("101")["label"], "Tercapai")
        self.assertEqual(_nko_status("97")["label"], "Hampir Tercapai")
        self.assertEqual(_nko_status("94.9")["label"], "Perlu Peningkatan")
        self.assertEqual(_nko_status(None)["label"], "Belum Ada Data")

    def test_base_relationship_exposes_linked_unit_risk(self):
        class NamedObject:
            def __init__(self, pk, name):
                self.pk = pk
                self.name = name

            def __str__(self):
                return self.name

        class RelatedObjects:
            def __init__(self, *items):
                self.items = items

            def all(self):
                return self.items

        unit = NamedObject(7, "UB INFRA")
        unit_summary = SimpleNamespace(
            pk=3,
            judul="Profil Risiko INFRA",
            unit_bisnis=unit,
        )
        unit_risk = SimpleNamespace(
            pk=37,
            summary_id=3,
            summary=unit_summary,
            no_risiko=30,
            no_item=33,
            peristiwa_risiko=(
                "Terjadinya insiden keamanan siber pada sistem IT/OT "
                "yang mengganggu layanan dan berpotensi menyebabkan "
                "kebocoran data."
            ),
        )
        source = SimpleNamespace(reassessment_item=unit_risk)

        corporate = SimpleNamespace(
            pk=11,
            no_risiko=11,
            no_item=11,
            peristiwa_risiko=(
                "Serangan Cyber terhadap IT dan OT yang berdampak "
                "pada operasional Perusahaan"
            ),
            summary=NamedObject(2, "Profil Risiko Korporat 2026"),
            kategori_risiko_id=None,
            get_level_name=lambda mode: "Low",
            sumber_risiko=RelatedObjects(source),
        )

        relationships, summary_ids, units = _base_relationships([corporate])

        self.assertEqual(summary_ids, {3})
        self.assertEqual(units, [{"id": 7, "name": "UB INFRA"}])

        support = relationships[0]["supports"][0]

        self.assertEqual(support["source_count"], 1)
        self.assertEqual(support["risk_event_ids"], {37})
        self.assertEqual(
            support["linked_risks"],
            [
                {
                    "id": 37,
                    "risk_no": 30,
                    "event": (
                        "Terjadinya insiden keamanan siber pada sistem IT/OT "
                        "yang mengganggu layanan dan berpotensi menyebabkan "
                        "kebocoran data."
                    ),
                }
            ],
        )


class StrategyRiskMapPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="strategy-map-user",
            password="test-pass-123",
        )
        self.url = "/strategy-risk-map/"

    def test_requires_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_renders_new_executive_relationship_page(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Executive Risk Relationship Map")
        self.assertContains(response, "Profil Risiko Korporat")
        self.assertContains(response, "Bidang / Unit Bisnis")
        # Empty state tidak mempunyai unit_performance_rows,
        # sehingga tabel ringkasan memang tidak dirender.
        self.assertNotContains(response, "KM (NKO)")
        self.assertNotContains(response, "Arsitektur Integrasi")
