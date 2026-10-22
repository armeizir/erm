"""Executive Risk Dashboard V2 sourced from the approved August 2026 workbook."""

from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from corporate_risk.models import MultiMetricMonteCarloResult
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
        "outlook_status": (
            "BAHAYA" if worst_case > target * Decimal("1.05")
            else "WASPADA" if worst_case > target
            else "AMAN"
        ),
        "outlook_status_class": (
            "bahaya" if worst_case > target * Decimal("1.05")
            else "waspada" if worst_case > target
            else "aman"
        ),
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


def _dynamic_dashboard_data_base(risk, year):
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


# EXECUTIVE_MONTE_CARLO_SYNC_V1
def _metric_display(value, unit="", decimals=2):
    """Format angka dengan pemisah Indonesia dan satuan metrik."""
    if value is None:
        return "–"

    amount = Decimal(str(value))
    text = f"{amount:,.{decimals}f}"
    text = text.replace(",", "X").replace(".", ",").replace("X", ".")

    return f"{text} {unit}".strip()


def _result_period_year(result):
    period = result.forecast_periode

    for field_name in ("tanggal_mulai", "tanggal_data", "tanggal"):
        value = getattr(period, field_name, None)
        if value:
            return value.year

    period_year = getattr(period, "tahun", None)
    if period_year:
        return int(period_year)

    return None


def _latest_monte_carlo_result(risk, year):
    """
    Memilih hasil Multi Metric Monte Carlo terbaru untuk risiko dan tahun
    yang sedang dibuka pada dashboard.
    """
    related_model = (
        MultiMetricMonteCarloResult
        ._meta
        .get_field("corporate_risk_item")
        .remote_field
        .model
    )

    queryset = (
        MultiMetricMonteCarloResult.objects
        .select_related("corporate_risk_item", "forecast_periode")
    )

    if isinstance(risk, related_model):
        queryset = queryset.filter(corporate_risk_item=risk)
    else:
        risk_number = getattr(risk, "no_risiko", None)
        related_fields = {
            field.name for field in related_model._meta.concrete_fields
        }

        if risk_number not in (None, "") and "no_risiko" in related_fields:
            queryset = queryset.filter(
                corporate_risk_item__no_risiko=risk_number
            )
        else:
            queryset = queryset.filter(
                corporate_risk_item_id=getattr(risk, "pk", None)
            )

    candidates = list(
        queryset.filter(
            forecast_periode__tanggal_mulai__year=int(year)
        ).order_by(
            "-forecast_periode__tanggal_selesai", "-updated_at", "-pk"
        )[:20]
    )

    for result in candidates:
        if _result_period_year(result) == int(year):
            return result

    return candidates[0] if candidates else None


