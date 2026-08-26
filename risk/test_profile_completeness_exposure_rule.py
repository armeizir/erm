from types import SimpleNamespace

from django.test import SimpleTestCase

from risk.services.profile_completeness import (
    check_profile_completeness,
)


class _ItemManager:
    def __init__(self, items):
        self.items = items

    def all(self):
        return list(self.items)

    def filter(self, **kwargs):
        result = list(self.items)

        for key, expected in kwargs.items():
            result = [
                item
                for item in result
                if getattr(item, key, None) == expected
            ]

        return result


def _item(category):
    values = dict(
        pk=1,
        is_active=True,
        summary_id=1,
        unit_bisnis_id=1,
        no_item=1,
        no_risiko=1,
        peristiwa_risiko="Peristiwa Risiko Test",
        taksonomi_t3_id=1,
        sasaran_kbumn_id=1,
        kategori_risiko_id=1,
        kategori_dampak=category,

        nilai_dampak=None,
        nilai_probabilitas=None,
        skala_probabilitas_id=1,

        penyebab_risiko="Penyebab test",
        rencana_perlakuan_risiko="Mitigasi test",

        key_risk_indicators=None,
        unit_satuan_kri=None,
        threshold_aman=None,
        threshold_hati_hati=None,
        threshold_bahaya=None,
        kri_threshold_direction=None,
    )

    for q in range(1, 5):
        values.update({
            f"nilai_dampak_q{q}": None,
            f"skala_dampak_q{q}_id": 1,
            f"nilai_probabilitas_q{q}": None,
            f"skala_probabilitas_q{q}_id": 1,
            f"eksposur_risiko_q{q}": None,
            f"skala_risiko_q{q}": "1",
            f"level_nilai_risiko_q{q}": "Low",
        })

    return SimpleNamespace(**values)


def _profile(item):
    return SimpleNamespace(
        pk=1,
        judul="Profil Test",
        tahun=2026,
        unit_bisnis_id=1,
        kontrak_manajemen_id=None,
        risk_matrix_id=None,
        rkm_id=None,
        item=_ItemManager([item]),
    )


class DerivedExposureCompletenessTests(SimpleTestCase):

    def _messages(self, category):
        result = check_profile_completeness(
            _profile(_item(category))
        )
        return [x.message for x in result.findings]

    def test_qualitative_does_not_require_numeric_or_exposure(self):
        messages = self._messages("Dampak Kualilatif")

        self.assertFalse(
            any("Target Eksposur" in x for x in messages)
        )
        self.assertFalse(
            any("Nilai Dampak Q" in x for x in messages)
        )
        self.assertFalse(
            any("Nilai Probabilitas Q" in x for x in messages)
        )

    def test_quantitative_requires_components_but_not_exposure(self):
        messages = self._messages("Dampak Kuantitatif")

        self.assertTrue(
            any("Nilai Dampak Q1" in x for x in messages)
        )
        self.assertTrue(
            any("Nilai Probabilitas Q1" in x for x in messages)
        )
        self.assertFalse(
            any("Target Eksposur" in x for x in messages)
        )
