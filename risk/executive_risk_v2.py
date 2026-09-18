"""Executive Risk Dashboard V2 sourced from the approved August 2026 workbook."""

from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from risk.executive_signage import _build_risk_card
from risk.services.permissions import get_accessible_corporate_risk_items


SOURCE_FILE = "05. KK RISIKO Gangguan Padam System Agustus 2026 (1).xlsx"


def _billions(value):
    return float(Decimal(str(value)) / Decimal("1000000000"))


def _idr_compact(value, decimals=2):
    amount = Decimal(str(value))
    if abs(amount) >= Decimal("1000000000"):
        scaled, suffix = amount / Decimal("1000000000"), "M"
    elif abs(amount) >= Decimal("1000000"):
        scaled, suffix = amount / Decimal("1000000"), "Juta"
    else:
        scaled, suffix = amount, ""
    quantum = Decimal("1").scaleb(-decimals)
    text = f"{scaled.quantize(quantum, rounding=ROUND_HALF_UP):,.{decimals}f}"
    text = text.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"Rp {text} {suffix}".strip()


def _dashboard_data():
    # Explicit source mapping: Dashboard!B4/C4/E4/F10:F12.
    target = Decimal("6726701018")
    actual_ytd = Decimal("4716611184.4")
    current_month = Decimal("696600000")
    best_case = Decimal("5345486674")
    baseline_case = Decimal("7229336303.93797")
    worst_case = Decimal("9749729818")
    monthly_values = [
        Decimal("0"), Decimal("957825000"), Decimal("5107998"),
        Decimal("513320033.2"), Decimal("726693642"), Decimal("746638668"),
        Decimal("1070425843.2"), Decimal("696600000"),
        Decimal("610737441.020819"), Decimal("774631608.5739318"),
        Decimal("585408933.7003517"), Decimal("541947136.2428687"),
    ]  # Dashboard!C22:N22: actual Jan-Aug, forecast Sep-Dec.
    achievement = actual_ytd / target * Decimal("100")

    return {
        "source_file": SOURCE_FILE,
        "risk_number": 5,
        "risk_title": "Gangguan Padam Parsial dan/atau Blackout pada Pelanggan Premium",
        "risk_description": (
            "Risiko padam parsial dan/atau blackout pada pelanggan premium akibat "
            "gangguan sistem ketenagalistrikan yang dapat mengganggu operasional "
            "pelanggan, menimbulkan kompensasi, serta menurunkan pendapatan dan reputasi PLN Batam."
        ),
        "period": "s.d. Agustus 2026",
        "level": "High 24",
        "status": "AMAN",
        "actual_ytd": _idr_compact(actual_ytd),
        "achievement": f"{achievement.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}".replace(".", ","),
        "target": _idr_compact(target),
        "current_month": _idr_compact(current_month, 1),
        "best_case": _idr_compact(best_case),
        "baseline_case": _idr_compact(baseline_case),
        "worst_case": _idr_compact(worst_case),
        "risk_limit": _idr_compact(target * Decimal("0.95")),
        "risk_appetite": _idr_compact(target),
        "risk_tolerance": _idr_compact(target * Decimal("1.05")),
        "chart_months": ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"],
        "chart_values": [_billions(value) for value in monthly_values],
        "actual_month_count": 8,
        "drivers": [
            "Kesiapan fasilitas anti-blackout belum merata (Free Governor & Island Operation).",
            "Keandalan jaringan distribusi masih terbatas (feeder overload, jaringan rentan gangguan).",
            "Sistem proteksi dan otomasi belum optimal (integrasi SCADA & jaringan FO).",
            "Kerentanan jaringan terhadap gangguan fisik dan keandalan peralatan tinggi.",
        ],
        "programs": [
            {"name": "Pembangunan Mudal Rensis (10 Feeder)", "pic": "UB DISYAN", "status": "On Track", "class": "on-track"},
            {"name": "Pemasangan Box Culvert (300 m)", "pic": "UB DISYAN", "status": "On Track", "class": "on-track"},
            {"name": "Integrasi Gardu ke SCADA (60 G)", "pic": "UB DISYAN", "status": "In Progress", "class": "in-progress"},
            {"name": "Upgrade kubikel (AIS, LBS ke CB) (20 GD)", "pic": "UB DISYAN", "status": "Planned", "class": "planned"},
            {"name": "Upgrade relay proteksi (60 Cell)", "pic": "UB DISYAN", "status": "Planned", "class": "planned"},
            {"name": "Pemanfaatan jaringan FO (200 GD)", "pic": "UB DISYAN", "status": "Planned", "class": "planned"},
            {"name": "Upgrade jardis SUTM ke SKTM (10 Kms)", "pic": "UB DISYAN", "status": "Planned", "class": "planned"},
        ],
        "kri_rows": [
            {"name": "Jumlah pelanggan terdampak", "status": "Di atas threshold", "class": "danger", "icon": "↑"},
            {"name": "Durasi padam (jam)", "status": "Dalam pemantauan", "class": "watch", "icon": "—"},
            {"name": "Ketersediaan fasilitas anti-blackout", "status": "Dalam pemantauan", "class": "watch", "icon": "—"},
            {"name": "Keandalan jaringan distribusi", "status": "Perlu perhatian", "class": "danger", "icon": "↑"},
        ],
        "concerns": [
            "Percepatan realisasi program keandalan jaringan prioritas (anti-blackout pelanggan premium).",
            "Dukungan alokasi anggaran dan percepatan pengadaan material kritikal.",
            "Koordinasi lintas unit untuk percepatan pekerjaan konstruksi dan integrasi SCADA/FO.",
            "Monitoring berkala terhadap pelanggan dengan risiko kompensasi tinggi.",
        ],
    }


