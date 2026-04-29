import json
from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html
from riskproject.admin_site import risk_admin_site
from django.utils.safestring import mark_safe

from .models import (
    MonteCarloKorporatConfig,
    MonteCarloKorporatHistory,
    MonteCarloKorporatResult,
    AIInsightKorporat,
    RiskMetric,
    MonteCarloMetricHistory,
    MultiMetricMonteCarloResult,
    MultiMetricAIInsightKorporat,
)

from .services import (
    run_monte_carlo_for_korporat_item,
    run_multi_metric_monte_carlo_for_korporat_item,
    generate_rule_based_ai_insight_for_result,
    generate_rule_based_ai_insight_for_multi_metric_result,
)

@admin.register(MonteCarloKorporatConfig)
class MonteCarloKorporatConfigAdmin(admin.ModelAdmin):
    list_display = (
        "corporate_risk_item",
        "metric_name",
        "metric_unit",
        "direction",
        "distribution_type",
        "n_simulations",
        "minimum_history_points",
        "is_active",
        "run_button",
    )
    list_filter = ("direction", "distribution_type", "is_active")
    search_fields = (
        "corporate_risk_item__peristiwa_risiko",
        "metric_name",
        "metric_unit",
    )
    autocomplete_fields = ("corporate_risk_item",)

    fieldsets = (
        ("Informasi Utama", {
            "fields": (
                "corporate_risk_item",
                "metric_name",
                "metric_unit",
                "is_active",
            )
        }),
        ("Pengaturan Simulasi", {
            "fields": (
                "direction",
                "distribution_type",
                "n_simulations",
                "minimum_history_points",
            )
        }),
    )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:config_id>/run/",
                self.admin_site.admin_view(self.run_monte_carlo_view),
                name="corporate_risk_montecarlo_run",
            ),
        ]
        return custom_urls + urls

    def run_button(self, obj):
        url = reverse("admin:corporate_risk_montecarlo_run", args=[obj.pk])
        return format_html('<a class="button" href="{}">Jalankan Monte Carlo</a>', url)
    run_button.short_description = "Proses"

    def run_monte_carlo_view(self, request, config_id, *args, **kwargs):
        config = get_object_or_404(MonteCarloKorporatConfig, pk=config_id)

        histories = MonteCarloKorporatHistory.objects.filter(
            corporate_risk_item=config.corporate_risk_item,
            metric_name=config.metric_name,
        ).order_by("tanggal_data")

        if not histories.exists():
            self.message_user(
                request,
                "Belum ada histori Monte Carlo untuk item dan metric ini.",
                level=messages.ERROR,
            )
            return redirect(
                reverse("admin:corporate_risk_montecarlokorporatconfig_change", args=[config.pk])
            )

        forecast_periode = histories.last().periode

        try:
            result = run_monte_carlo_for_korporat_item(
                item=config.corporate_risk_item,
                forecast_periode=forecast_periode,
                months_ahead=9,
            )
            self.message_user(
                request,
                f"Monte Carlo berhasil dijalankan. Result ID: {result.pk}",
                level=messages.SUCCESS,
            )
            return redirect(
                reverse("admin:corporate_risk_montecarlokorporatresult_change", args=[result.pk])
            )
        except Exception as exc:
            self.message_user(
                request,
                f"Gagal menjalankan Monte Carlo: {exc}",
                level=messages.ERROR,
            )
            return redirect(
                reverse("admin:corporate_risk_montecarlokorporatconfig_change", args=[config.pk])
            )

@admin.register(MonteCarloKorporatHistory)
class MonteCarloKorporatHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "corporate_risk_item",
        "periode",
        "tanggal_data",
        "metric_name",
        "metric_value",
        "target_value",
        "created_at",
    )
    list_filter = ("metric_name", "periode")
    search_fields = (
        "corporate_risk_item__peristiwa_risiko",
        "metric_name",
    )
    autocomplete_fields = ("corporate_risk_item",)
    ordering = ("corporate_risk_item", "tanggal_data")

    fieldsets = (
        ("Relasi", {
            "fields": (
                "corporate_risk_item",
                "periode",
            )
        }),
        ("Data Historis", {
            "fields": (
                "tanggal_data",
                "metric_name",
                "metric_value",
                "target_value",
            )
        }),
    )

