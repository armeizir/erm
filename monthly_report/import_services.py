import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

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
IMPORT_PARSER_VERSION = 2
FIELD_LABELS = {
    "realisasi_asumsi_dampak": "Asumsi perhitungan dampak",
    "realisasi_nilai_dampak": "Nilai dampak",
    "realisasi_skala_dampak_id": "Skala dampak",
    "realisasi_nilai_probabilitas": "Nilai probabilitas",
    "realisasi_skala_probabilitas_id": "Skala probabilitas",
    "efektivitas_perlakuan_risiko": "Efektivitas perlakuan",
    "realisasi_rencana_perlakuan": "Realisasi rencana",
    "realisasi_output_perlakuan": "Realisasi output",
    "realisasi_biaya_perlakuan": "Realisasi biaya",
    "realisasi_pic": "PIC",
    "status_rencana_perlakuan": "Status rencana",
    "penjelasan_status_rencana": "Penjelasan status",
    "progress_pelaksanaan_percent": "Progress",
    "realisasi_threshold_kri": "Nilai KRI",
    "realisasi_threshold_kri_skor": "Threshold KRI",
}


def file_sha256(uploaded_file):
    digest = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    uploaded_file.seek(0)
    return digest.hexdigest()


def _text(value):
    return str(value or "").strip()


def _safe_import_text(value):
    text = _text(value)
    if text.startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


def _normalize(value):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", _text(value).lower())).strip()


def normalize_treatment_code(value):
    return re.sub(r"[\s-]+", "", _text(value)).upper()


def _positive_integer(value):
    if isinstance(value, bool):
        return None
    number = _decimal(value)
    if number is None or number <= 0 or number != number.to_integral_value():
        return None
    return int(number)


def find_start_row(worksheet):
    for row_number, row in enumerate(worksheet.iter_rows(values_only=True), start=1):
        if any(_text(value).casefold() == "start pengisian" for value in row):
            return row_number
    raise ValidationError(
        f"Anchor 'Start pengisian' tidak ditemukan pada sheet {worksheet.title}."
    )


def iter_data_rows_after_anchor(worksheet):
    start_row = find_start_row(worksheet)
    for row_number, row in enumerate(
        worksheet.iter_rows(min_row=start_row + 1, values_only=True),
        start=start_row + 1,
    ):
        yield row_number, list(row)


def is_valid_risk_row(row):
    return bool(
        _positive_integer(row[1] if len(row) > 1 else None)
        and _text(row[2] if len(row) > 2 else None)
    )


def is_valid_treatment_row(row):
    number = _positive_integer(row[1] if len(row) > 1 else None)
    code = (row[5] if len(row) > 5 else None) or (
        row[1] if len(row) > 1 else None
    )
    event = row[2] if len(row) > 2 else None
    treatment = row[10] if len(row) > 10 else None
    return bool(number and _text(code) and (_text(event) or _text(treatment)))