def _dynamic_dashboard_data(risk, year):
    """
    Executive Dashboard menggunakan hasil Multi Metric Monte Carlo terbaru.
    Data RCC tetap menjadi fallback apabila simulasi belum tersedia.
    """
    context = _dynamic_dashboard_data_base(risk, year)
    result = _latest_monte_carlo_result(risk, year)

    if result is None:
        # Jika Monte Carlo belum tersedia, gunakan proyeksi RCC sebagai fallback.
        # Status ditentukan dengan membandingkan Worst Case dan Risk Tolerance.
        import re

        def parse_dashboard_number(value):
            if value is None:
                return None

            if isinstance(value, (int, float)):
                return float(value)

            text = str(value).strip()
            if not text or text in {"–", "-", "None"}:
                return None

            # Mengubah format Indonesia, misalnya:
            # "Rp 9,75 M" -> 9.75
            # "9.750.000.000,00" -> 9750000000.00
            cleaned = re.sub(r"[^0-9,.-]", "", text)

            if "," in cleaned and "." in cleaned:
                cleaned = cleaned.replace(".", "").replace(",", ".")
            elif "," in cleaned:
                cleaned = cleaned.replace(",", ".")
            elif cleaned.count(".") > 1:
                cleaned = cleaned.replace(".", "")

            try:
                return float(cleaned)
            except (TypeError, ValueError):
                return None

        worst_value = parse_dashboard_number(context.get("worst_case"))
        tolerance_value = parse_dashboard_number(context.get("risk_tolerance"))

        polarity = str(
            getattr(risk, "polaritas", "")
            or getattr(risk, "polarity", "")
            or ""
        ).strip().lower()

        higher_is_better = polarity in {
            "positive", "positif", "maximize", "maximise",
            "semakin tinggi semakin baik",
        }

        if worst_value is not None and tolerance_value is not None:
            exceeds_tolerance = (
                worst_value < tolerance_value
                if higher_is_better
                else worst_value > tolerance_value
            )

            if exceeds_tolerance:
                context["outlook_status"] = "BAHAYA"
                context["outlook_status_class"] = "danger"
            else:
                context["outlook_status"] = "AMAN"
                context["outlook_status_class"] = "safe"

            context["source_file"] = (
                "Database RCC — status outlook dihitung dari "
                "Worst Case terhadap Risk Tolerance"
            )
        else:
            context["outlook_status"] = "BELUM TERSEDIA"
            context["outlook_status_class"] = "waspada"
            context["source_file"] = (
                "Database RCC — data pembanding outlook belum lengkap"
            )

        context["chart_unit"] = context.get("chart_unit") or "Satuan metrik"
        return context

    context["period"] = str(result.forecast_periode)
    metric_snapshot = result.metric_snapshot or {}
    simulation_snapshot = result.simulation_snapshot or {}

    metrics = metric_snapshot.get("metrics") or []
    target_metric = next(
        (item for item in metrics if item.get("is_target_metric")),
        None,
    )

    if target_metric is None and metrics:
        target_metric = max(
            metrics,
            key=lambda item: float(item.get("weight_ratio") or 0),
        )

    target_metric = target_metric or {}
    metric_name = target_metric.get("metric_name") or "Metrik target"
    metric_unit = target_metric.get("unit") or ""

    target_analysis = simulation_snapshot.get("target_analysis") or {}

    target_value = (
        result.target_value
        if result.target_value is not None
        else target_analysis.get("target_value")
    )
    actual_ytd = target_analysis.get("actual_total")
    last_actual = target_metric.get("last_actual")

    history_rows = target_metric.get("history_rows") or []
    actual_by_month = {}

    for row in history_rows:
        tanggal = str(row.get("tanggal") or "")
        try:
            row_year = int(tanggal[:4])
            row_month = int(tanggal[5:7])
        except (TypeError, ValueError):
            continue

        if row_year == int(year) and 1 <= row_month <= 12:
            actual_by_month[row_month] = Decimal(
                str(row.get("actual") or 0)
            )

    forecast_rows = (
        simulation_snapshot.get("target_projection_rows")
        or simulation_snapshot.get("descriptive_projection_rows")
        or []
    )

    forecast_by_month = {}
    last_actual_month = max(actual_by_month, default=0)

    for row in forecast_rows:
        try:
            offset = int(row.get("bulan_index") or 0)
        except (TypeError, ValueError):
            continue

        month_number = last_actual_month + offset

        if not 1 <= month_number <= 12:
            continue

        value = (
            row.get("forecast_median")
            if row.get("forecast_median") is not None
            else row.get("f_p50")
        )
        if value is None:
            value = row.get("mean")

        if value is not None:
            forecast_by_month[month_number] = Decimal(str(value))

    combined = dict(actual_by_month)
    combined.update(forecast_by_month)
    last_chart_month = max(combined, default=0)

    # CHART_UNIT_SCALE_FIX_V1
    unit_lower = (metric_unit or "").strip().lower()
    chart_divisor = Decimal("1")

    if unit_lower == "kwh":
        chart_divisor = Decimal("1000000000")
        chart_unit = "Miliar kWh"
    elif unit_lower in {"rp", "idr"}:
        chart_divisor = Decimal("1000000000")
        chart_unit = "Rp Miliar"
    else:
        chart_unit = (metric_unit or "").strip() or "Satuan metrik"

    chart_values = [
        float(combined.get(month, Decimal("0")) / chart_divisor)
        for month in range(1, last_chart_month + 1)
    ]

    probability_achieve = (
        result.probability_achieve_target
        if result.probability_achieve_target is not None
        else target_analysis.get("probability_achieve_target")
    )
    probability_not_achieve = (
        result.probability_not_achieve_target
        if result.probability_not_achieve_target is not None
        else target_analysis.get("probability_not_achieve_target")
    )

    target_status = result.target_status or target_analysis.get(
        "target_status"
    ) or "Belum tersedia"

    risk_status = result.risk_status or target_analysis.get(
        "risk_status"
    ) or "Belum tersedia"

    if (
        str(target_status).strip().lower() == "tercapai"
        and str(risk_status).strip().lower() == "aman"
    ):
        outlook_status = "AMAN"
        outlook_status_class = "aman"
    elif (
        probability_not_achieve is not None
        and Decimal(str(probability_not_achieve)) < Decimal("50")
    ):
        outlook_status = "WASPADA"
        outlook_status_class = "waspada"
    else:
        outlook_status = "BAHAYA"
        outlook_status_class = "bahaya"

    # Current Status menggunakan pencapaian bulan berjalan, bukan outlook.
    positive_metric = (
        "penjualan tenaga listrik" in metric_name.lower()
        and metric_unit.lower() == "kwh"
    )

    if (
        positive_metric
        and target_value is not None
        and last_actual is not None
        and Decimal(str(target_value)) != 0
    ):
        monthly_target = Decimal(str(target_value)) / Decimal("12")
        current_ratio = Decimal(str(last_actual)) / monthly_target

        if current_ratio >= Decimal("0.95"):
            context["status"] = "TERKENDALI"
            context["status_class"] = "safe"
        elif current_ratio >= Decimal("0.90"):
            context["status"] = "WASPADA"
            context["status_class"] = "warning"
        else:
            context["status"] = "BAHAYA"
            context["status_class"] = "danger"

    # COP_POSITION_ACTUAL_V1
    cop_name = " ".join(
        str(metric_name).casefold()
        .replace("_", " ").replace("-", " ").split()
    )
    cop_is_position = (
        str(metric_unit).strip().casefold() in {"hari", "day", "days"}
        and (
            "collection period" in cop_name
            or "cop" in cop_name.split()
        )
    )

    if cop_is_position:
        # COP merupakan posisi periode, tidak dijumlah antarbulan.
        actual_ytd = None
        context["achievement"] = "–"
        if last_actual is not None:
            cop_value = Decimal(str(last_actual))
            if cop_value.is_finite() and cop_value >= 0:
                actual_ytd = cop_value
    elif actual_ytd is None and actual_by_month:
        actual_ytd = sum(actual_by_month.values(), Decimal("0"))

    if target_value not in (None, 0) and actual_ytd is not None:
        achievement = (
            Decimal(str(actual_ytd))
            / Decimal(str(target_value))
            * Decimal("100")
        )
        context["achievement"] = (
            f"{achievement.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"
            .replace(".", ",")
        )

    context.update({
        "source_file": (
            f"Multi Metric Monte Carlo Result ID {result.pk} "
            f"— diperbarui {result.updated_at:%d-%m-%Y %H:%M}"
        ),
        "actual_ytd": _metric_display(actual_ytd, metric_unit, 0),
        "current_month": _metric_display(last_actual, metric_unit, 0),
        "target": _metric_display(target_value, metric_unit, 2 if metric_unit.strip().casefold() == "mw" else 0),
        "best_case": _metric_display(result.best_case_value, metric_unit, 2),
        "baseline_case": _metric_display(
            result.baseline_value or result.forecast_total,
            metric_unit,
            2,
        ),
        "worst_case": _metric_display(
            result.worst_case_value,
            metric_unit,
            2,
        ),
        "chart_values": chart_values,
        "actual_month_count": last_actual_month,
        "chart_unit": chart_unit,
        "outlook_status": outlook_status,
        "outlook_status_class": outlook_status_class,
        "probability_achieve": probability_achieve,
        "probability_not_achieve": probability_not_achieve,
        "target_status": target_status,
        "risk_status": risk_status,
        "conclusion": (
            f"Monte Carlo {result.n_simulations:,} trials menghasilkan "
            f"baseline/P50 {_metric_display(result.baseline_value or result.forecast_total, metric_unit, 2)}, "
            f"dengan probabilitas target tercapai "
            f"{_metric_display(probability_achieve, '%', 2)} dan tidak tercapai "
            f"{_metric_display(probability_not_achieve, '%', 2)}. "
            f"Status target {target_status} dan status risiko {risk_status}."
        ),
    })

    # FINAL_OUTLOOK_THRESHOLD_NORMALIZATION_V1
    # Normalisasi terakhir setelah data RCC atau Monte Carlo selesai dimuat.
    # Hanya mengganti status yang masih kosong/BELUM TERSEDIA.
    current_outlook = str(
        context.get("outlook_status") or ""
    ).strip().upper()

    unavailable_statuses = {
        "",
        "-",
        "–",
        "NONE",
        "BELUM TERSEDIA",
        "BELUM DISIMULASIKAN",
        "BELUM DINILAI",
    }

    if current_outlook in unavailable_statuses:
        import re

        def parse_final_outlook_number(value):
            if value is None:
                return None

            if isinstance(value, (int, float)):
                return float(value)

            text = str(value).strip()
            if not text or text.upper() in unavailable_statuses:
                return None

            cleaned = re.sub(r"[^0-9,.-]", "", text)

            if "," in cleaned and "." in cleaned:
                cleaned = cleaned.replace(".", "").replace(",", ".")
            elif "," in cleaned:
                cleaned = cleaned.replace(",", ".")
            elif cleaned.count(".") > 1:
                cleaned = cleaned.replace(".", "")

            try:
                return float(cleaned)
            except (TypeError, ValueError):
                return None

        worst_value = parse_final_outlook_number(
            context.get("worst_case")
        )
        tolerance_value = parse_final_outlook_number(
            context.get("risk_tolerance")
        )

        polarity = str(
            getattr(risk, "polaritas", "")
            or getattr(risk, "polarity", "")
            or ""
        ).strip().lower()

        higher_is_better = polarity in {
            "positive",
            "positif",
            "maximize",
            "maximise",
            "semakin tinggi semakin baik",
        }

        if worst_value is not None and tolerance_value is not None:
            exceeds_tolerance = (
                worst_value < tolerance_value
                if higher_is_better
                else worst_value > tolerance_value
            )

            if exceeds_tolerance:
                context["outlook_status"] = "BAHAYA"
                context["outlook_status_class"] = "danger"
            else:
                context["outlook_status"] = "AMAN"
                context["outlook_status_class"] = "safe"

    return context


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
        context = _dynamic_dashboard_data(selected, selected_year)

    # WORST_CASE_DETAILS_V1
    if selected is not None:
        number = str(
            selected.no_risiko or selected.no_item or ""
        ).strip().lstrip("#")
        if number == "5":
            result = _latest_monte_carlo_result(selected, selected_year)
            if (
                result is not None
                and _result_period_year(result) == int(selected_year)
            ):
                analysis = (
                    result.simulation_snapshot or {}
                ).get("target_analysis") or {}

                probability = result.probability_not_achieve_target
                if probability is None:
                    probability = analysis.get("probability_not_achieve_target")

                impact = result.dampak_worst_case
                worst = result.worst_case_value
                target = result.target_value
                baseline = result.baseline_value
                if baseline is None:
                    baseline = result.forecast_total

                if impact is None and worst is not None and target is not None:
                    impact = max(
                        Decimal(str(worst)) - Decimal(str(target)),
                        Decimal("0"),
                    )

                context.update({
                    "best_case": _idr_compact(result.best_case_value)
                        if result.best_case_value is not None else "–",
                    "baseline_case": _idr_compact(baseline)
                        if baseline is not None else "–",
                    "worst_case": _idr_compact(worst)
                        if worst is not None else "–",
                    "worst_probability": _metric_display(probability, "%", 2),
                    "worst_impact": _idr_compact(impact)
                        if impact is not None else "–",
                    "worst_exposure": "–",
                })

                if probability is not None and impact is not None:
                    p = Decimal(str(probability))
                    if Decimal("0") <= p <= Decimal("100"):
                        context["worst_exposure"] = _idr_compact(
                            p / Decimal("100") * Decimal(str(impact))
                        )

                if target is not None:
                    appetite = Decimal(str(target))
                    tolerance = appetite * Decimal("1.05")
                    context["target"] = _idr_compact(appetite)
                    context["risk_limit"] = _idr_compact(
                        appetite * Decimal("0.95")
                    )
                    context["risk_appetite"] = _idr_compact(appetite)
                    context["risk_tolerance"] = _idr_compact(tolerance)
                    if worst is not None:
                        value = Decimal(str(worst))
                        status = (
                            "BAHAYA" if value > tolerance
                            else "WASPADA" if value > appetite
                            else "AMAN"
                        )
                        context["outlook_status"] = status
                        context["outlook_status_class"] = status.lower()


    # SLA_ZERO_TARGET_DISPLAY_V1
    if selected is not None and int(selected_year) == 2026:
        number = str(
            selected.no_risiko or selected.no_item or ""
        ).strip().lstrip("#")
        if number == "5":
            context.update({
                "sla_zero_target": True,
                "target": _idr_compact(Decimal("0")),
                "achievement": "–",
                "historical_reference": _idr_compact(Decimal("6726701018")),
                "risk_limit": "Belum ditetapkan",
                "risk_appetite": "Belum ditetapkan",
                "risk_tolerance": "Belum ditetapkan",
                "best_case_note": "Skenario optimistis (P5)",
                "baseline_case_note": "Skenario tengah (P50)",
                "worst_case_note": "Skenario buruk (P95)",
            })
            result = _latest_monte_carlo_result(selected, selected_year)
            if (
                result is not None
                and _result_period_year(result) == int(selected_year)
                and result.target_value == Decimal("0")
            ):
                context["outlook_status"] = (
                    "BAHAYA"
                    if result.worst_case_value is not None
                    and result.worst_case_value > 0
                    else "AMAN"
                    if result.worst_case_value is not None
                    else "BELUM TERSEDIA"
                )
                context["outlook_status_class"] = (
                    "bahaya" if context["outlook_status"] == "BAHAYA"
                    else "aman" if context["outlook_status"] == "AMAN"
                    else "waspada"
                )
                context["conclusion"] = (
                    "Target kompensasi 2026 Rp0. "
                    "Probabilitas total kompensasi melampaui target "
                    f"{_metric_display(result.probability_not_achieve_target, '%', 2)}. "
                    f"Proyeksi Worst Case {_idr_compact(result.worst_case_value)}. "
                    "Status outlook dibandingkan dengan target Rp0. "
                    "Realisasi 2025 Rp6,73 miliar hanya sebagai referensi historis."
                )


    # SLA_REFERENCE_ADMIN_V1
    chart_numbers = [
        float(value)
        for value in (context.get("chart_values") or [])
        if value is not None
    ]
    context["chart_scale"] = max(
        1.2,
        max(chart_numbers, default=0.0) * 1.15,
    )
    context["chart_reference_visible"] = True
    context["chart_reference_label"] = "Target bulanan"
    context["chart_reference_percent"] = "46.7"

    if context.get("sla_zero_target"):
        from risk.models import AppSetting
        from decimal import InvalidOperation

        setting = AppSetting.objects.order_by("pk").first()
        annual = (
            setting.sla_reference_annual
            if setting is not None
            else Decimal("6726701018")
        )
        visible = (
            setting.sla_reference_visible if setting is not None else True
        )
        label = (
            setting.sla_reference_label if setting is not None
            else "Rata-rata bulanan 2025"
        )
        reference = annual / Decimal("12") / Decimal("1000000000")
        values = []
        for value in context.get("chart_values") or []:
            try:
                number = Decimal(str(value))
                if number.is_finite() and number >= 0:
                    values.append(number)
            except (InvalidOperation, ValueError, TypeError):
                continue

        scale = max(
            Decimal("1.2"),
            max(values, default=Decimal("0")) * Decimal("1.10"),
            reference * Decimal("1.10") if visible else Decimal("0"),
        )
        context.update({
            "historical_reference": _idr_compact(annual),
            "chart_scale": float(scale),
            "chart_reference_visible": visible,
            "chart_reference_label": label or "Referensi historis 2025",
            "chart_reference_percent": format(
                reference / scale * Decimal("100"), ".6f"
            ),
            "chart_reference_value": _idr_compact(annual / Decimal("12")),
        })


    # HJR_REFERENCE_RATIO_V1
    if context.get("hjr_ratio_target") is not None:
        reference = context["hjr_ratio_target"]
        scale = max(context["chart_scale"], reference * 1.15)
        context.update(chart_scale=scale, chart_reference_label="Target harga jual",
            chart_reference_percent=format(reference / scale * 100, ".6f"),
            chart_reference_value=_metric_display(reference, "Rp/kWh", 2))

    # EXECUTIVE_PROGRAMS_FROM_ADMIN_V1
    if selected is not None:
        from risk.models import RencanaPerlakuanRisikoKorporat

        program_rows = RencanaPerlakuanRisikoKorporat.objects.filter(
            risiko_korporat_id=selected.pk
        ).order_by("urutan", "pk")

        status_classes = {
            "on track": "on-track",
            "on-track": "on-track",
            "sesuai rencana": "on-track",
            "in progress": "in-progress",
            "in-progress": "in-progress",
            "dalam proses": "in-progress",
            "planned": "planned",
            "direncanakan": "planned",
        }

        admin_programs = []
        for row in program_rows:
            name = (row.rencana_perlakuan_risiko or "").strip()
            if not name:
                continue
            status = (row.status or "").strip()
            admin_programs.append({
                "name": name,
                "pic": (row.pic or "").strip() or "–",
                "status": status or "Belum diisi",
                "class": status_classes.get(
                    status.casefold(), "program-status-neutral"
                ),
                "description": (row.keterangan or "").strip(),
            })

        context["programs"] = admin_programs or [{
            "name": "Program mitigasi belum diinput melalui admin",
            "pic": "–",
            "status": "Belum diisi",
            "class": "program-status-neutral",
        }]

    context.update({
        "years": years,
        "selected_year": selected_year,
        "risks": risks,
        "selected_risk_id": selected.pk if selected else "",
        "tv_mode": request.GET.get("tv") in {"1", "true", "yes"},
    })
    context["page_title"] = "Executive Risk Dashboard V2"
    return render(request, "executive_risk_dashboard_v2.html", context)


