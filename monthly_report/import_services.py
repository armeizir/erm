import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

import httpx
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from risk.models import AppSetting, MasterSkalaDampak, MasterSkalaProbabilitas

from .models import (
    MonthlyRiskReportImportBatch,
    MonthlyRiskReportImportRow,
    MonthlyRiskReportSubmissionLog,
)
from .services import refresh_monthly_report_summary


IMPORTABLE_FIELDS = (
    "realisasi_asumsi_dampak",
    "realisasi_nilai_dampak",
    "realisasi_skala_dampak_id",
    "realisasi_nilai_probabilitas",
    "realisasi_skala_probabilitas_id",
    "efektivitas_perlakuan_risiko",
    "realisasi_rencana_perlakuan",
    "realisasi_output_perlakuan",
    "realisasi_biaya_perlakuan",
    "realisasi_pic",
    "status_rencana_perlakuan",
    "penjelasan_status_rencana",
    "progress_pelaksanaan_percent",
    "realisasi_threshold_kri",
    "realisasi_threshold_kri_skor",
)


def file_sha256(uploaded_file):
    digest = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    uploaded_file.seek(0)
    return digest.hexdigest()


def _text(value):
    return str(value or "").strip()


def _normalize(value):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", _text(value).lower())).strip()


def _decimal(value):
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Rp", "").replace(" ", "")
    if text.endswith("%"):
        text = text[:-1]
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        text = "".join(parts) if len(parts[-1]) == 3 else text.replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _percent(value):
    number = _decimal(value)
    if number is None:
        return None
    if 0 < number <= 1:
        number *= 100
    return number


def _risk_identity(code):
    text = _text(code)
    match = re.search(r"(?:^|[-\s])(\d+)[-\s]*([A-Za-z]+)\s*$", text)
    if not match:
        return None, ""
    return int(match.group(1)), match.group(2).lower()


def _scale_id(model, value):
    if value in (None, ""):
        return None
    number = _decimal(value)
    if number is not None:
        candidate = model.objects.filter(urutan=int(number), aktif=True).first()
        if candidate:
            return candidate.pk
    normalized = _normalize(value)
    for scale in model.objects.filter(aktif=True):
        if normalized in {_normalize(scale.nama), _normalize(getattr(scale, "label", ""))}:
            return scale.pk
    return None


def _effectiveness(value):
    normalized = _normalize(value)
    if "tidak" in normalized:
        return "tidak_efektif"
    if "cukup" in normalized:
        return "cukup_efektif"
    if "efektif" in normalized:
        return "efektif"
    return None


def _treatment_status(value):
    normalized = _normalize(value)
    if any(token in normalized for token in ("discontinue", "dihentikan", "stop")):
        return "discontinue"
    if any(token in normalized for token in ("continue", "dilanjut", "lanjut")):
        return "continue"
    return None


def _json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    return value