def _dynamic_dashboard_data(risk, year):
    """Adapt the existing Executive Risk card to the V2 visual layout."""
    card = _build_risk_card(risk, year)
    causes = list(risk.daftar_penyebab.all().order_by("urutan")[:4])
    treatments = list(risk.rencana_perlakuan_items.all().order_by("urutan")[:7])
    kri_rows = []
    for row in (card.get("rows") or [])[:4]:
        trend = row.get("trend") or "flat"
        status_class = row.get("status_class") or "neutral"
        kri_rows.append({
            "name": row.get("name") or "Indikator risiko",
            "status": row.get("status") or row.get("actual") or "Belum tersedia",
            "class": "danger" if status_class == "danger" else "watch" if status_class == "warning" else "neutral",
            "icon": "↑" if trend == "up" else "↓" if trend == "down" else "—",
        })
    if not kri_rows:
        kri_rows = [{"name": "KRI belum tersedia", "status": "Lengkapi data sumber", "class": "neutral", "icon": "—"}]

    drivers = []
    for cause in causes:
        text = cause.penyebab_risiko or cause.key_risk_indicators
        if text:
            drivers.append(text)
    if not drivers:
        drivers = ["Penyebab utama belum tersedia pada profil risiko."]

    programs = []
    for item in treatments:
        name = (item.rencana_perlakuan_risiko or "").strip()
        if name:
            programs.append({
                "name": name,
                "pic": "–",
                "status": "Planned",
                "class": "planned",
            })
    if not programs:
        programs = [{"name": "Program mitigasi belum tersedia", "pic": "–", "status": "Belum tersedia", "class": "planned"}]

    status = card.get("status") or "BELUM DINILAI"
    concerns = list(card.get("decisions") or [])[:4]
    if not concerns:
        concerns = ["Management decision belum tersedia pada profil risiko."]

    return {
        "source_file": "Database RCC",
        "risk_number": card.get("number"),
        "risk_title": card.get("title") or "Risiko belum tersedia",
        "risk_description": card.get("description") or "Deskripsi risiko belum tersedia.",
        "period": card.get("period_label") or str(year),
        "level": card.get("level") or "Belum dipetakan",
        "status": status,
        "status_class": card.get("status_class") or "neutral",
        "actual_ytd": card.get("ytd") or "–",
        "achievement": "–",
        "target": card.get("target") or "–",
        "current_month": card.get("current") or "–",
        "best_case": "–",
        "baseline_case": card.get("forecast") or "–",
        "worst_case": card.get("worst_case") or "–",
        "risk_limit": "–",
        "risk_appetite": card.get("target") or "–",
        "risk_tolerance": card.get("trigger") or "–",
        "chart_values": [],
        "actual_month_count": 0,
        "drivers": drivers,
        "programs": programs,
        "kri_rows": kri_rows,
        "concerns": concerns,
        "conclusion": card.get("status_note") or "Posisi risiko mengikuti data RCC terkini.",
    }


@login_required
def executive_risk_v2_dashboard(request):
    base = (
        get_accessible_corporate_risk_items(request.user)
        .select_related(
            "summary", "kategori_risiko", "matrix_cell_residual",
            "matrix_cell_residual__level_risiko",
        )
        .prefetch_related(
            "daftar_penyebab", "daftar_penyebab__pemilik_risiko",
            "rencana_perlakuan_items", "sumber_risiko",
            "sumber_risiko__reassessment_item",
        )
    )
    years = list(base.values_list("summary__tahun", flat=True).distinct().order_by("-summary__tahun"))
    if not years:
        years = [2026]
    try:
        selected_year = int(request.GET.get("year") or years[0])
    except (TypeError, ValueError):
        selected_year = years[0]
    risks = list(base.filter(summary__tahun=selected_year).order_by("no_risiko", "no_item", "id"))
    selected = None
    try:
        selected_id = int(request.GET.get("risk") or 0)
    except (TypeError, ValueError):
        selected_id = 0
    if selected_id:
        selected = next((item for item in risks if item.pk == selected_id), None)
    if selected is None and risks:
        selected = risks[0]

    if selected is None:
        context = _dashboard_data()
    else:
        number = str(selected.no_risiko or selected.no_item or "").strip().lstrip("#")
        context = _dashboard_data() if selected_year == 2026 and number == "5" else _dynamic_dashboard_data(selected, selected_year)
    context.update({
        "years": years,
        "selected_year": selected_year,
        "risks": risks,
        "selected_risk_id": selected.pk if selected else "",
        "tv_mode": request.GET.get("tv") in {"1", "true", "yes"},
    })
    context["page_title"] = "Executive Risk Dashboard V2"
    return render(request, "executive_risk_dashboard_v2.html", context)