@admin.register(MonteCarloKorporatResult)
class MonteCarloKorporatResultAdmin(admin.ModelAdmin):
    list_display = (
        "corporate_risk_item",
        "forecast_periode",
        "metric_name",
        "mean_value",
        "p80_value",
        "probability_meet_target",
        "status_hasil",
        "created_at",
        "generate_ai_button",
        "generate_ai_insight_button",
    )
    list_filter = ("forecast_periode", "metric_name", "status_hasil")
    search_fields = (
        "corporate_risk_item__peristiwa_risiko",
        "metric_name",
    )
    autocomplete_fields = ("corporate_risk_item",)
    readonly_fields = (
        "corporate_risk_item",
        "forecast_periode",
        "metric_name",
        "status_hasil",
        "created_at",
        "ringkasan_hasil_html",
        "pemantauan_kemungkinan_html",
        "history_snapshot_html",
        "projection_rows_html",
        "grafik_monte_carlo_html",
        "narasi_analisis_html",
        "ai_insight_html",
    )

    fieldsets = (
        ("Informasi Utama", {
            "fields": (
                "corporate_risk_item",
                "forecast_periode",
                "metric_name",
                "status_hasil",
                "created_at",
            )
        }),
        ("Ringkasan Hasil", {
            "fields": (
                "ringkasan_hasil_html",
            )
        }),
        ("Histori Aktual", {
            "fields": (
                "history_snapshot_html",
            )
        }),
        ("Proyeksi Bulanan Monte Carlo", {
            "fields": (
                "projection_rows_html",
            )
        }),
        ("Pemantauan Tingkat Kemungkinan", {
            "fields": (
                "pemantauan_kemungkinan_html",
            )
        }),
        ("Grafik Monte Carlo", {
            "fields": (
                "grafik_monte_carlo_html",
            )
        }),
        ("Narasi Analisis Sistem", {
            "fields": (
                "narasi_analisis_html",
            )
        }),
        ("AI Insight Korporat", {
            "fields": (
                "ai_insight_html",
            )
        }),
    )

    def has_add_permission(self, request):
        return False

    def _fmt(self, value, digits=3):
        if value is None or value == "":
            return "-"
        try:
            return f"{float(value):,.{digits}f}"
        except Exception:
            return str(value)

    def _summary(self, obj):
        return (obj.simulation_snapshot or {}).get("summary", {})

    def _projection_rows(self, obj):
        return (obj.simulation_snapshot or {}).get("projection_rows", [])

    def ringkasan_hasil_html(self, obj):
        summary = self._summary(obj)

        rows = f"""
        <table style="width:100%; border-collapse:collapse;">
            <thead>
                <tr>
                    <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Item</th>
                    <th style="text-align:right; padding:8px; border-bottom:1px solid #ddd;">Nilai</th>
                </tr>
            </thead>
            <tbody>
                <tr><td style="padding:8px;">Mean Total</td><td style="padding:8px; text-align:right;">{self._fmt(obj.mean_value, 3)}</td></tr>
                <tr><td style="padding:8px;">P50 Total</td><td style="padding:8px; text-align:right;">{self._fmt(obj.p50_value, 3)}</td></tr>
                <tr><td style="padding:8px;">P80 Total</td><td style="padding:8px; text-align:right;">{self._fmt(obj.p80_value, 3)}</td></tr>
                <tr><td style="padding:8px;">P90 Total</td><td style="padding:8px; text-align:right;">{self._fmt(obj.p90_value, 3)}</td></tr>
                <tr><td style="padding:8px;">Min Total</td><td style="padding:8px; text-align:right;">{self._fmt(obj.min_value, 3)}</td></tr>
                <tr><td style="padding:8px;">Max Total</td><td style="padding:8px; text-align:right;">{self._fmt(obj.max_value, 3)}</td></tr>
                <tr><td style="padding:8px;">Aktual YTD</td><td style="padding:8px; text-align:right;">{self._fmt(summary.get("actual_ytd_total"), 3)}</td></tr>
                <tr><td style="padding:8px;">Future Mean Total</td><td style="padding:8px; text-align:right;">{self._fmt(summary.get("future_mean_total"), 3)}</td></tr>
                <tr><td style="padding:8px;">Full Year Expected</td><td style="padding:8px; text-align:right;">{self._fmt(summary.get("full_year_expected"), 3)}</td></tr>
                <tr><td style="padding:8px;">P20 Total</td><td style="padding:8px; text-align:right;">{self._fmt(summary.get("p20_total"), 3)}</td></tr>
                <tr><td style="padding:8px;">P40 Total</td><td style="padding:8px; text-align:right;">{self._fmt(summary.get("p40_total"), 3)}</td></tr>
                <tr><td style="padding:8px;">P60 Total</td><td style="padding:8px; text-align:right;">{self._fmt(summary.get("p60_total"), 3)}</td></tr>
                <tr><td style="padding:8px;">P80 Total</td><td style="padding:8px; text-align:right;">{self._fmt(summary.get("p80_total"), 3)}</td></tr>
            </tbody>
        </table>
        """
        return mark_safe(rows)

    ringkasan_hasil_html.short_description = "Ringkasan Hasil"

    def pemantauan_kemungkinan_html(self, obj):
        summary = self._summary(obj)

        actual_ytd = summary.get("actual_ytd_total")
        p80_total = summary.get("p80_total")
        full_year_expected = summary.get("full_year_expected")

        realisasi_kemungkinan = None
        tingkat_kemungkinan = "-"

        try:
            actual_ytd = float(actual_ytd or 0)
            p80_total = float(p80_total or 0)
            full_year_expected = float(full_year_expected or 0)

            if p80_total > 0:
                realisasi_kemungkinan = (actual_ytd / p80_total) * 100

            if realisasi_kemungkinan is not None:
                if realisasi_kemungkinan <= 20:
                    tingkat_kemungkinan = "20%"
                elif realisasi_kemungkinan <= 40:
                    tingkat_kemungkinan = "40%"
                elif realisasi_kemungkinan <= 60:
                    tingkat_kemungkinan = "60%"
                elif realisasi_kemungkinan <= 80:
                    tingkat_kemungkinan = "80%"
                else:
                    tingkat_kemungkinan = "100%"
        except Exception:
            pass

        rows = f"""
        <table style="width:100%; border-collapse:collapse;">
            <thead>
                <tr>
                    <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Parameter</th>
                    <th style="text-align:right; padding:8px; border-bottom:1px solid #ddd;">Nilai</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td style="padding:8px;">Proyeksi Serangan 2026 (Full Year Expected)</td>
                    <td style="padding:8px; text-align:right;">{self._fmt(full_year_expected, 3)}</td>
                </tr>
                <tr>
                    <td style="padding:8px;">Skenario Konservatif (P80 Total)</td>
                    <td style="padding:8px; text-align:right;">{self._fmt(p80_total, 3)}</td>
                </tr>
                <tr>
                    <td style="padding:8px;">Realisasi YTD</td>
                    <td style="padding:8px; text-align:right;">{self._fmt(actual_ytd, 3)}</td>
                </tr>
                <tr>
                    <td style="padding:8px;">Realisasi Kemungkinan</td>
                    <td style="padding:8px; text-align:right;">{self._fmt(realisasi_kemungkinan, 2)}%</td>
                </tr>
                <tr>
                    <td style="padding:8px;">Tingkat Kemungkinan (ambil batas atas range)</td>
                    <td style="padding:8px; text-align:right; font-weight:700;">{tingkat_kemungkinan}</td>
                </tr>
            </tbody>
        </table>

        <div style="margin-top:12px; padding:12px; background:#f8fafc; border:1px solid #e5e7eb; border-radius:8px;">
            <div><strong>Aturan mapping:</strong></div>
            <div>0–20% → 20%</div>
            <div>20–40% → 40%</div>
            <div>40–60% → 60%</div>
            <div>60–80% → 80%</div>
            <div>&gt;80% → 100%</div>
        </div>
        """
        return mark_safe(rows)

    pemantauan_kemungkinan_html.short_description = "Pemantauan Tingkat Kemungkinan"

    def history_snapshot_html(self, obj):
        history = obj.history_snapshot or []
        if not history:
            return "-"

        rows = []
        for row in history:
            rows.append(f"""
                <tr>
                    <td style="padding:8px; border-bottom:1px solid #eee;">{row.get('periode', '-')}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee;">{row.get('tanggal', '-')}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee; text-align:right;">{self._fmt(row.get('value'), 3)}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee; text-align:right;">{self._fmt(row.get('target'), 3)}</td>
                </tr>
            """)

        html = f"""
        <table style="width:100%; border-collapse:collapse;">
            <thead>
                <tr>
                    <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Periode</th>
                    <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Tanggal</th>
                    <th style="text-align:right; padding:8px; border-bottom:1px solid #ddd;">Actual</th>
                    <th style="text-align:right; padding:8px; border-bottom:1px solid #ddd;">Target</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
        """
        return mark_safe(html)

    history_snapshot_html.short_description = "Histori Aktual"

    def projection_rows_html(self, obj):
        rows_data = self._projection_rows(obj)
        if not rows_data:
            return "-"

        rows = []
        for row in rows_data:
            rows.append(f"""
                <tr>
                    <td style="padding:8px; border-bottom:1px solid #eee;">{row.get('bulan', '-')}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee; text-align:right;">{self._fmt(row.get('mean'), 3)}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee; text-align:right;">{self._fmt(row.get('p20'), 3)}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee; text-align:right;">{self._fmt(row.get('p40'), 3)}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee; text-align:right;">{self._fmt(row.get('p60'), 3)}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee; text-align:right;">{self._fmt(row.get('p80'), 3)}</td>
                </tr>
            """)

        html = f"""
        <table style="width:100%; border-collapse:collapse;">
            <thead>
                <tr>
                    <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Bulan</th>
                    <th style="text-align:right; padding:8px; border-bottom:1px solid #ddd;">Proyeksi</th>
                    <th style="text-align:right; padding:8px; border-bottom:1px solid #ddd;">P20</th>
                    <th style="text-align:right; padding:8px; border-bottom:1px solid #ddd;">P40</th>
                    <th style="text-align:right; padding:8px; border-bottom:1px solid #ddd;">P60</th>
                    <th style="text-align:right; padding:8px; border-bottom:1px solid #ddd;">P80</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
        """
        return mark_safe(html)

    projection_rows_html.short_description = "Proyeksi Bulanan"

    def grafik_monte_carlo_html(self, obj):
        history = obj.history_snapshot or []
        projection_rows = (obj.simulation_snapshot or {}).get("projection_rows", [])

        if not history and not projection_rows:
            return "-"

        history_labels = [row.get("periode", "-") for row in history]
        history_values = [float(row.get("value") or 0) for row in history]

        projection_labels = [row.get("bulan", "-") for row in projection_rows]
        projection_mean = [float(row.get("mean") or 0) for row in projection_rows]
        projection_p20 = [float(row.get("p20") or 0) for row in projection_rows]
        projection_p80 = [float(row.get("p80") or 0) for row in projection_rows]

        labels = history_labels + projection_labels
        actual_series = history_values + [None] * len(projection_labels)
        mean_series = [None] * len(history_labels) + projection_mean
        p20_series = [None] * len(history_labels) + projection_p20
        p80_series = [None] * len(history_labels) + projection_p80

        chart_id = f"mc-chart-{obj.pk}"

        return mark_safe(f"""
        <div style="width:100%; max-width:1200px; padding:12px 0;">
            <canvas id="{chart_id}" style="width:100%; height:420px;"></canvas>
        </div>

        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script>
        (function() {{
            const labels = {json.dumps(labels)};
            const actualSeries = {json.dumps(actual_series)};
            const meanSeries = {json.dumps(mean_series)};
            const p20Series = {json.dumps(p20_series)};
            const p80Series = {json.dumps(p80_series)};

            const canvas = document.getElementById("{chart_id}");
            if (!canvas) return;

            const existing = Chart.getChart("{chart_id}");
            if (existing) {{
                existing.destroy();
            }}

            const ctx = canvas.getContext("2d");

            new Chart(ctx, {{
                type: "line",
                data: {{
                    labels: labels,
                    datasets: [
                        {{
                            label: "Actual",
                            data: actualSeries,
                            borderColor: "#1f77b4",
                            backgroundColor: "#1f77b4",
                            borderWidth: 2,
                            tension: 0.25,
                            spanGaps: false
                        }},
                        {{
                            label: "Proyeksi Mean",
                            data: meanSeries,
                            borderColor: "#2ca02c",
                            backgroundColor: "#2ca02c",
                            borderWidth: 2,
                            tension: 0.25,
                            spanGaps: false
                        }},
                        {{
                            label: "P20",
                            data: p20Series,
                            borderColor: "#ff7f0e",
                            backgroundColor: "#ff7f0e",
                            borderWidth: 1,
                            borderDash: [6, 4],
                            tension: 0.25,
                            spanGaps: false
                        }},
                        {{
                            label: "P80",
                            data: p80Series,
                            borderColor: "#d62728",
                            backgroundColor: "#d62728",
                            borderWidth: 1,
                            borderDash: [6, 4],
                            tension: 0.25,
                            spanGaps: false
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{
                            position: "top"
                        }},
                        title: {{
                            display: true,
                            text: "Histori Aktual dan Proyeksi Monte Carlo"
                        }}
                    }},
                    scales: {{
                        y: {{
                            beginAtZero: true
                        }}
                    }}
                }}
            }});
        }})();
        </script>
        """)
    grafik_monte_carlo_html.short_description = "Grafik Monte Carlo"

    def narasi_analisis_html(self, obj):
        summary = self._summary(obj)

        actual_ytd = float(summary.get("actual_ytd_total") or 0)
        p80_total = float(summary.get("p80_total") or 0)
        full_year_expected = float(summary.get("full_year_expected") or 0)

        realization_percent = 0.0
        if p80_total > 0:
            realization_percent = (actual_ytd / p80_total) * 100

        if realization_percent <= 20:
            tingkat = "masih berada pada level rendah"
        elif realization_percent <= 40:
            tingkat = "masih berada pada level moderat"
        elif realization_percent <= 60:
            tingkat = "sudah berada pada level cukup tinggi"
        elif realization_percent <= 80:
            tingkat = "berada pada level tinggi"
        else:
            tingkat = "berada pada level sangat tinggi"

        html = f"""
        <div style="margin-top:20px; padding:15px; background:#f8f9fa; border-radius:8px; border:1px solid #ddd;">
        <h3 style="margin-bottom:10px;">Analisis Proyeksi Risiko Siber</h3>

        <p>
            Berdasarkan hasil simulasi Monte Carlo, proyeksi ancaman/incident cyber terhadap sistem IT dan OT
            menunjukkan bahwa eksposur risiko {tingkat}. Full year expected tercatat sebesar
            <strong>{self._fmt(full_year_expected, 3)}</strong>, dengan skenario konservatif (P80)
            sebesar <strong>{self._fmt(p80_total, 3)}</strong>.
        </p>

        <p>
            Realisasi year-to-date saat ini sebesar <strong>{self._fmt(actual_ytd, 3)}</strong> atau
            <strong>{self._fmt(realization_percent, 2)}</strong>% terhadap skenario konservatif.
            Hal ini menunjukkan bahwa meskipun ancaman telah terjadi, posisi saat ini masih perlu dibaca
            sebagai sinyal kewaspadaan untuk sisa periode tahun berjalan.
        </p>

        <p>
            Dengan target perusahaan yang tidak mentoleransi insiden sampai merusak sistem, maka fokus utama
            mitigasi bukan hanya menurunkan jumlah threat, tetapi memastikan threat tersebut tidak berkembang
            menjadi insiden yang mengganggu operasional atau merusak sistem kritikal.
        </p>

        <p><strong>Fokus mitigasi yang direkomendasikan:</strong></p>
        <ul>
            <li>Penguatan deteksi dini dan monitoring ancaman siber</li>
            <li>Peningkatan respons insiden dan containment pada sistem IT/OT</li>
            <li>Penguatan kontrol keamanan pada aset kritikal</li>
            <li>Pencegahan eskalasi ancaman menjadi gangguan operasional</li>
        </ul>
        </div>
        """
        return mark_safe(html)

    narasi_analisis_html.short_description = "Narasi Analisis Sistem"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:result_id>/generate-ai-insight/",
                self.admin_site.admin_view(self.generate_ai_insight_view),
                name="corporate_risk_generate_ai_insight",
            ),
        ]
        return custom_urls + urls

    def generate_ai_button(self, obj):
        url = reverse("admin:corporate_risk_generate_ai_insight", args=[obj.pk])
        return format_html('<a class="button" href="{}">Generate AI Insight</a>', url)
    generate_ai_button.short_description = "AI Insight"

    def generate_ai_insight_view(self, request, result_id, *args, **kwargs):
        result = get_object_or_404(MonteCarloKorporatResult, pk=result_id)
        try:
            insight = generate_rule_based_ai_insight_for_result(result)
            self.message_user(
                request,
                f"AI Insight berhasil dibuat. Insight ID: {insight.pk}",
                level=messages.SUCCESS,
            )
        except Exception as exc:
            self.message_user(
                request,
                f"Gagal generate AI Insight: {exc}",
                level=messages.ERROR,
            )
        return redirect(
            reverse("admin:corporate_risk_montecarlokorporatresult_change", args=[result.pk])
        )

    
    def ai_insight_html(self, obj):
        insight = AIInsightKorporat.objects.filter(monte_carlo_result=obj).first()
        if not insight:
            return mark_safe(
                '<div style="padding:12px; background:#fff8e1; border:1px solid #f0d98a; border-radius:8px;">'
                'AI Insight belum dibuat. Klik tombol <strong>Generate AI Insight</strong> pada daftar hasil Monte Carlo.'
                '</div>'
            )

        html = f"""
        <div style="padding:15px; background:#f8f9fa; border-radius:8px; border:1px solid #ddd;">
        <h3>Executive Summary</h3>
        <p>{insight.executive_summary.replace(chr(10), '<br>')}</p>

        <h3 style="margin-top:15px;">Key Drivers</h3>
        <p>{insight.key_drivers.replace(chr(10), '<br>')}</p>

        <h3 style="margin-top:15px;">Recommended Actions</h3>
        <p>{insight.recommended_actions.replace(chr(10), '<br>')}</p>
        </div>
        """
        return mark_safe(html)

    ai_insight_html.short_description = "AI Insight Korporat"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:result_id>/generate-ai-insight-multi-metric/",
                self.admin_site.admin_view(self.generate_ai_insight_multi_metric_view),
                name="corporate_risk_generate_ai_insight_multi_metric",
            ),
        ]
        return custom_urls + urls


    def generate_ai_insight_button(self, obj):
        url = reverse(
            "admin:corporate_risk_generate_ai_insight_multi_metric",
            args=[obj.pk],
        )
        return format_html('<a class="button" href="{}">Generate AI Insight</a>', url)

    generate_ai_insight_button.short_description = "AI Insight"


    def generate_ai_insight_multi_metric_view(self, request, result_id, *args, **kwargs):
        result = get_object_or_404(MultiMetricMonteCarloResult, pk=result_id)

        try:
            insight = generate_rule_based_ai_insight_for_multi_metric_result(result)
            self.message_user(
                request,
                f"AI Insight Multi Metric berhasil dibuat. Insight ID: {insight.pk}",
                level=messages.SUCCESS,
            )
        except Exception as exc:
            self.message_user(
                request,
                f"Gagal generate AI Insight Multi Metric: {exc}",
                level=messages.ERROR,
            )

        return redirect(
            reverse(
                "admin:corporate_risk_multimetricmontecarloresult_change",
                args=[result.pk],
            )
        )