# COP_DASHBOARD_POSITION_V1
_cop_previous_dynamic_dashboard_data = _dynamic_dashboard_data


def _dynamic_dashboard_data(risk, year):
    context = _cop_previous_dynamic_dashboard_data(risk, year)
    result = _latest_monte_carlo_result(risk, year)
    if result is None:
        return context
    metrics = (result.metric_snapshot or {}).get("metrics") or []
    selected = next((m for m in metrics if m.get("is_target_metric")), None)
    if selected is None:
        return context
    name = " ".join(str(selected.get("metric_name") or "").casefold().replace("_", " ").replace("-", " ").split())
    unit = str(selected.get("unit") or "").strip()
    if unit.casefold() not in {"hari", "day", "days"} or not ("cop" in name.split() or "collection period" in name):
        return context
    actual = selected.get("last_actual")
    target = result.target_value
    if actual is not None:
        actual = Decimal(str(actual))
        context["actual_ytd"] = _metric_display(actual, unit, 0)
        context["current_month"] = _metric_display(actual, unit, 0)
    if target is None or Decimal(str(target)) <= 0:
        context["achievement"] = "–"
        return context
    target = Decimal(str(target))
    limit, tolerance = target * Decimal("0.95"), target * Decimal("1.05")
    context.update({
        "risk_limit": _metric_display(limit, unit, 2),
        "risk_appetite": _metric_display(target, unit, 2),
        "risk_tolerance": _metric_display(tolerance, unit, 2),
    })
    if actual is not None:
        context["achievement"] = format((actual / target * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f").replace(".", ",")
        if actual > tolerance:
            context.update(status="BAHAYA", status_class="danger")
        elif actual > target:
            context.update(status="WASPADA", status_class="warning")
        else:
            context.update(status="AMAN", status_class="safe")
    stats = selected.get("descriptive_stats") or {}
    if stats.get("patch") != "COP_END_OF_PERIOD_V1":
        context.update({
            "best_case": "Perlu hitung ulang", "baseline_case": "Perlu hitung ulang",
            "worst_case": "Perlu hitung ulang", "outlook_status": "BELUM TERSEDIA",
            "outlook_status_class": "waspada", "probability_achieve": None,
            "probability_not_achieve": None, "best_case_note": "Proyeksi COP belum dihitung ulang",
            "baseline_case_note": "Proyeksi COP belum dihitung ulang", "worst_case_note": "Proyeksi COP belum dihitung ulang",
            "conclusion": "Proyeksi COP perlu dihitung ulang dengan metode posisi Desember.",
        })
        return context

    def note(value):
        if value is None:
            return "Belum tersedia"
        value = Decimal(str(value))
        if value <= target:
            return "Dalam risk appetite"
        if value <= tolerance:
            return "Melewati risk appetite, dalam tolerance"
        return "Melebihi tolerance"

    context.update({
        "best_case": _metric_display(result.best_case_value, unit, 2),
        "baseline_case": _metric_display(result.baseline_value, unit, 2),
        "worst_case": _metric_display(result.worst_case_value, unit, 2),
        "best_case_note": note(result.best_case_value),
        "baseline_case_note": note(result.baseline_value),
        "worst_case_note": note(result.worst_case_value),
        "source_file": f"Monte Carlo Result {result.pk}: COP posisi Desember, bukan penjumlahan bulanan",
    })
    worst = result.worst_case_value
    if worst is None:
        context.update(outlook_status="BELUM TERSEDIA", outlook_status_class="waspada")
    elif Decimal(str(worst)) > tolerance:
        context.update(outlook_status="BAHAYA", outlook_status_class="danger")
    elif Decimal(str(worst)) > target:
        context.update(outlook_status="WASPADA", outlook_status_class="waspada")
    else:
        context.update(outlook_status="AMAN", outlook_status_class="safe")
    return context

# DASHBOARD_STATUS_LABEL_ID_V1
_status_label_previous_dashboard = _dynamic_dashboard_data

def _dynamic_dashboard_data(risk, year):
    context = _status_label_previous_dashboard(risk, year)
    labels = {
        "TERKENDALI": "AMAN",
        "AMAN": "AMAN",
        "WASPADA": "HATI-HATI",
        "HATI-HATI": "HATI-HATI",
        "BAHAYA": "BAHAYA",
    }
    for key in ("status", "outlook_status"):
        value = str(context.get(key) or "").strip().upper()
        if value in labels:
            context[key] = labels[value]
    return context

# INHERENT_MATRIX_LEVEL_V1
_matrix_level_previous_dashboard = _dynamic_dashboard_data

def _dynamic_dashboard_data(risk, year):
    context = _matrix_level_previous_dashboard(risk, year)
    score = getattr(risk, "level_risiko", None)
    labels = (
        (5, "Low"),
        (11, "Low to Moderate"),
        (15, "Moderate"),
        (19, "Moderate to High"),
        (25, "High"),
    )
    if isinstance(score, int) and not isinstance(score, bool) and 1 <= score <= 25:
        label = next(label for upper, label in labels if score <= upper)
        context["level"] = f"{label} ({score})"
    else:
        context["level"] = "Belum dipetakan"
    return context


# HJR_RATIO_DASHBOARD_V1
_hjr_previous_dashboard = _dynamic_dashboard_data

def _dynamic_dashboard_data(risk, year):
    context = _hjr_previous_dashboard(risk, year)
    result = _latest_monte_carlo_result(risk, year)
    if result is None:
        return context
    rows = (result.metric_snapshot or {}).get('metrics') or []
    target_row = next((r for r in rows if r.get('is_target_metric')), {})
    if target_row.get('aggregation_type') != 'ratio' or str(target_row.get('unit', '')).replace(' ', '').casefold() != 'rp/kwh':
        return context
    stats = target_row.get('descriptive_stats') or {}
    if stats.get('patch') != 'HJR_RATIO_OF_TOTALS_V1':
        context.update(actual_ytd='Perlu hitung ulang', achievement='–',
            best_case='Perlu hitung ulang', baseline_case='Perlu hitung ulang', worst_case='Perlu hitung ulang',
            outlook_status='BELUM TERSEDIA', outlook_status_class='neutral',
            conclusion='Hasil lama menjumlahkan harga bulanan; hitung ulang sebagai rasio pendapatan terhadap kWh.')
        return context
    analysis = (result.simulation_snapshot or {}).get('target_analysis') or {}
    target = Decimal(str(result.target_value)) if result.target_value is not None else None
    actual = Decimal(str(target_row['actual_total']))
    context.update(actual_ytd=_metric_display(actual, 'Rp/kWh', 2),
        current_month=_metric_display(target_row['last_actual'], 'Rp/kWh', 2),
        source_file=f'Monte Carlo Result {result.pk}: HJR rasio total pendapatan / total kWh',
        hjr_ratio_target=float(target) if target is not None else None,
        worst_probability=_metric_display(result.probability_not_achieve_target, '%', 2),
        worst_impact='–', worst_exposure='–')
    if target is not None and target > 0:
        context['achievement'] = format(actual / target * 100, '.2f').replace('.', ',')
        context['risk_appetite'] = _metric_display(target, 'Rp/kWh', 2)
        # Source risk tolerance for this metric declares price BELOW target adverse.
        context['risk_tolerance'] = '< ' + _metric_display(target, 'Rp/kWh', 2)
        for key, value in (('best_case_note', result.best_case_value), ('baseline_case_note', result.baseline_value), ('worst_case_note', result.worst_case_value)):
            context[key] = ('Di bawah target harga jual' if value is not None and Decimal(str(value)) < target else 'Memenuhi target harga jual') if value is not None else 'Belum tersedia'
        worst = result.worst_case_value
        context['outlook_status'] = 'BAHAYA' if worst is not None and Decimal(str(worst)) < target else 'AMAN' if worst is not None else 'BELUM TERSEDIA'
        context['outlook_status_class'] = 'danger' if context['outlook_status'] == 'BAHAYA' else 'safe' if context['outlook_status'] == 'AMAN' else 'neutral'
    # HJR_ACTUAL_STATUS_V1
    if target is not None and target > 0 and actual.is_finite():
        actual_safe = actual >= target
        context["hjr_actual_status"] = "AMAN" if actual_safe else "BAHAYA"
        context["hjr_actual_status_class"] = "safe" if actual_safe else "danger"
    else:
        context["hjr_actual_status"] = "BELUM TERSEDIA"
        context["hjr_actual_status_class"] = "waspada"

    context['conclusion'] = ('HJR dihitung sebagai rasio total pendapatan terhadap total kWh. '
        f"Probabilitas HJR tahunan di bawah target: {result.probability_not_achieve_target}%. "
        'Model memakai inovasi independen untuk kedua sumber; korelasi belum dikalibrasi. '
        'Selisih Rp/kWh belum merupakan kerugian rupiah tanpa volume kWh yang sesuai.')
    return context
