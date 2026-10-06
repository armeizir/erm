from __future__ import annotations

import httpx
from django.conf import settings


FONNTE_SEND_URL = "https://api.fonnte.com/send"


class WhatsAppConfigurationError(RuntimeError):
    pass


def send_fonnte_message(message: str, *, target: str | None = None) -> dict:
    token = getattr(settings, "FONNTE_TOKEN", "").strip()
    sender = getattr(settings, "WHATSAPP_SENDER", "").strip()
    target = (target or getattr(settings, "WHATSAPP_TARGET", "")).strip()
    if not token:
        raise WhatsAppConfigurationError("FONNTE_TOKEN belum diisi.")
    if not target:
        raise WhatsAppConfigurationError("WHATSAPP_TARGET belum diisi.")

    response = httpx.post(
        FONNTE_SEND_URL,
        headers={"Authorization": token},
        data={"target": target, "message": message, "countryCode": "62"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") is False:
        raise RuntimeError(payload.get("detail") or payload.get("reason") or "Fonnte menolak pesan.")
    return payload


def profile_monitoring_message(pending_rows: list[dict], approved_rows: list[dict] | None = None, progress_rows: list[dict] | None = None) -> str:
    approved_rows = approved_rows or []
    progress_rows = progress_rows or []
    lines = [
        "Yth. Bapak/Ibu PIC Manajemen Risiko Bidang/Unit,", "",
        "Berdasarkan hasil monitoring terbaru pada aplikasi ERM, berikut status laporan Profil Risiko:", "",
    ]
    lines.append(f"Laporan yang telah Approved ({len(approved_rows)}):")
    if approved_rows:
        for index, row in enumerate(approved_rows, start=1):
            kpmr = f" – KPMR {row['kpmr_period']} {row['kpmr_score']}" if row.get("kpmr_score") is not None else ""
            lines.append(f"{index}. {row['unit']} – {row['month']} – Approved{kpmr}")
    else:
        lines.append("- Tidak ada data.")
    lines.extend(["", f"Laporan dalam proses Submit/Review ({len(progress_rows)}):"])
    if progress_rows:
        for index, row in enumerate(progress_rows, start=1):
            lines.append(f"{index}. {row['unit']} – {row['month']} – {row['status']} – Coverage {row['coverage']}")
    else:
        lines.append("- Tidak ada data.")
    lines.extend(["", f"Laporan yang belum Approved ({len(pending_rows)}):"])
    for index, row in enumerate(pending_rows, start=1):
        lines.append(f"{index}. {row['unit']} – {row['month']} – {row['status']} – Coverage {row['coverage']}")
    lines.extend([
        "",
        "Mohon bantuan Bapak/Ibu PIC masing-masing Bidang/Unit untuk segera menindaklanjuti proses review, melengkapi data yang masih kurang, serta menyelesaikan proses approval laporan Profil Risiko pada aplikasi ERM.",
        "", "Terima kasih atas perhatian dan kerja sama Bapak/Ibu. 🙏", "",
        "Bidang Manajemen Risiko & Kepatuhan", "PT PLN Batam",
    ])
    return "\n".join(lines)