def target_item_fingerprint(report):
    payload = "|".join(
        f"{pk}:{risk_id}:{number}:{cause}:{updated.isoformat()}"
        for pk, risk_id, number, cause, updated in report.items.order_by("pk").values_list(
            "pk",
            "risk_event_id",
            "risk_event__no_risiko",
            "risk_event__no_penyebab_risiko",
            "updated_at",
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def batch_analysis_is_current(batch):
    return (
        batch.parser_version == IMPORT_PARSER_VERSION
        and batch.target_fingerprint == target_item_fingerprint(batch.report)
    )


def build_display_changes(row):
    changes = []
    item = row.matched_report_item
    for field_name, after in row.proposed_data.items():
        if field_name not in IMPORTABLE_FIELDS:
            continue
        before = _field_value(item, field_name) if item else None
        changes.append(
            {
                "label": FIELD_LABELS.get(field_name, field_name),
                "before": "-" if before in (None, "") else before,
                "after": "-" if after in (None, "") else after,
            }
        )
    return changes


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
    entries = []
    for row_number, row in iter_data_rows_after_anchor(workbook["III.A"]):
        if not is_valid_risk_row(row):
            continue
        code = row[1]
        event = row[2] if len(row) > 2 else None
        no_risiko = _positive_integer(code)
        def schema_score(schema):
            _, dampak_scale, _, prob_scale, _, _ = schema
            return int(bool(len(row) > dampak_scale and _scale_id(MasterSkalaDampak, row[dampak_scale]))) + int(
                bool(len(row) > prob_scale and _scale_id(MasterSkalaProbabilitas, row[prob_scale]))
            )
        nilai_dampak, skala_dampak, nilai_prob, skala_prob, efektivitas, asumsi = max(
            iiia_schemas, key=schema_score
        )
        entries.append({
            "source_reference": f"III.A:{row_number}",
            "source_sheet": "III.A",
            "source_row": row_number,
            "risk_code": _text(code),
            "risk_event_text": _text(event),
            "no_risiko": no_risiko,
            "cause": "",
            "normalized_code": "",
            "raw_data": {"source_sheet": "III.A", "source_row": row_number},
            "proposed_data": {
                "realisasi_asumsi_dampak": _safe_import_text(
                    row[asumsi] if len(row) > asumsi else None
                ),
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
        })
    if not entries:
        raise ValidationError(
            "Tidak ada data risiko valid setelah anchor pada sheet III.A."
        )

    progress_col = {1: 30, 2: 31, 3: 32, 4: 33}[quarter] - 1
    threshold_col = 39 + ((month - 1) * 2) - 1
    treatment_start = len(entries)
    for row_number, row in iter_data_rows_after_anchor(workbook["III.B"]):
        if not is_valid_treatment_row(row):
            continue
        code = (row[5] if len(row) > 5 else None) or (row[1] if len(row) > 1 else None)
        no_risiko = _positive_integer(row[1] if len(row) > 1 else None)
        code_number, cause = _risk_identity(code)
        no_risiko = no_risiko or code_number
        event = row[2] if len(row) > 2 else None
        entries.append({
            "source_reference": f"III.B:{row_number}",
            "source_sheet": "III.B",
            "source_row": row_number,
            "risk_code": _text(code),
            "risk_event_text": _text(event),
            "no_risiko": no_risiko,
            "cause": cause,
            "normalized_code": normalize_treatment_code(code),
            "raw_data": {
                "source_sheet": "III.B",
                "source_row": row_number,
                "normalized_treatment_code": normalize_treatment_code(code),
            },
            "proposed_data": {
                "realisasi_rencana_perlakuan": _safe_import_text(
                    row[10] if len(row) > 10 else None
                ),
                "realisasi_output_perlakuan": _safe_import_text(
                    row[11] if len(row) > 11 else None
                ),
                "realisasi_biaya_perlakuan": _decimal(row[12] if len(row) > 12 else None),
                "realisasi_pic": _safe_import_text(
                    row[14] if len(row) > 14 else None
                ),
                "status_rencana_perlakuan": _treatment_status(row[27] if len(row) > 27 else None),
                "penjelasan_status_rencana": _safe_import_text(
                    row[28] if len(row) > 28 else None
                ),
                "progress_pelaksanaan_percent": _percent(row[progress_col])
                if len(row) > progress_col else None,
                "realisasi_threshold_kri": _safe_import_text(row[threshold_col])
                if len(row) > threshold_col else "",
                "realisasi_threshold_kri_skor": _safe_import_text(
                    row[threshold_col + 1]
                )
                if len(row) > threshold_col + 1 else "",
            },
        })
    if len(entries) == treatment_start:
        raise ValidationError(
            "Tidak ada data rencana perlakuan valid setelah anchor pada sheet III.B."
        )
    return entries


def _match_item(report, entry):
    items = list(report.items.select_related("risk_event"))
    if not items:
        return None, "target_report_empty", Decimal("0"), []
    same_number = [
        item
        for item in items
        if entry["no_risiko"] is not None
        and item.risk_event.no_risiko == entry["no_risiko"]
    ]
    normalized_code = entry.get("normalized_code")
    if normalized_code:
        exact_code = [
            item
            for item in same_number
            if normalize_treatment_code(
                f"SPI{item.risk_event.no_risiko}"
                f"{item.risk_event.no_penyebab_risiko or ''}"
            ) == normalized_code
            or normalize_treatment_code(
                f"{item.risk_event.no_risiko}"
                f"{item.risk_event.no_penyebab_risiko or ''}"
            ) == normalized_code
            or normalize_treatment_code(item.risk_event.no_penyebab_risiko)
            == normalized_code
            or normalize_treatment_code(item.risk_event.no_penyebab_risiko)
            == normalize_treatment_code(entry["cause"])
        ]
        if len(exact_code) == 1:
            return exact_code[0], "exact_risk_number_and_code", Decimal("100"), []
    if len(same_number) == 1:
        item = same_number[0]
        return item, "exact_risk_number", Decimal("100"), []
    if len(same_number) > 1 and entry.get("source_sheet") == "III.A":
        return (
            same_number[0],
            "exact_risk_number_primary",
            Decimal("100"),
            [item.pk for item in same_number[1:]],
        )
    source_event = _normalize(entry["risk_event_text"])
    same_name = [
        item
        for item in items
        if source_event
        and _normalize(item.risk_event.peristiwa_risiko) == source_event
    ]
    if len(same_name) == 1:
        return same_name[0], "unique_normalized_name", Decimal("85"), []
    if len(same_number) > 1 or len(same_name) > 1:
        candidates = sorted({item.pk for item in same_number + same_name})
        return None, "ambiguous", Decimal("0"), candidates
    return None, "unmatched", Decimal("0"), []


def _validate_entry(entry, item, method, confidence, candidates):
    issues = []
    fatal = False
    proposed = entry["proposed_data"]
    probability = proposed.get("realisasi_nilai_probabilitas")
    progress = proposed.get("progress_pelaksanaan_percent")
    if probability is not None and not 0 <= probability <= 100:
        issues.append("Nilai probabilitas harus berada antara 0 dan 100%.")
        fatal = True
    if progress is not None and not 0 <= progress <= 100:
        issues.append("Progress pelaksanaan harus berada antara 0 dan 100%.")
        fatal = True
    if proposed.get("realisasi_biaya_perlakuan") is not None and proposed["realisasi_biaya_perlakuan"] < 0:
        issues.append("Realisasi biaya tidak boleh negatif.")
        fatal = True
    if not item:
        if method == "ambiguous":
            issues.append(
                "Pencocokan ambigu; kandidat target: "
                + ", ".join(str(value) for value in candidates)
                + "."
            )
        else:
            issues.append("Risiko pada Excel belum dapat dicocokkan dengan item laporan ERM.")
        fatal = True
    elif entry["risk_event_text"] and _normalize(entry["risk_event_text"]) != _normalize(
        item.risk_event.peristiwa_risiko
    ):
        issues.append(
            "Nomor/kode cocok, tetapi nama peristiwa berbeda; mohon konfirmasi."
        )
    if fatal:
        return MonthlyRiskReportImportRow.LEVEL_RED, issues
    if issues:
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
    source_risks = sum(entry["source_sheet"] == "III.A" for entry in entries)
    source_treatments = sum(entry["source_sheet"] == "III.B" for entry in entries)
    summary = {
        "source_risks": source_risks,
        "source_treatments": source_treatments,
        "source_total": len(entries),
        "matched": 0,
        "ambiguous": 0,
        "invalid": 0,
        "skipped": 0,
    }
    fingerprint = target_item_fingerprint(batch.report)
    if not batch.report.items.exists():
        batch.status = batch.STATUS_REVIEW
        batch.parser_version = IMPORT_PARSER_VERSION
        batch.target_fingerprint = fingerprint
        batch.analysis_summary = summary
        batch.blocking_reason = (
            f"Laporan {batch.report.periode.nama_periode} belum memiliki item risiko "
            "sebagai target import."
        )
        batch.ai_used = False
        batch.ai_summary = (
            f"Risiko sumber: {source_risks}; rencana perlakuan sumber: "
            f"{source_treatments}; total sumber: {len(entries)}. "
            "Matching tidak dijalankan karena target kosong."
        )
        batch.analyzed_at = timezone.now()
        batch.error_message = ""
        batch.save(
            update_fields=[
                "status",
                "parser_version",
                "target_fingerprint",
                "analysis_summary",
                "blocking_reason",
                "ai_used",
                "ai_summary",
                "analyzed_at",
                "error_message",
                "updated_at",
            ]
        )
        return batch
    rows = []
    for entry in entries:
        item, method, confidence, candidates = _match_item(batch.report, entry)
        level, issues = _validate_entry(
            entry, item, method, confidence, candidates
        )
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
                raw_data={
                    **entry["raw_data"],
                    "parser_version": IMPORT_PARSER_VERSION,
                    "normalized_risk_name": _normalize(entry["risk_event_text"]),
                    "ambiguity_candidates": candidates,
                },
                proposed_data=proposed,
                user_decision="import" if level == "green" else "pending",
            )
        )
        if item:
            summary["matched"] += 1
        if method == "ambiguous":
            summary["ambiguous"] += 1
        if level == MonthlyRiskReportImportRow.LEVEL_RED:
            summary["invalid"] += 1
    ai_used, ai_summary = _run_ai_review(batch, rows)
    batch.status = batch.STATUS_REVIEW
    batch.ai_used = ai_used
    batch.ai_summary = ai_summary
    batch.analyzed_at = timezone.now()
    batch.error_message = ""
    batch.parser_version = IMPORT_PARSER_VERSION
    batch.target_fingerprint = fingerprint
    batch.analysis_summary = summary
    batch.blocking_reason = ""
    batch.save(update_fields=[
        "status",
        "ai_used",
        "ai_summary",
        "analyzed_at",
        "error_message",
        "parser_version",
        "target_fingerprint",
        "analysis_summary",
        "blocking_reason",
        "updated_at",
    ])
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
    if batch.blocking_reason:
        raise ValidationError(batch.blocking_reason)
    if not batch_analysis_is_current(batch):
        raise ValidationError(
            "Struktur target laporan berubah setelah preview. Jalankan analisis ulang."
        )
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
        item.save(update_fields=[*applied.keys(), "updated_at"])
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
