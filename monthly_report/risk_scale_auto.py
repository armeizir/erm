"""Numeric ranges shared by monthly risk forms and model saves."""
from decimal import Decimal


def numeric_levels(impact, probability):
    impact_level = probability_level = None
    if impact is not None:
        value = Decimal(str(impact))
        if value < 0:
            raise ValueError('Nilai dampak tidak boleh negatif.')
        # 33 belongs to level 2; the upper bounds 66, 100, 133 are inclusive.
        impact_level = (1 if value < 33000000000 else
                        2 if value <= 66000000000 else
                        3 if value <= 100000000000 else
                        4 if value <= 133000000000 else 5)
    if probability is not None:
        value = Decimal(str(probability))
        if not 0 <= value <= 100:
            raise ValueError('Probabilitas harus antara 0 dan 100%.')
        probability_level = (1 if value < 20 else 2 if value <= 40 else
                             3 if value <= 60 else 4 if value <= 80 else 5)
    return impact_level, probability_level


def derive_scales(item):
    from django.core.exceptions import ValidationError
    from risk.models import MasterSkalaDampak, MasterSkalaProbabilitas
    fields = ('realisasi_skala_dampak', 'realisasi_skala_probabilitas',
              'realisasi_skor_risiko', 'realisasi_level_risiko_bumn')
    kind = getattr(item.risk_event, 'jenis_risiko', item.jenis_risiko) if item.risk_event_id else item.jenis_risiko
    if kind != 'kuantitatif':
        return set()
    try:
        d, p = numeric_levels(item.realisasi_nilai_dampak, item.realisasi_nilai_probabilitas)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    resolved = []
    for model, level in ((MasterSkalaDampak, d), (MasterSkalaProbabilitas, p)):
        candidates = list(model.objects.filter(aktif=True, urutan=level)[:2]) if level else []
        if level and len(candidates) != 1:
            raise ValidationError('Master skala level %s tidak tersedia atau tidak unik.' % level)
        resolved.append(candidates[0] if candidates else None)
    item.realisasi_skala_dampak, item.realisasi_skala_probabilitas = resolved
    item.realisasi_skor_risiko = None
    item.realisasi_level_risiko_bumn = None
    if all(resolved):
        matrix = item._get_active_matrix()
        cell = matrix.get_cell(*resolved) if matrix else None
        if cell is None:
            raise ValidationError('Sel matriks risiko untuk skala ini belum tersedia.')
        item.realisasi_skor_risiko = cell.skor
        item.realisasi_level_risiko_bumn = cell.level_risiko.nama
    return set(fields)
