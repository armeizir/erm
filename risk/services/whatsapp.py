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


def profile_monitoring_message() -> str:
    return """Yth. Bapak/Ibu PIC Manajemen Risiko Bidang/Unit,

Berdasarkan hasil monitoring terbaru pada aplikasi ERM, masih terdapat 3 laporan Profil Risiko yang belum berstatus Approved, yaitu:

1. BID KEU – Juli – Draft – Coverage 100%
2. UB DISYAN – Agustus – Draft – Coverage 85%
3. UB KITRAN – Juli – Draft – Coverage 100%

Mohon bantuan Bapak/Ibu PIC masing-masing Bidang/Unit untuk segera menindaklanjuti proses review, melengkapi data yang masih kurang, serta menyelesaikan proses approval laporan Profil Risiko pada aplikasi ERM.

Terima kasih atas perhatian dan kerja sama Bapak/Ibu. 🙏

Bidang Manajemen Risiko & Kepatuhan
PT PLN Batam"""