@admin.register(AIInsightKorporat)
class AIInsightKorporatAdmin(admin.ModelAdmin):
    list_display = (
        "corporate_risk_item",
        "monte_carlo_result",
        "created_at",
    )
    search_fields = (
        "corporate_risk_item__peristiwa_risiko",
        "executive_summary",
    )
    autocomplete_fields = ("corporate_risk_item", "monte_carlo_result")
    readonly_fields = ("created_at",)

    fieldsets = (
        ("Relasi", {
            "fields": (
                "corporate_risk_item",
                "monte_carlo_result",
                "created_at",
            )
        }),
        ("Insight", {
            "fields": (
                "executive_summary",
                "key_drivers",
                "recommended_actions",
            )
        }),
    )


@admin.register(RiskMetric)
class RiskMetricAdmin(admin.ModelAdmin):
    list_display = (
        "corporate_risk_item",
        "name",
        "unit",
        "direction",
        "weight",
        "is_active",
    )
    list_filter = ("direction", "is_active")
    search_fields = (
        "corporate_risk_item__peristiwa_risiko",
        "name",
        "unit",
    )
    autocomplete_fields = ("corporate_risk_item",)
    ordering = ("corporate_risk_item", "name")

    fieldsets = (
        ("Relasi Risiko", {
            "fields": ("corporate_risk_item",)
        }),
        ("Informasi Metric", {
            "fields": (
                "name",
                "unit",
                "direction",
                "weight",
                "is_active",
            )
        }),
    )