def _parse_workbook(batch):
    batch.source_file.open("rb")
    workbook = load_workbook(batch.source_file, data_only=True, read_only=True)
    if "III.A" not in workbook.sheetnames or "III.B" not in workbook.sheetnames:
        raise ValidationError("File harus memiliki sheet III.A dan III.B sesuai template laporan ERM.")

    month = batch.report.periode.tanggal_mulai.month
    quarter = ((month - 1) // 3) + 1
    # Template historis antar-unit memiliki beberapa pergeseran kolom. Kandidat
    # dipilih per baris berdasarkan pasangan skala yang benar-benar dikenali.
    iiia_schemas = (
        (11 + quarter, 15 + quarter, 23 + quarter, 27 + quarter, 56, 11),  # BIS
        (13 + quarter, 17 + quarter, 21 + quarter, 25 + quarter, 46, 13),  # umum
        (13 + quarter, 17 + quarter, 25 + quarter, 29 + quarter, 58, 13),  # RENKIN
        (11 + quarter, 15 + quarter, 19 + quarter, 23 + quarter, 40, 11),  # legacy
    )
    entries = {}
    for row_number, row in enumerate(
        workbook["III.A"].iter_rows(min_row=10, values_only=True), start=10
    ):
        row = list(row)
        code = row[1] if len(row) > 1 else None
        event = row[2] if len(row) > 2 else None
        no_risiko, cause = _risk_identity(code)
        if not any((code, event)):
            continue
        key = (no_risiko or _normalize(code), cause or _normalize(event))
        def schema_score(schema):
            _, dampak_scale, _, prob_scale, _, _ = schema
            return int(bool(len(row) > dampak_scale and _scale_id(MasterSkalaDampak, row[dampak_scale]))) + int(
                bool(len(row) > prob_scale and _scale_id(MasterSkalaProbabilitas, row[prob_scale]))
            )
        nilai_dampak, skala_dampak, nilai_prob, skala_prob, efektivitas, asumsi = max(
            iiia_schemas, key=schema_score
        )
        entries[key] = {
            "source_reference": f"III.A:{row_number}",
            "risk_code": _text(code),
            "risk_event_text": _text(event),
            "no_risiko": no_risiko,
            "cause": cause,
            "raw_data": {"iiia_row": row_number},
            "proposed_data": {
                "realisasi_asumsi_dampak": _text(row[asumsi] if len(row) > asumsi else None),
                "realisasi_nilai_dampak": _decimal(row[nilai_dampak])
                if len(row) > nilai_dampak else None,
                "realisasi_skala_dampak_id": _scale_id(
                    MasterSkalaDampak,
                    row[skala_dampak] if len(row) > skala_dampak else None,
                ),
                "realisasi_nilai_probabilitas": _percent(row[nilai_prob])
                if len(row) > nilai_prob else None,
                "realisasi_skala_probabilitas_id": _scale_id(
                    MasterSkalaProbabilitas,
                    row[skala_prob] if len(row) > skala_prob else None,
                ),
                "efektivitas_perlakuan_risiko": _effectiveness(
                    row[efektivitas] if len(row) > efektivitas else None
                ),
            },
        }

    progress_col = {1: 30, 2: 31, 3: 32, 4: 33}[quarter] - 1
    threshold_col = 39 + ((month - 1) * 2) - 1
    for row_number, row in enumerate(
        workbook["III.B"].iter_rows(min_row=10, values_only=True), start=10
    ):
        row = list(row)
        code = (row[5] if len(row) > 5 else None) or (row[1] if len(row) > 1 else None)
        no_risiko, cause = _risk_identity(code)
        event = row[2] if len(row) > 2 else None
        if code in (None, "") and event in (None, ""):
            continue
        key = (no_risiko or _normalize(code), cause or _normalize(event))
        entry = entries.setdefault(
            key,
            {
                "source_reference": f"III.B:{row_number}",
                "risk_code": _text(code),
                "risk_event_text": _text(event),
                "no_risiko": no_risiko,
                "cause": cause,
                "raw_data": {},
                "proposed_data": {},
            },
        )
        entry["source_reference"] += f"|III.B:{row_number}"
        entry["raw_data"]["iiib_row"] = row_number
        entry["proposed_data"].update(
            {
                "realisasi_rencana_perlakuan": _text(row[10] if len(row) > 10 else None),
                "realisasi_output_perlakuan": _text(row[11] if len(row) > 11 else None),
                "realisasi_biaya_perlakuan": _decimal(row[12] if len(row) > 12 else None),
                "realisasi_pic": _text(row[14] if len(row) > 14 else None),
                "status_rencana_perlakuan": _treatment_status(row[27] if len(row) > 27 else None),
                "penjelasan_status_rencana": _text(row[28] if len(row) > 28 else None),
                "progress_pelaksanaan_percent": _percent(row[progress_col])
                if len(row) > progress_col else None,
                "realisasi_threshold_kri": _text(row[threshold_col])
                if len(row) > threshold_col else "",
                "realisasi_threshold_kri_skor": _text(row[threshold_col + 1])
                if len(row) > threshold_col + 1 else "",
            }
        )
    return list(entries.values())


def _match_item(report, entry):
    items = list(report.items.select_related("risk_event"))
    exact = [
        item for item in items
        if entry["no_risiko"] is not None
        and item.risk_event.no_risiko == entry["no_risiko"]
        and _normalize(item.risk_event.no_penyebab_risiko) == _normalize(entry["cause"])
    ]
    if len(exact) == 1:
        return exact[0], "code", Decimal("100")

    source_event = _normalize(entry["risk_event_text"])
    scored = sorted(
        [
            (
            SequenceMatcher(None, source_event, _normalize(item.risk_event.peristiwa_risiko)).ratio(),
            item,
            )
            for item in items
        ],
        key=lambda candidate: candidate[0],
    )
    if scored and scored[-1][0] >= 0.60:
        score, item = scored[-1]
        return item, "event_similarity", Decimal(str(round(score * 100, 2)))
    return None, "unmatched", Decimal("0")


def _validate_entry(entry, item, confidence):
    issues = []
    proposed = entry["proposed_data"]
    probability = proposed.get("realisasi_nilai_probabilitas")
    progress = proposed.get("progress_pelaksanaan_percent")
    if probability is not None and not 0 <= probability <= 100:
        issues.append("Nilai probabilitas harus berada antara 0 dan 100%.")
    if progress is not None and not 0 <= progress <= 100:
        issues.append("Progress pelaksanaan harus berada antara 0 dan 100%.")
    if proposed.get("realisasi_biaya_perlakuan") is not None and proposed["realisasi_biaya_perlakuan"] < 0:
        issues.append("Realisasi biaya tidak boleh negatif.")
    if not item:
        issues.append("Risiko pada Excel belum dapat dicocokkan dengan item laporan ERM.")
    if issues:
        return MonthlyRiskReportImportRow.LEVEL_RED, issues
    if confidence < 100:
        issues.append(f"Pencocokan berdasarkan kemiripan teks ({confidence}%).")
        return MonthlyRiskReportImportRow.LEVEL_YELLOW, issues
    return MonthlyRiskReportImportRow.LEVEL_GREEN, issues


def _extract_json(text):
    cleaned = (text or "").strip().strip("`")
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)


