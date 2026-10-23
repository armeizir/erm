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


def profile_monitoring_message(rows: list[dict], approved_rows: list[dict] | None = None,
                               progress_rows: list[dict] | None = None,
                               *, include_kpmr: bool = True) -> str:
    approved_rows = approved_rows or []
    progress_rows = progress_rows or []
    lines = [
        "Yth. Bapak/Ibu PIC Manajemen Risiko Bidang/Unit,", "",
        "Berdasarkan hasil monitoring terbaru pada Aplikasi PRISMA, berikut status laporan Profil Risiko bulanan:", "",
    ]
    for title, group, approved in (
        ("Laporan yang telah Approved", approved_rows, True),
        ("Laporan dalam proses Submit/Review", progress_rows, False),
        ("Laporan yang belum Approved", rows, False),
    ):
        lines.append(f"{title} ({len(group)}):")
        if not group:
            lines.append("- Tidak ada data.")
        for index, row in enumerate(group, start=1):
            detail = f"{index}. {row['unit']} – {row['month']} – {row['status']}"
            if approved and include_kpmr:
                detail += (
                    f" – KPMR {row['kpmr_period']} "
                    f"{row.get('kpmr_text', 'Belum Dinilai')}"
                )
            else:
                detail += f" – Coverage {row['coverage']}"
            lines.append(detail)
        lines.append("")
    lines.extend([
        "",
        "Mohon bantuan Bapak/Ibu PIC masing-masing Bidang/Unit untuk segera menindaklanjuti proses review, melengkapi data yang masih kurang, serta menyelesaikan proses approval laporan Profil Risiko pada Aplikasi PRISMA.",
        "", "Terima kasih atas perhatian dan kerja sama Bapak/Ibu. 🙏", "",
        "Bidang Manajemen Risiko & Kepatuhan", "PT PLN Batam",
    ])
    return "\n".join(lines)