@admin.register(MonteCarloMetricHistory)
class MonteCarloMetricHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "metric",
        "periode",
        "tanggal_data",
        "metric_value",
        "target_value",
        "created_at",
    )
    list_filter = (
        "metric",
        "periode",
    )
    search_fields = (
        "metric__name",
        "metric__corporate_risk_item__peristiwa_risiko",
    )
    autocomplete_fields = (
        "metric",
        "periode",
    )
    ordering = (
        "metric",
        "tanggal_data",
    )

    fieldsets = (
        ("Relasi", {
            "fields": (
                "metric",
                "periode",
            )
        }),
        ("Data Historis", {
            "fields": (
                "tanggal_data",
                "metric_value",
                "target_value",
                "keterangan",
            )
        }),
    )


@admin.register(MultiMetricMonteCarloResult)
class MultiMetricMonteCarloResultAdmin(admin.ModelAdmin):
    list_display = (
        "corporate_risk_item",
        "forecast_periode",
        "composite_score",
        "p80_score",
        "status_hasil",
        "created_at",
    )

    list_filter = (
        "forecast_periode",
        "status_hasil",
    )

    search_fields = (
        "corporate_risk_item__peristiwa_risiko",
    )

    autocomplete_fields = (
        "corporate_risk_item",
        "forecast_periode",
    )

    readonly_fields = (
        "executive_summary_html",
        "metric_contribution_html",
        "composite_interpretation_html",
        "multi_metric_history_rows_html",
        "multi_metric_projection_rows_html",
        "multi_metric_chart_html",
        "composite_score",
        "p80_score",
        "status_hasil",
        "metric_snapshot_html",
        "multi_metric_ai_insight_html",
        "created_at",
    )

    fieldsets = (
        ("Executive Summary", {
            "fields": ("executive_summary_html",)
        }),
        ("Informasi Utama", {
            "fields": (
                "corporate_risk_item",
                "forecast_periode",
                "scenario_percentile",
                "composite_score",
                "p80_score",
                "status_hasil",
                "created_at",
            )
        }),
        ("Kontribusi Metric", {
            "fields": ("metric_contribution_html",)
        }),
        ("Narasi Analisis Sistem", {
            "fields": ("composite_interpretation_html",)
        }),
        ("Histori Aktual Multi Metric", {
            "fields": ("multi_metric_history_rows_html",)
        }),
        ("Proyeksi Bulanan Multi Metric", {
            "fields": ("multi_metric_projection_rows_html",)
        }),
        ("Grafik Multi Metric Monte Carlo", {
            "fields": ("multi_metric_chart_html",)
        }),
        ("Detail Metric", {
            "fields": ("metric_snapshot_html",)
        }),
        ("AI Insight Multi Metric", {
            "fields": ("multi_metric_ai_insight_html",)
        }),
    )

    def has_add_permission(self, request):
        return True

    def _fmt(self, value, digits=2):
        try:
            return f"{float(value):,.{digits}f}"
        except Exception:
            return "-"

    def save_model(self, request, obj, form, change):
        result = run_multi_metric_monte_carlo_for_korporat_item(
            item=obj.corporate_risk_item,
            forecast_periode=obj.forecast_periode,
            months_ahead=9,
            n_simulations=1000,
            scenario_percentile=obj.scenario_percentile,
        )

        obj.composite_score = result.composite_score
        obj.p80_score = result.p80_score
        obj.status_hasil = result.status_hasil
        obj.metric_snapshot = result.metric_snapshot
        obj.simulation_snapshot = result.simulation_snapshot

        super().save_model(request, obj, form, change)

    def multi_metric_history_rows_html(self, obj):
        snapshot = obj.simulation_snapshot or {}
        rows = snapshot.get("history_rows", [])

        metrics = (obj.metric_snapshot or {}).get("metrics", [])
        metric_names = [m.get("metric_name") for m in metrics]

        if not rows:
            return mark_safe(
                "<div style='padding:12px;background:#fff3cd;border:1px solid #ffeeba;border-radius:6px;'>"
                "Histori aktual multi metric belum tersedia. Generate ulang Multi Metric Monte Carlo Result."
                "</div>"
            )

        header_metric_cols = "".join([
            f'<th style="padding:8px;border:1px solid #ddd;text-align:right;">{name}</th>'
            for name in metric_names
        ])

        table_rows = []

        for row in rows:
            metric_values = {
                item.get("metric_name"): item
                for item in row.get("metric_values", [])
            }

            metric_cols = ""

            for name in metric_names:
                item = metric_values.get(name, {})
                metric_cols += f"""
                    <td style="padding:8px;border:1px solid #ddd;text-align:right;">
                        {self._fmt(item.get("actual"), 2)}
                    </td>
                """

            table_rows.append(f"""
                <tr>
                    <td style="padding:8px;border:1px solid #ddd;">{row.get("periode") or "-"}</td>
                    <td style="padding:8px;border:1px solid #ddd;">{row.get("tanggal") or "-"}</td>
                    {metric_cols}
                    <td style="padding:8px;border:1px solid #ddd;text-align:right;font-weight:bold;">
                        {self._fmt(row.get("actual_score"), 2)}
                    </td>
                </tr>
            """)

        html = f"""
        <table style="border-collapse:collapse;width:100%;font-size:13px;">
            <thead>
                <tr style="background:#f3f4f6;">
                    <th style="padding:8px;border:1px solid #ddd;">Periode</th>
                    <th style="padding:8px;border:1px solid #ddd;">Tanggal</th>
                    {header_metric_cols}
                    <th style="padding:8px;border:1px solid #ddd;text-align:right;">Actual Composite Score</th>
                </tr>
            </thead>
            <tbody>
                {''.join(table_rows)}
            </tbody>
        </table>
        """
        return mark_safe(html)

    multi_metric_history_rows_html.short_description = "Histori Aktual Multi Metric"


    def multi_metric_projection_rows_html(self, obj):
        snapshot = obj.simulation_snapshot or {}
        rows = snapshot.get("projection_rows", [])

        if not rows:
            return mark_safe(
                "<div style='padding:12px;background:#fff3cd;border:1px solid #ffeeba;border-radius:6px;'>"
                "Proyeksi bulanan belum tersedia. Generate ulang Multi Metric Monte Carlo Result."
                "</div>"
            )

        table_rows = []

        for row in rows:
            bulan = row.get("bulan") or f"Bulan-{row.get('bulan_index')}"
            table_rows.append(f"""
                <tr>
                    <td style="padding:8px;border:1px solid #ddd;">{bulan}</td>
                    <td style="padding:8px;border:1px solid #ddd;text-align:right;">{self._fmt(row.get("mean_score"), 2)}</td>
                    <td style="padding:8px;border:1px solid #ddd;text-align:right;">{self._fmt(row.get("p20_score"), 2)}</td>
                    <td style="padding:8px;border:1px solid #ddd;text-align:right;">{self._fmt(row.get("p40_score"), 2)}</td>
                    <td style="padding:8px;border:1px solid #ddd;text-align:right;">{self._fmt(row.get("p60_score"), 2)}</td>
                    <td style="padding:8px;border:1px solid #ddd;text-align:right;font-weight:bold;">{self._fmt(row.get("p80_score"), 2)}</td>
                    <td style="padding:8px;border:1px solid #ddd;">{row.get("dominant_metric") or "-"}</td>
                </tr>
            """)

        html = f"""
        <table style="border-collapse:collapse;width:100%;font-size:13px;">
            <thead>
                <tr style="background:#f3f4f6;">
                    <th style="padding:8px;border:1px solid #ddd;">Bulan</th>
                    <th style="padding:8px;border:1px solid #ddd;text-align:right;">Mean Score</th>
                    <th style="padding:8px;border:1px solid #ddd;text-align:right;">P20</th>
                    <th style="padding:8px;border:1px solid #ddd;text-align:right;">P40</th>
                    <th style="padding:8px;border:1px solid #ddd;text-align:right;">P60</th>
                    <th style="padding:8px;border:1px solid #ddd;text-align:right;">P80</th>
                    <th style="padding:8px;border:1px solid #ddd;">Metric Dominan</th>
                </tr>
            </thead>
            <tbody>
                {''.join(table_rows)}
            </tbody>
        </table>
        """
        return mark_safe(html)

    multi_metric_projection_rows_html.short_description = "Proyeksi Bulanan Multi Metric"

    def multi_metric_chart_html(self, obj):
        snapshot = obj.simulation_snapshot or {}
        chart_series = snapshot.get("chart_series", {})

        labels = chart_series.get("labels", [])
        mean_values = chart_series.get("mean", [])
        p20_values = chart_series.get("p20", [])
        p40_values = chart_series.get("p40", [])
        p60_values = chart_series.get("p60", [])
        p80_values = chart_series.get("p80", [])

        if not labels:
            return mark_safe(
                "<div style='padding:12px;background:#fff3cd;border:1px solid #ffeeba;border-radius:6px;'>"
                "Data grafik belum tersedia. Generate ulang Multi Metric Monte Carlo Result."
                "</div>"
            )

        all_values = []
        for series in [mean_values, p20_values, p40_values, p60_values, p80_values]:
            all_values.extend([float(v) for v in series if v is not None])

        if all_values:
            min_val = min(all_values)
            max_val = max(all_values)
            padding = max((max_val - min_val) * 0.35, 0.25)
            y_min = max(0, min_val - padding)
            y_max = min(100, max_val + padding)
        else:
            y_min = 0
            y_max = 100

        chart_id = f"multiMetricChart_{obj.id}"

        html = f"""
        <div style="width:100%;max-width:1200px;height:480px;">
            <canvas id="{chart_id}"></canvas>
        </div>

        <div style="margin-top:10px;padding:10px;background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;font-size:13px;">
            Grafik menggunakan <strong>auto zoom</strong> pada sumbu Y agar perbedaan kecil antar percentile tetap terlihat.
            Rentang score ditampilkan dari <strong>{self._fmt(y_min, 2)}</strong> sampai <strong>{self._fmt(y_max, 2)}</strong>.
        </div>

        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script>
        (function() {{
            const canvas = document.getElementById("{chart_id}");
            if (!canvas) return;

            if (typeof Chart === "undefined") return;

            const existing = Chart.getChart("{chart_id}");
            if (existing) {{
                existing.destroy();
            }}

            new Chart(canvas, {{
                type: "line",
                data: {{
                    labels: {json.dumps(labels)},
                    datasets: [
                        {{
                            label: "P80",
                            data: {json.dumps(p80_values)},
                            borderWidth: 2,
                            borderDash: [6, 4],
                            tension: 0.25,
                            pointRadius: 4
                        }},
                        {{
                            label: "P60",
                            data: {json.dumps(p60_values)},
                            borderWidth: 2,
                            borderDash: [4, 4],
                            tension: 0.25,
                            pointRadius: 3
                        }},
                        {{
                            label: "Mean Score",
                            data: {json.dumps(mean_values)},
                            borderWidth: 3,
                            tension: 0.25,
                            pointRadius: 5
                        }},
                        {{
                            label: "P40",
                            data: {json.dumps(p40_values)},
                            borderWidth: 2,
                            borderDash: [4, 4],
                            tension: 0.25,
                            pointRadius: 3
                        }},
                        {{
                            label: "P20",
                            data: {json.dumps(p20_values)},
                            borderWidth: 2,
                            borderDash: [6, 4],
                            tension: 0.25,
                            pointRadius: 4
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {{
                        mode: "index",
                        intersect: false
                    }},
                    plugins: {{
                        legend: {{
                            position: "bottom"
                        }},
                        title: {{
                            display: true,
                            text: "Proyeksi Composite Risk Score Multi Metric"
                        }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    let value = context.parsed.y;
                                    return context.dataset.label + ": " + value.toFixed(4);
                                }}
                            }}
                        }}
                    }},
                    scales: {{
                        y: {{
                            min: {y_min},
                            max: {y_max},
                            title: {{
                                display: true,
                                text: "Composite Risk Score"
                            }}
                        }}
                    }}
                }}
            }});
        }})();
        </script>
        """

        return mark_safe(html)

    multi_metric_chart_html.short_description = "Grafik Multi Metric Monte Carlo"

    def executive_summary_html(self, obj):
        if not obj or not obj.pk:
            return "-"

        metrics = (obj.metric_snapshot or {}).get("metrics", [])
        if not metrics:
            return "-"

        top_metric = max(metrics, key=lambda x: float(x.get("mean_score") or 0))

        html = f"""
        <div style="padding:16px; background:#f8fafc; border:1px solid #e5e7eb; border-radius:10px;">
            <h3 style="margin-top:0;">Ringkasan Eksekutif Risiko</h3>
            <p>
                Risiko <strong>{obj.corporate_risk_item}</strong> untuk periode forecast
                <strong>{obj.forecast_periode}</strong> berada pada level
                <strong>{obj.status_hasil}</strong>.
            </p>
            <p>
                Composite Risk Score tercatat sebesar
                <strong>{self._fmt(obj.composite_score, 2)}</strong>,
                dengan skenario konservatif P80 sebesar
                <strong>{self._fmt(obj.p80_score, 2)}</strong>.
            </p>
            <p>
                Faktor dominan yang memengaruhi risiko adalah
                <strong>{top_metric.get("metric_name", "-")}</strong>.
            </p>
        </div>
        """
        return mark_safe(html)

    executive_summary_html.short_description = "Ringkasan Eksekutif"

    def metric_contribution_html(self, obj):
        if not obj or not obj.pk:
            return "-"

        metrics = (obj.metric_snapshot or {}).get("metrics", [])
        if not metrics:
            return "-"

        total = sum(
            float(m.get("mean_score") or 0) * float(m.get("weight_ratio") or 0)
            for m in metrics
        )

        rows = []
        for m in metrics:
            contribution = float(m.get("mean_score") or 0) * float(m.get("weight_ratio") or 0)
            percent = (contribution / total * 100) if total > 0 else 0

            rows.append(f"""
                <tr>
                    <td style="padding:8px; border-bottom:1px solid #eee;">{m.get("metric_name", "-")}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee; text-align:right;">{self._fmt(m.get("weight"), 2)}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee; text-align:right;">{self._fmt(m.get("mean_score"), 2)}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee; text-align:right; font-weight:700;">{self._fmt(percent, 2)}%</td>
                </tr>
            """)

        html = f"""
        <table style="width:100%; border-collapse:collapse;">
            <thead>
                <tr>
                    <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Metric</th>
                    <th style="text-align:right; padding:8px; border-bottom:1px solid #ddd;">Bobot</th>
                    <th style="text-align:right; padding:8px; border-bottom:1px solid #ddd;">Score</th>
                    <th style="text-align:right; padding:8px; border-bottom:1px solid #ddd;">Kontribusi</th>
                </tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
        """
        return mark_safe(html)

    metric_contribution_html.short_description = "Kontribusi Metric"

    def composite_interpretation_html(self, obj):
        if not obj or not obj.pk:
            return "-"

        metrics = (obj.metric_snapshot or {}).get("metrics", [])
        if not metrics:
            return "-"

        top_metric = max(metrics, key=lambda x: float(x.get("mean_score") or 0))
        top_name = top_metric.get("metric_name", "-")

        html = f"""
        <div style="padding:16px; background:#fff; border:1px solid #ddd; border-radius:10px;">
            <h3 style="margin-top:0;">Narasi Analisis Sistem</h3>
            <p>
                Berdasarkan simulasi multi-metric Monte Carlo, risiko berada pada level
                <strong>{obj.status_hasil}</strong>. Kondisi ini terutama dipengaruhi oleh
                metric <strong>{top_name}</strong> sebagai driver utama.
            </p>
            <p>
                Nilai P80 Composite Score sebesar <strong>{self._fmt(obj.p80_score, 2)}</strong>
                menunjukkan skenario konservatif yang perlu menjadi perhatian dalam pengambilan keputusan.
            </p>
            <p><strong>Fokus tindak lanjut:</strong></p>
            <ul>
                <li>Prioritaskan mitigasi pada metric dengan kontribusi risiko terbesar.</li>
                <li>Lakukan monitoring bulanan atas tren historis dan realisasi aktual.</li>
                <li>Bandingkan hasil simulasi dengan risk appetite dan batas toleransi perusahaan.</li>
                <li>Gunakan P80 sebagai dasar kewaspadaan manajemen.</li>
            </ul>
        </div>
        """
        return mark_safe(html)

    composite_interpretation_html.short_description = "Narasi Analisis Sistem"

    def metric_snapshot_html(self, obj):
        metrics = (obj.metric_snapshot or {}).get("metrics", [])
        if not metrics:
            return "-"

        rows = []

        for row in metrics:
            rows.append(f"""
                <tr>
                    <td style="padding:8px; border-bottom:1px solid #eee;">{row.get("metric_name", "-")}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee;">{row.get("unit", "-")}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee;">{row.get("direction", "-")}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee; text-align:right;">{self._fmt(row.get("weight"), 2)}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee; text-align:right;">{self._fmt(row.get("last_actual"), 2)}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee; text-align:right;">{self._fmt(row.get("full_year_expected"), 2)}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee; text-align:right;">{self._fmt(row.get("mean_score"), 2)}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee; text-align:right;">{self._fmt(row.get("p80_score"), 2)}</td>
                </tr>
            """)

        html = f"""
        <table style="width:100%; border-collapse:collapse;">
            <thead>
                <tr>
                    <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Metric</th>
                    <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Unit</th>
                    <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Direction</th>
                    <th style="text-align:right; padding:8px; border-bottom:1px solid #ddd;">Bobot</th>
                    <th style="text-align:right; padding:8px; border-bottom:1px solid #ddd;">Last Actual</th>
                    <th style="text-align:right; padding:8px; border-bottom:1px solid #ddd;">Full Year Expected</th>
                    <th style="text-align:right; padding:8px; border-bottom:1px solid #ddd;">Mean Score</th>
                    <th style="text-align:right; padding:8px; border-bottom:1px solid #ddd;">P80 Score</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
        """
        return mark_safe(html)

    metric_snapshot_html.short_description = "Detail Metric"

    def multi_metric_ai_insight_html(self, obj):
        insight = MultiMetricAIInsightKorporat.objects.filter(
            multi_metric_result=obj
        ).first()

        if not insight:
            return mark_safe(
                '<div style="padding:12px; background:#fff8e1; border:1px solid #f0d98a; border-radius:8px;">'
                'AI Insight Multi Metric belum dibuat. Klik tombol <strong>Generate AI Insight</strong> pada daftar hasil.'
                '</div>'
            )

        html = f"""
        <div style="padding:15px; background:#f8f9fa; border-radius:8px; border:1px solid #ddd;">
            <h3>Executive Summary</h3>
            <p>{insight.executive_summary.replace(chr(10), '<br>')}</p>

            <h3 style="margin-top:15px;">Key Findings</h3>
            <p>{insight.key_findings.replace(chr(10), '<br>')}</p>

            <h3 style="margin-top:15px;">Recommended Actions</h3>
            <p>{insight.recommended_actions.replace(chr(10), '<br>')}</p>
        </div>
        """
        return mark_safe(html)

    multi_metric_ai_insight_html.short_description = "AI Insight Multi Metric"