def _run_ai_review(batch, rows):
    setting = AppSetting.get_solo()
    if not setting.ai_aktif or not setting.runtime_ai_api_key:
        return False, "AI tidak aktif; analisis deterministik digunakan."
    ambiguous = [row for row in rows if row.validation_level != row.LEVEL_GREEN]
    if not ambiguous:
        return False, "Semua baris cocok secara deterministik; AI tidak diperlukan."
    payload = [
        {
            "row_id": row.pk,
            "risk_code": row.risk_code,
            "risk_event": row.risk_event_text,
            "matched_item_id": row.matched_report_item_id,
            "confidence": float(row.confidence),
            "issues": row.issues,
        }
        for row in ambiguous[:100]
    ]
    prompt = (
        "Anda adalah analis ERM PLN Batam. Tinjau hasil validasi import berikut tanpa "
        "menciptakan fakta baru. Kembalikan JSON valid: {summary:string, rows:[{row_id:int," 
        "analysis:string}]}. Jelaskan singkat hal yang perlu dikonfirmasi user. Data: "
        + json.dumps(payload, ensure_ascii=False)
    )
    try:
        if setting.ai_provider == AppSetting.AI_PROVIDER_GEMINI:
            base = (setting.ai_base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
            if "api.openai.com" in base:
                base = "https://generativelanguage.googleapis.com/v1beta"
            model = setting.ai_model if not setting.ai_model.startswith("gpt-") else "gemini-3.1-flash-lite"
            response = httpx.post(
                f"{base}/models/{model}:generateContent",
                headers={"x-goog-api-key": setting.runtime_ai_api_key},
                json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            base = (setting.ai_base_url or "https://api.openai.com/v1").rstrip("/")
            response = httpx.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {setting.runtime_ai_api_key}"},
                json={"model": setting.ai_model or "gpt-4.1-mini", "temperature": float(setting.ai_temperature), "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}},
                timeout=30,
            )
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"]
        result = _extract_json(text)
        by_id = {row.pk: row for row in ambiguous}
        for ai_row in result.get("rows", []):
            row = by_id.get(ai_row.get("row_id"))
            if row:
                row.ai_analysis = _text(ai_row.get("analysis"))
                row.save(update_fields=["ai_analysis", "updated_at"])
        return True, _text(result.get("summary")) or "Analisis AI selesai."
    except Exception as exc:
        return False, f"AI tidak tersedia ({exc}); analisis deterministik tetap dapat direview."


@transaction.atomic
def analyze_import_batch(batch):
    if batch.report.status not in {"draft", "revision"}:
        raise ValidationError("Import hanya dapat dilakukan pada laporan Draft atau Revision.")
    batch.rows.all().delete()
    entries = _parse_workbook(batch)
    if not entries:
        raise ValidationError("Tidak ditemukan baris risiko valid pada sheet III.A/III.B.")
    rows = []
    for entry in entries:
        item, method, confidence = _match_item(batch.report, entry)
        level, issues = _validate_entry(entry, item, confidence)
        proposed = {
            key: _json_value(value)
            for key, value in entry["proposed_data"].items()
            if value not in (None, "")
        }
        rows.append(
            MonthlyRiskReportImportRow.objects.create(
                batch=batch,
                source_reference=entry["source_reference"],
                risk_code=entry["risk_code"],
                risk_event_text=entry["risk_event_text"],
                matched_report_item=item,
                match_method=method,
                confidence=confidence,
                validation_level=level,
                issues=issues,
                raw_data=entry["raw_data"],
                proposed_data=proposed,
                user_decision="import" if level == "green" else "pending",
            )
        )
    ai_used, ai_summary = _run_ai_review(batch, rows)
    batch.status = batch.STATUS_REVIEW
    batch.ai_used = ai_used
    batch.ai_summary = ai_summary
    batch.analyzed_at = timezone.now()
    batch.error_message = ""
    batch.save(update_fields=["status", "ai_used", "ai_summary", "analyzed_at", "error_message", "updated_at"])
    return batch


def _field_value(item, field_name):
    value = getattr(item, field_name)
    return _json_value(value)


@transaction.atomic
def apply_import_batch(batch, user):
    batch = MonthlyRiskReportImportBatch.objects.select_for_update().select_related("report").get(pk=batch.pk)
    if batch.status != batch.STATUS_REVIEW:
        raise ValidationError("Batch import ini tidak lagi menunggu konfirmasi.")
    if batch.report.status not in {"draft", "revision"}:
        raise ValidationError("Laporan bukan lagi Draft/Revision sehingga import dibatalkan.")
    rows = list(batch.rows.select_related("matched_report_item"))
    unresolved = [
        row for row in rows
        if row.validation_level in {row.LEVEL_YELLOW, row.LEVEL_RED}
        and row.user_decision == row.DECISION_PENDING
    ]
    if unresolved:
        raise ValidationError("Masih ada baris kuning/merah yang belum dikonfirmasi.")
    for row in rows:
        if row.user_decision == row.DECISION_SKIP:
            continue
        if row.validation_level == row.LEVEL_RED or not row.matched_report_item_id:
            raise ValidationError(f"{row.source_reference} berstatus merah dan tidak dapat diimpor.")
        item = row.matched_report_item
        previous = {}
        applied = {}
        for field_name, raw_value in row.proposed_data.items():
            if field_name not in IMPORTABLE_FIELDS:
                continue
            previous[field_name] = _field_value(item, field_name)
            model_field = field_name[:-3] if field_name.endswith("_id") else field_name
            field = item._meta.get_field(model_field)
            value = raw_value
            if field.get_internal_type() == "DecimalField" and raw_value not in (None, ""):
                value = Decimal(str(raw_value))
            setattr(item, field_name, value)
            applied[field_name] = _json_value(value)
        item.full_clean()
        item.save()
        row.previous_data = previous
        row.applied_data = applied
        row.save(update_fields=["previous_data", "applied_data", "updated_at"])
    refresh_monthly_report_summary(batch.report)
    batch.status = batch.STATUS_IMPORTED
    batch.imported_by = user
    batch.imported_at = timezone.now()
    batch.save(update_fields=["status", "imported_by", "imported_at", "updated_at"])
    MonthlyRiskReportSubmissionLog.objects.create(
        report=batch.report,
        action="import",
        action_by=user,
        note=f"Import Excel {batch.original_filename}; batch ID {batch.pk}.",
    )
    return batch