@admin.register(MultiMetricAIInsightKorporat)
class MultiMetricAIInsightKorporatAdmin(admin.ModelAdmin):
    list_display = (
        "multi_metric_result",
        "created_at",
    )
    search_fields = (
        "executive_summary",
        "key_findings",
        "recommended_actions",
    )
    autocomplete_fields = (
        "multi_metric_result",
    )
    readonly_fields = (
        "created_at",
    )

try:
    risk_admin_site.register(MonteCarloKorporatConfig, MonteCarloKorporatConfigAdmin)
except Exception:
    pass

try:
    risk_admin_site.register(MonteCarloKorporatHistory, MonteCarloKorporatHistoryAdmin)
except Exception:
    pass

try:
    risk_admin_site.register(MonteCarloKorporatResult, MonteCarloKorporatResultAdmin)
except Exception:
    pass

try:
    risk_admin_site.register(AIInsightKorporat, AIInsightKorporatAdmin)
except Exception:
    pass

try:
    risk_admin_site.register(MonteCarloMetricHistory, MonteCarloMetricHistoryAdmin)
except Exception:
    pass

try:
    risk_admin_site.register(RiskMetric, RiskMetricAdmin)
except Exception:
    pass

try:
    risk_admin_site.register(MultiMetricMonteCarloResult, MultiMetricMonteCarloResultAdmin)
except Exception:
    pass

try:
    risk_admin_site.register(MultiMetricAIInsightKorporat, MultiMetricAIInsightKorporatAdmin)
except Exception:
    pass