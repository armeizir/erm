import json
from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import escape, format_html
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
    recommend_monte_carlo_distribution,
)


def risk_item_label_html(item):
    if not item:
        return "-"
    title = item.get_display_label() if hasattr(item, "get_display_label") else str(item)
    short = getattr(item, "short_label", None) or title
    summary = getattr(item, "summary", None)
    return format_html(
        '<span title="{}">{}</span><br><span class="helptext">{}</span>',
        title,
        short,
        summary or "",
    )


class MonteCarloDistributionRecommendationForm(forms.Form):
    distribution_type = forms.ChoiceField(
        label="Distribusi yang digunakan",
        choices=MonteCarloKorporatConfig.DISTRIBUTION_CHOICES,
    )


class MultiMetricMonteCarloResultForm(forms.ModelForm):
    class Meta:
        model = MultiMetricMonteCarloResult
        fields = "__all__"

    def _metric_history_readiness_errors(self, item, forecast_periode):
        if not item or not forecast_periode:
            return []

        metrics = RiskMetric.objects.filter(corporate_risk_item=item, is_active=True).order_by("name")
        if not metrics.exists():
            return ["Belum ada Risk Metric aktif untuk item risiko korporat ini."]

        errors = []
        forecast_end = getattr(forecast_periode, "tanggal_selesai", None)
        for metric in metrics:
            histories = MonteCarloMetricHistory.objects.filter(metric=metric)
            if forecast_end:
                histories = histories.filter(tanggal_data__lte=forecast_end)
            history_count = histories.count()
            if history_count < 3:
                errors.append(f"{metric.name}: {history_count}/3 periode")
        return errors

    def _aggregate_recommendation(self, item, forecast_periode):
        if not item:
            return ""
        counts = {}
        metrics = RiskMetric.objects.filter(corporate_risk_item=item, is_active=True)
        for metric in metrics:
            histories = MonteCarloMetricHistory.objects.filter(metric=metric)
            if forecast_periode and getattr(forecast_periode, "tanggal_selesai", None):
                histories = histories.filter(tanggal_data__lte=forecast_periode.tanggal_selesai)
            values = list(histories.order_by("tanggal_data", "id").values_list("metric_value", flat=True))
            recommendation = recommend_monte_carlo_distribution(values)
            recommended = recommendation.get("recommended") or "empirical"
            counts[recommended] = counts.get(recommended, 0) + 1
        if not counts:
            return ""
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

    def clean(self):
        cleaned_data = super().clean()
        history_errors = self._metric_history_readiness_errors(
            cleaned_data.get("corporate_risk_item"),
            cleaned_data.get("forecast_periode"),
        )
        if history_errors:
            raise forms.ValidationError(
                "Data histori belum cukup untuk menjalankan Multi Metric Monte Carlo. "
                "Lengkapi minimal 3 periode histori untuk setiap Risk Metric aktif melalui "
                f"panel Input Histori di Profil Risiko Korporat. Detail: {'; '.join(history_errors)}"
            )

        selected = cleaned_data.get("distribution_type") or ""
        justification = (cleaned_data.get("selected_distribution_justification") or "").strip()
        recommended = (
            self.instance.recommended_distribution
            or self._aggregate_recommendation(
                cleaned_data.get("corporate_risk_item"),
                cleaned_data.get("forecast_periode"),
            )
        )

        if selected and recommended and selected != recommended and not justification:
            raise forms.ValidationError(
                "Justifikasi wajib diisi jika memilih model distribusi yang berbeda dari rekomendasi sistem."
            )

        return cleaned_data


@admin.register(MonteCarloKorporatConfig)
class MonteCarloKorporatConfigAdmin(admin.ModelAdmin):
    list_display = (
        "corporate_risk_item_display",
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

    @admin.display(description="Item Risiko Korporat", ordering="corporate_risk_item__no_item")
    def corporate_risk_item_display(self, obj):
        return risk_item_label_html(obj.corporate_risk_item)

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
        url = reverse(f"{self.admin_site.name}:corporate_risk_montecarlo_run", args=[obj.pk])
        return format_html('<a class="button" href="{}">Jalankan Monte Carlo</a>', url)
    run_button.short_description = "Proses"

    def has_module_permission(self, request):
        return bool(request.user and request.user.is_active and request.user.is_staff)

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_active and request.user.is_staff)

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
                reverse(f"{self.admin_site.name}:corporate_risk_montecarlokorporatconfig_change", args=[config.pk])
            )

        forecast_periode = histories.last().periode
        history_values = [h.metric_value for h in histories]
        recommendation = recommend_monte_carlo_distribution(history_values)
        recommended_distribution = recommendation.get("recommended") or config.distribution_type

        if request.method != "POST":
            form = MonteCarloDistributionRecommendationForm(
                initial={"distribution_type": recommended_distribution},
            )
            context = {
                **self.admin_site.each_context(request),
                "title": "Rekomendasi Model Distribusi Monte Carlo",
                "opts": self.model._meta,
                "config": config,
                "histories": histories,
                "recommendation": recommendation,
                "form": form,
                "change_url": reverse(
                    f"{self.admin_site.name}:corporate_risk_montecarlokorporatconfig_change",
                    args=[config.pk],
                ),
            }
            return TemplateResponse(
                request,
                "admin/corporate_risk/montecarlokorporatconfig/recommend_distribution.html",
                context,
            )

        form = MonteCarloDistributionRecommendationForm(request.POST)
        if not form.is_valid():
            context = {
                **self.admin_site.each_context(request),
                "title": "Rekomendasi Model Distribusi Monte Carlo",
                "opts": self.model._meta,
                "config": config,
                "histories": histories,
                "recommendation": recommendation,
                "form": form,
                "change_url": reverse(
                    f"{self.admin_site.name}:corporate_risk_montecarlokorporatconfig_change",
                    args=[config.pk],
                ),
            }
            return TemplateResponse(
                request,
                "admin/corporate_risk/montecarlokorporatconfig/recommend_distribution.html",
                context,
            )

        selected_distribution = form.cleaned_data["distribution_type"]
        if config.distribution_type != selected_distribution:
            config.distribution_type = selected_distribution
            config.save(update_fields=["distribution_type", "updated_at"])

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
                reverse(f"{self.admin_site.name}:corporate_risk_montecarlokorporatresult_change", args=[result.pk])
            )
        except Exception as exc:
            self.message_user(
                request,
                f"Gagal menjalankan Monte Carlo: {exc}",
                level=messages.ERROR,
            )
            return redirect(
                reverse(f"{self.admin_site.name}:corporate_risk_montecarlokorporatconfig_change", args=[config.pk])
            )

@admin.register(MonteCarloKorporatHistory)
class MonteCarloKorporatHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "corporate_risk_item_display",
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

    def has_module_permission(self, request):
        return bool(request.user and request.user.is_active and request.user.is_staff)

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_active and request.user.is_staff)

    @admin.display(description="Item Risiko Korporat", ordering="corporate_risk_item__no_item")
    def corporate_risk_item_display(self, obj):
        return risk_item_label_html(obj.corporate_risk_item)

@admin.register(MonteCarloKorporatResult)
class MonteCarloKorporatResultAdmin(admin.ModelAdmin):
    list_display = (
        "corporate_risk_item_display",
        "forecast_periode",
        "metric_name",
        "mean_value",
        "p80_value",
        "probability_meet_target",
        "status_hasil",
        "created_at",
        "generate_ai_button",
    )

    @admin.display(description="Item Risiko Korporat", ordering="corporate_risk_item__no_item")
    def corporate_risk_item_display(self, obj):
        return risk_item_label_html(obj.corporate_risk_item)
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

    def has_module_permission(self, request):
        return bool(request.user and request.user.is_active and request.user.is_staff)

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_active and request.user.is_staff)

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
        metric_name = obj.metric_name or "Metric Risiko"
        metric_lower = metric_name.lower()

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

        if "piutang" in metric_lower:
            title = "Analisis Proyeksi Risiko Saldo Piutang"
            subject = "saldo piutang"
            risk_context = (
                "menunjukkan potensi tekanan terhadap arus kas dan kolektibilitas piutang"
            )
            interpretation = (
                "Hal ini perlu dibaca sebagai sinyal kewaspadaan atas potensi peningkatan saldo piutang, "
                "keterlambatan pembayaran, dan kebutuhan penguatan proses penagihan pada sisa periode tahun berjalan."
            )
            mitigation_intro = (
                "Fokus utama mitigasi adalah menekan pertumbuhan saldo piutang, mempercepat penagihan, "
                "dan menjaga kualitas kolektibilitas agar tidak berkembang menjadi eksposur kerugian."
            )
            actions = [
                "Percepatan penagihan dan monitoring aging piutang",
                "Prioritisasi penyelesaian piutang dengan saldo dan risiko keterlambatan terbesar",
                "Koordinasi dengan unit komersial/keuangan untuk rencana penurunan outstanding",
                "Evaluasi kebijakan pembayaran, reminder, dan eskalasi pelanggan berisiko",
            ]
        elif "cyber" in metric_lower or "siber" in metric_lower or "incident" in metric_lower:
            title = "Analisis Proyeksi Risiko Siber"
            subject = "ancaman/incident cyber terhadap sistem IT dan OT"
            risk_context = "menunjukkan bahwa eksposur risiko siber"
            interpretation = (
                "Hal ini menunjukkan bahwa meskipun ancaman telah terjadi, posisi saat ini masih perlu dibaca "
                "sebagai sinyal kewaspadaan untuk sisa periode tahun berjalan."
            )
            mitigation_intro = (
                "Fokus utama mitigasi bukan hanya menurunkan jumlah threat, tetapi memastikan threat tersebut "
                "tidak berkembang menjadi insiden yang mengganggu operasional atau merusak sistem kritikal."
            )
            actions = [
                "Penguatan deteksi dini dan monitoring ancaman siber",
                "Peningkatan respons insiden dan containment pada sistem IT/OT",
                "Penguatan kontrol keamanan pada aset kritikal",
                "Pencegahan eskalasi ancaman menjadi gangguan operasional",
            ]
        else:
            title = f"Analisis Proyeksi {metric_name}"
            subject = metric_name
            risk_context = "menunjukkan profil eksposur risiko"
            interpretation = (
                "Hal ini perlu dibaca sebagai sinyal monitoring untuk melihat apakah realisasi berjalan "
                "masih sesuai dengan risk appetite dan target periode berjalan."
            )
            mitigation_intro = (
                "Fokus utama mitigasi adalah menjaga realisasi tetap dalam batas yang dapat diterima "
                "dan memperkuat kontrol pada driver utama risiko."
            )
            actions = [
                "Monitoring realisasi dan deviasi terhadap target secara berkala",
                "Identifikasi driver utama yang menyebabkan perubahan proyeksi",
                "Penetapan trigger eskalasi saat proyeksi melewati risk appetite",
                "Evaluasi efektivitas rencana mitigasi berjalan",
            ]

        action_items = "".join(f"<li>{action}</li>" for action in actions)

        html = f"""
        <div style="margin-top:20px; padding:15px; background:#f8f9fa; border-radius:8px; border:1px solid #ddd;">
        <h3 style="margin-bottom:10px;">{title}</h3>

        <p>
            Berdasarkan hasil simulasi Monte Carlo, proyeksi <strong>{metric_name}</strong> untuk {subject}
            {risk_context} {tingkat}. Full year expected tercatat sebesar
            <strong>{self._fmt(full_year_expected, 3)}</strong>, dengan skenario konservatif (P80)
            sebesar <strong>{self._fmt(p80_total, 3)}</strong>.
        </p>

        <p>
            Realisasi year-to-date saat ini sebesar <strong>{self._fmt(actual_ytd, 3)}</strong> atau
            <strong>{self._fmt(realization_percent, 2)}</strong>% terhadap skenario konservatif.
            {interpretation}
        </p>

        <p>
            {mitigation_intro}
        </p>

        <p><strong>Fokus mitigasi yang direkomendasikan:</strong></p>
        <ul>
            {action_items}
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
        url = reverse(f"{self.admin_site.name}:corporate_risk_generate_ai_insight", args=[obj.pk])
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
            reverse(f"{self.admin_site.name}:corporate_risk_montecarlokorporatresult_change", args=[result.pk])
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

@admin.register(AIInsightKorporat)
class AIInsightKorporatAdmin(admin.ModelAdmin):
    list_display = (
        "corporate_risk_item_display",
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

    @admin.display(description="Item Risiko Korporat", ordering="corporate_risk_item__no_item")
    def corporate_risk_item_display(self, obj):
        return risk_item_label_html(obj.corporate_risk_item)


@admin.register(RiskMetric)
class RiskMetricAdmin(admin.ModelAdmin):
    list_display = (
        "corporate_risk_item_display",
        "name",
        "unit",
        "direction",
        "weight",
        "is_target_metric",
        "rkap_item",
        "target_value",
        "is_active",
        "input_history_button",
    )
    list_filter = ("direction", "is_target_metric", "is_active")
    search_fields = (
        "corporate_risk_item__peristiwa_risiko",
        "name",
        "unit",
    )
    autocomplete_fields = ("corporate_risk_item", "rkap_item")
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
        ("Prediksi Risiko / Target RKAP", {
            "fields": (
                "is_target_metric",
                "rkap_item",
                "target_value",
                "average_selling_price",
                "risk_appetite_threshold",
                "risk_appetite_value",
            )
        }),
    )

    @admin.display(description="Item Risiko Korporat", ordering="corporate_risk_item__no_item")
    def corporate_risk_item_display(self, obj):
        return risk_item_label_html(obj.corporate_risk_item)

    def get_list_display(self, request):
        if (
            request.user.has_perm("corporate_risk.add_montecarlometrichistory")
            or request.user.has_perm("corporate_risk.change_montecarlometrichistory")
        ):
            return self.list_display
        return tuple(
            field
            for field in self.list_display
            if field != "input_history_button"
        )

    def input_history_button(self, obj):
        url = reverse(
            "risk_admin:risk_profilrisikokorporatsummary_change",
            args=[obj.corporate_risk_item.summary_id],
        )
        url = f"{url}#monte-carlo-korporat"
        return format_html('<a class="button" href="{}">Input Histori</a>', url)

    input_history_button.short_description = "Data Historis"


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
    form = MultiMetricMonteCarloResultForm
    change_form_template = (
        "admin/corporate_risk/multimetricmontecarloresult/change_form.html"
    )

    list_display = (
        "corporate_risk_item_display",
        "forecast_periode",
        "distribution_type",
        "composite_score",
        "p80_score",
        "target_status",
        "probability_achieve_target",
        "probability_not_achieve_target",
        "requires_mitigation",
        "status_hasil",
        "created_at",
        "generate_ai_insight_button",
    )

    list_filter = (
        "forecast_periode",
        "status_hasil",
        "target_status",
        "risk_status",
        "requires_mitigation",
        "distribution_type",
    )

    search_fields = (
        "corporate_risk_item__peristiwa_risiko",
    )

    autocomplete_fields = (
        "corporate_risk_item",
        "forecast_periode",
    )

    @admin.display(description="Item Risiko Korporat", ordering="corporate_risk_item__no_item")
    def corporate_risk_item_display(self, obj):
        return risk_item_label_html(obj.corporate_risk_item)

    readonly_fields = (
        "risk_prediction_flow_html",
        "target_prediction_cards_html",
        "target_prediction_table_html",
        "forecasting_predictor_html",
        "distribution_recommendation_html",
        "distribution_analysis_snapshot_html",
        "target_distribution_chart_html",
        "mitigation_recommendation_html",
        "metric_contribution_html",
        "multi_metric_history_rows_html",
        "multi_metric_projection_rows_html",
        "multi_metric_descriptive_projection_rows_html",
        "multi_metric_chart_html",
        "composite_score",
        "p80_score",
        "forecast_total",
        "target_value",
        "target_gap",
        "average_selling_price",
        "potential_loss",
        "probability_achieve_target",
        "probability_not_achieve_target",
        "target_status",
        "risk_status",
        "worst_case_value",
        "baseline_value",
        "best_case_value",
        "var_95",
        "dampak_best_case",
        "dampak_base_case",
        "dampak_worst_case",
        "requires_mitigation",
        "status_hasil",
        "metric_snapshot_html",
        "multi_metric_ai_insight_html",
        "created_at",
        "recommended_distribution",
        "distribution_reason_summary",
        "distribution_reason_detail",
        "distribution_limitations",
        "distribution_confidence",
        "distribution_data_quality_warnings",
        "selected_distribution",
    )

    fieldsets = (
        ("Informasi Utama", {
            "fields": (
                "corporate_risk_item",
                "forecast_periode",
            )
        }),
        ("Pengaturan Forecasting / Monte Carlo", {
            "fields": (
                "forecasting_method",
                "forecast_periods",
                "prediction_interval",
                "n_simulations",
                "distribution_recommendation_html",
                "distribution_type",
                "selected_distribution_justification",
                "scenario_percentile",
            )
        }),
        ("Traceability Analisa Distribusi", {
            "fields": (
                "distribution_analysis_snapshot_html",
                "recommended_distribution",
                "distribution_reason_summary",
                "distribution_reason_detail",
                "distribution_limitations",
                "distribution_confidence",
                "distribution_data_quality_warnings",
                "selected_distribution",
            )
        }),
        ("Prediksi Risiko / Target RKAP", {
            "fields": (
                "risk_prediction_flow_html",
                "target_prediction_cards_html",
                "target_prediction_table_html",
                "forecasting_predictor_html",
                "target_distribution_chart_html",
                "mitigation_recommendation_html",
            )
        }),
        ("Hasil Simulasi", {
            "fields": (
                "composite_score",
                "p80_score",
                "forecast_total",
                "target_value",
                "target_gap",
                "average_selling_price",
                "potential_loss",
                "probability_achieve_target",
                "probability_not_achieve_target",
                "worst_case_value",
                "baseline_value",
                "best_case_value",
                "var_95",
                "dampak_best_case",
                "dampak_base_case",
                "dampak_worst_case",
                "target_status",
                "risk_status",
                "requires_mitigation",
                "status_hasil",
                "created_at",
            )
        }),
        ("Kontribusi Metric", {
            "fields": ("metric_contribution_html",)
        }),
        ("Histori Aktual Multi Metric (Tahap 1)", {
            "fields": ("multi_metric_history_rows_html",)
        }),
        ("Analisis Deskriptif Prediksi (Tahap 2)", {
            "fields": ("multi_metric_descriptive_projection_rows_html",)
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
                f"{self.admin_site.name}:corporate_risk_multimetricmontecarloresult_change",
                args=[result.pk],
            )
        )

    def _fmt(self, value, digits=2):
        try:
            return f"{float(value):,.{digits}f}"
        except Exception:
            return "-"

    def _fmt_paren_negative(self, value, digits=2):
        try:
            num = float(value)
            if num < 0:
                return f"({abs(num):,.{digits}f})"
            return f"{num:,.{digits}f}"
        except Exception:
            return "-"

    def _target_analysis(self, obj):
        snapshot = obj.simulation_snapshot or {}
        return snapshot.get("target_analysis") or {}

    def risk_prediction_flow_html(self, obj):
        steps = [
            "Tentukan value/objective",
            "Identifikasi faktor risiko",
            "Kumpulkan data historis",
            "Analisis statistik",
            "Tentukan distribusi",
            "Bangun mathematical model",
            "Monte Carlo Simulation",
            "Distribusi output",
            "Hitung VaR",
            "Analisis probabilitas",
            "Sensitivity analysis",
            "Mitigasi risiko",
            "Monitoring & improvement",
        ]
        html_steps = "".join(
            f"""
            <div style="display:flex;align-items:center;gap:8px;margin:4px 0;">
                <span style="width:24px;height:24px;border-radius:50%;background:#14345f;color:#fff;display:inline-flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;">{idx}</span>
                <span>{step}</span>
            </div>
            """
            for idx, step in enumerate(steps, start=1)
        )
        return mark_safe(
            f"""
            <div style="padding:14px;border:1px solid #dbe3ef;border-radius:10px;background:#f8fafc;">
                <div style="font-weight:700;margin-bottom:8px;">Flow Prediksi Risiko</div>
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:4px 16px;">
                    {html_steps}
                </div>
            </div>
            """
        )

    risk_prediction_flow_html.short_description = "Flow Prediksi Risiko"

    def target_prediction_cards_html(self, obj):
        analysis = self._target_analysis(obj)
        if not analysis:
            return mark_safe(
                "<div style='padding:12px;background:#fff3cd;border:1px solid #ffeeba;border-radius:8px;'>"
                "Belum ada analisis target. Tandai salah satu Risk Metric sebagai <strong>Metric Target Utama</strong> "
                "dan isi Target RKAP atau target pada histori, lalu generate ulang hasil Monte Carlo."
                "</div>"
            )

        cards = [
            ("Target RKAP", obj.target_value, ""),
            ("Forecast Total", obj.forecast_total, ""),
            ("Gap Target", obj.target_gap, ""),
            ("Potential Loss", obj.potential_loss, ""),
            ("Prob. Tercapai", obj.probability_achieve_target, "%"),
            ("Prob. Tidak Tercapai", obj.probability_not_achieve_target, "%"),
            ("Worst Case P5", obj.worst_case_value, ""),
            ("Baseline P50", obj.baseline_value, ""),
            ("Best Case P95", obj.best_case_value, ""),
            ("VaR 95%", obj.var_95, ""),
            ("Dampak Best (T-Best)", obj.dampak_best_case, ""),
            ("Dampak Base (T-Base)", obj.dampak_base_case, ""),
            ("Dampak Worst (T-Worst)", obj.dampak_worst_case, ""),
        ]
        card_html = "".join(
            f"""
            <div style="padding:14px;border:1px solid #e5e7eb;border-radius:8px;background:#fff;">
                <div style="font-size:12px;color:#64748b;text-transform:uppercase;font-weight:700;">{label}</div>
                <div style="font-size:22px;font-weight:800;color:#14345f;margin-top:6px;">{
                    self._fmt_paren_negative(value, 2) if 'Dampak' in label else self._fmt(value, 2)
                }{suffix}</div>
            </div>
            """
            for label, value, suffix in cards
        )
        status_color = "#166534" if obj.risk_status == "Aman" else "#b91c1c"
        mitigation_text = "Perlu Mitigasi" if obj.requires_mitigation else "Monitor"
        return mark_safe(
            f"""
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;">
                {card_html}
                <div style="padding:14px;border:1px solid #e5e7eb;border-radius:8px;background:#fff;">
                    <div style="font-size:12px;color:#64748b;text-transform:uppercase;font-weight:700;">Status Target</div>
                    <div style="font-size:20px;font-weight:800;color:{status_color};margin-top:6px;">{obj.target_status or "-"}</div>
                    <div style="margin-top:6px;color:#64748b;">{obj.risk_status or "-"} · {mitigation_text}</div>
                </div>
            </div>
            """
        )

    target_prediction_cards_html.short_description = "Dashboard Card Prediksi"

    def target_prediction_table_html(self, obj):
        analysis = self._target_analysis(obj)
        if not analysis:
            return "-"

        rows = [
            ("Target RKAP", obj.target_value, "Target total akhir tahun."),
            ("Realisasi YTD", analysis.get("actual_total"), "Total realisasi historis yang sudah masuk simulasi."),
            ("Forecast total sampai akhir tahun", obj.forecast_total, "Median/P50 dari seluruh hasil simulasi."),
            ("Gap terhadap target", obj.target_gap, "max(Target RKAP - Forecast total, 0)."),
            ("Harga jual rata-rata", obj.average_selling_price, "Input untuk menghitung potential loss."),
            ("Potential loss", obj.potential_loss, "Gap target x harga jual rata-rata."),
            ("Probabilitas target tercapai", f"{self._fmt(obj.probability_achieve_target, 2)}%", "Jumlah simulasi >= target / total simulasi."),
            ("Probabilitas target tidak tercapai", f"{self._fmt(obj.probability_not_achieve_target, 2)}%", "Jumlah simulasi < target / total simulasi."),
            ("Worst case", obj.worst_case_value, "Percentile 5 dari distribusi output."),
            ("Baseline / median", obj.baseline_value, "Percentile 50 dari distribusi output."),
            ("Best case", obj.best_case_value, "Percentile 95 dari distribusi output."),
            ("VaR 95%", obj.var_95, "max(Target RKAP - Worst case, 0)."),
            ("Status target", obj.target_status, "Tercapai jika forecast_total >= target."),
            ("Status risiko", obj.risk_status, "Aman jika forecast_total >= target; selain itu berisiko."),
            ("Perlu mitigasi", "Ya" if obj.requires_mitigation else "Tidak", "Mengacu risk appetite probabilitas dan/atau potential loss."),
        ]
        table_rows = "".join(
            f"""
            <tr>
                <td style="padding:8px;border:1px solid #ddd;font-weight:700;">{label}</td>
                <td style="padding:8px;border:1px solid #ddd;text-align:right;">{self._fmt(value, 2) if not isinstance(value, str) else value}</td>
                <td style="padding:8px;border:1px solid #ddd;">{note}</td>
            </tr>
            """
            for label, value, note in rows
        )
        return mark_safe(
            f"""
            <table style="border-collapse:collapse;width:100%;font-size:13px;">
                <thead>
                    <tr style="background:#f3f4f6;">
                        <th style="padding:8px;border:1px solid #ddd;text-align:left;">Output</th>
                        <th style="padding:8px;border:1px solid #ddd;text-align:right;">Nilai</th>
                        <th style="padding:8px;border:1px solid #ddd;text-align:left;">Cara Baca</th>
                    </tr>
                </thead>
                <tbody>{table_rows}</tbody>
            </table>
            """
        )

    target_prediction_table_html.short_description = "Tabel Hasil Prediksi"

    def forecasting_predictor_html(self, obj):
        snapshot = obj.simulation_snapshot or {}
        trials = snapshot.get("n_simulations") or obj.n_simulations or 10000
        periods = snapshot.get("months_ahead") or obj.forecast_periods or 9
        method = obj.get_forecasting_method_display() if obj.forecasting_method else "Best Fit - Normal Growth Monte Carlo"
        interval = obj.get_prediction_interval_display() if obj.prediction_interval else "5% dan 95%"
        return mark_safe(
            f"""
            <style>
                .erm-predictor-wrap {{
                    display:grid;
                    grid-template-columns:minmax(0,1.6fr) minmax(300px,.8fr);
                    gap:16px;
                    align-items:stretch;
                    max-width:1220px;
                }}
                .erm-predictor-chart {{
                    min-height:330px;
                    border:1px solid #d9e1ec;
                    border-radius:12px;
                    background:
                        linear-gradient(90deg, transparent 0, transparent 62%, rgba(13,46,94,.14) 62%, rgba(13,46,94,.14) 62.4%, transparent 62.4%),
                        repeating-linear-gradient(0deg, #fff, #fff 48px, #eef3f8 49px),
                        #fff;
                    padding:16px;
                    display:grid;
                    align-content:end;
                    overflow:hidden;
                }}
                .erm-predictor-lines {{
                    position:relative;
                    height:235px;
                }}
                .erm-predictor-lines:before,
                .erm-predictor-lines:after {{
                    content:"";
                    position:absolute;
                    left:8%;
                    right:5%;
                    height:3px;
                    border-radius:999px;
                }}
                .erm-predictor-lines:before {{
                    top:42%;
                    background:#2f80ed;
                    box-shadow:40px -24px 0 #2f80ed,86px -10px 0 #2f80ed,132px -45px 0 #2f80ed,178px -36px 0 #2f80ed,224px -62px 0 #2f80ed,270px -58px 0 #2f80ed,316px -42px 0 #2f80ed,362px -50px 0 #2f80ed,408px -46px 0 #2f80ed;
                }}
                .erm-predictor-lines:after {{
                    top:52%;
                    background:#6aa84f;
                    box-shadow:40px -18px 0 #6aa84f,86px -8px 0 #6aa84f,132px -34px 0 #6aa84f,178px -26px 0 #6aa84f,224px -50px 0 #6aa84f,270px -44px 0 #6aa84f,316px -35px 0 #6aa84f,362px -38px 0 #6aa84f,408px -32px 0 #6aa84f;
                }}
                .erm-predictor-fan {{
                    position:absolute;
                    left:64%;
                    right:3%;
                    top:34%;
                    height:92px;
                    background:linear-gradient(90deg, rgba(249,180,107,.32), rgba(249,180,107,.06));
                    clip-path:polygon(0 45%,100% 0,100% 100%);
                    border-left:2px solid rgba(249,180,107,.85);
                }}
                .erm-predictor-side {{
                    border:1px solid #d9e1ec;
                    border-radius:12px;
                    background:#fbfdff;
                    padding:16px;
                    display:grid;
                    gap:12px;
                }}
                .erm-predictor-field label {{
                    display:block;
                    font-size:12px;
                    font-weight:800;
                    color:#64748b;
                    text-transform:uppercase;
                    margin-bottom:6px;
                }}
                .erm-predictor-value {{
                    border:1px solid #d9e1ec;
                    border-radius:10px;
                    padding:10px 12px;
                    background:#fff;
                    color:#0d2e5e;
                    font-weight:700;
                }}
                .erm-predictor-stats {{
                    display:grid;
                    grid-template-columns:repeat(2,minmax(0,1fr));
                    gap:10px;
                }}
                .erm-predictor-stat {{
                    border:1px solid #d9e1ec;
                    border-radius:10px;
                    background:#fff;
                    padding:12px;
                }}
                .erm-predictor-stat small {{
                    display:block;
                    color:#64748b;
                    font-weight:800;
                    text-transform:uppercase;
                    margin-bottom:6px;
                }}
                .erm-predictor-stat strong {{
                    font-size:20px;
                    color:#0d2e5e;
                }}
                .erm-predictor-legend {{
                    display:flex;
                    gap:10px;
                    flex-wrap:wrap;
                }}
                .erm-predictor-legend span {{
                    display:inline-flex;
                    align-items:center;
                    gap:6px;
                    border:1px solid #d9e1ec;
                    border-radius:999px;
                    padding:7px 10px;
                    background:#fff;
                    color:#0d2e5e;
                }}
                .erm-dot {{
                    width:11px;
                    height:11px;
                    border-radius:50%;
                    display:inline-block;
                }}
            </style>
            <div class="erm-predictor-wrap">
                <div class="erm-predictor-chart">
                    <div class="erm-predictor-lines"><div class="erm-predictor-fan"></div></div>
                    <div class="erm-predictor-legend">
                        <span><i class="erm-dot" style="background:#6aa84f;"></i>Historical</span>
                        <span><i class="erm-dot" style="background:#2f80ed;"></i>Fitted / Forecast</span>
                        <span><i class="erm-dot" style="background:#f9b46b;"></i>Prediction Interval</span>
                    </div>
                </div>
                <div class="erm-predictor-side">
                    <div class="erm-predictor-field">
                        <label>Method</label>
                        <div class="erm-predictor-value">{method}</div>
                    </div>
                    <div class="erm-predictor-field">
                        <label>Periods to Forecast</label>
                        <div class="erm-predictor-value">{periods}</div>
                    </div>
                    <div class="erm-predictor-field">
                        <label>Prediction Interval</label>
                        <div class="erm-predictor-value">{interval}</div>
                    </div>
                    <div class="erm-predictor-field">
                        <label>Monte Carlo Trials</label>
                        <div class="erm-predictor-value">{self._fmt(trials, 0)}</div>
                    </div>
                    <div class="erm-predictor-stats">
                        <div class="erm-predictor-stat">
                            <small>Baseline P50</small>
                            <strong>{self._fmt(obj.baseline_value, 0)}</strong>
                        </div>
                        <div class="erm-predictor-stat">
                            <small>VaR 95%</small>
                            <strong>{self._fmt(obj.var_95, 0)}</strong>
                        </div>
                    </div>
                </div>
            </div>
            """
        )

    forecasting_predictor_html.short_description = "Pilihan Forecasting / Prediksi Time Series"

    def distribution_recommendation_html(self, obj):
        if not obj or not obj.corporate_risk_item_id:
            return mark_safe(
                "<div style='padding:12px;background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;'>"
                "Pilih dan simpan Item Risiko Korporat terlebih dahulu untuk melihat rekomendasi distribusi."
                "</div>"
            )

        metrics = RiskMetric.objects.filter(
            corporate_risk_item=obj.corporate_risk_item,
            is_active=True,
        ).order_by("name")

        if not metrics.exists():
            return mark_safe(
                "<div style='padding:12px;background:#fef2f2;border:1px solid #fecaca;border-radius:8px;'>"
                "Belum ada Risk Metric aktif untuk item risiko ini."
                "</div>"
            )

        rows = []
        for metric in metrics:
            histories = MonteCarloMetricHistory.objects.filter(metric=metric)
            if obj.forecast_periode_id and obj.forecast_periode.tanggal_selesai:
                histories = histories.filter(tanggal_data__lte=obj.forecast_periode.tanggal_selesai)
            histories = histories.order_by("tanggal_data", "id")
            values = [history.metric_value for history in histories]
            recommendation = recommend_monte_carlo_distribution(values)
            warnings = recommendation.get("data_quality_warnings") or []
            alternatives = recommendation.get("alternative_distributions") or []
            warning_items = "".join(f"<li>{escape(warning)}</li>" for warning in warnings) or "<li>-</li>"
            alternative_items = "".join(
                f"<li><strong>{escape(item.get('distribution', '-'))}</strong>: "
                f"{escape(item.get('reason', '-'))} <em>{escape(item.get('limitation', ''))}</em></li>"
                for item in alternatives
            ) or "<li>-</li>"
            rows.append(
                f"""
                <tr>
                    <td style="padding:8px;border-bottom:1px solid #e5e7eb;">{escape(metric.name)}</td>
                    <td style="padding:8px;border-bottom:1px solid #e5e7eb;">{len(values)}</td>
                    <td style="padding:8px;border-bottom:1px solid #e5e7eb;"><strong>{escape(recommendation.get("recommended_label") or "-")}</strong></td>
                    <td style="padding:8px;border-bottom:1px solid #e5e7eb;">{self._fmt(recommendation.get("growth_mean"), 6) if recommendation.get("growth_mean") is not None else "-"}</td>
                    <td style="padding:8px;border-bottom:1px solid #e5e7eb;">{self._fmt(recommendation.get("growth_std"), 6) if recommendation.get("growth_std") is not None else "-"}</td>
                    <td style="padding:8px;border-bottom:1px solid #e5e7eb;">{escape(recommendation.get("reason_summary") or "-")}</td>
                    <td style="padding:8px;border-bottom:1px solid #e5e7eb;">{escape(recommendation.get("limitations") or "-")}</td>
                    <td style="padding:8px;border-bottom:1px solid #e5e7eb;"><strong>{escape(recommendation.get("confidence") or "-")}</strong></td>
                </tr>
                <tr>
                    <td colspan="8" style="padding:8px 12px 14px;border-bottom:1px solid #e5e7eb;background:#fbfdff;">
                        <details>
                            <summary style="cursor:pointer;font-weight:600;">Lihat Analisa</summary>
                            <div style="margin-top:10px;display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;">
                                <div>
                                    <strong>Alasan Detail</strong>
                                    <p>{escape(recommendation.get("reason_detail") or "-")}</p>
                                </div>
                                <div>
                                    <strong>Warning Data Quality</strong>
                                    <ul>{warning_items}</ul>
                                </div>
                                <div>
                                    <strong>Alternatif</strong>
                                    <ul>{alternative_items}</ul>
                                </div>
                            </div>
                        </details>
                    </td>
                </tr>
                """
            )

        selected_label = dict(MonteCarloKorporatConfig.DISTRIBUTION_CHOICES).get(
            obj.distribution_type,
            obj.distribution_type,
        )
        selected_warning = ""
        if obj.recommended_distribution and obj.distribution_type != obj.recommended_distribution:
            selected_warning = (
                "<p style='padding:10px;background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;'>"
                "Pilihan Anda berbeda dari rekomendasi sistem. Pastikan justifikasi bisnis/statistik terisi sebelum menyimpan."
                "</p>"
            )

        return mark_safe(
            f"""
            <div style="padding:14px;background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;">
                <p style="margin-top:0;">
                    <strong>Distribusi yang dipilih:</strong> {escape(selected_label)}. Gunakan rekomendasi di bawah sebagai dasar
                    memilih field <strong>Model Distribusi Monte Carlo</strong> sebelum menyimpan prediksi.
                </p>
                <p style="margin-top:0;color:#4b5563;">
                    Catatan: simulasi multi metric saat ini memakai satu model distribusi global untuk beberapa metric.
                    Rekomendasi agregat adalah kompromi; tinjau detail per metric sebelum override.
                </p>
                {selected_warning}
                <table style="width:100%;border-collapse:collapse;background:#fff;">
                    <thead>
                        <tr>
                            <th style="text-align:left;padding:8px;border-bottom:1px solid #d1d5db;">Metric</th>
                            <th style="text-align:left;padding:8px;border-bottom:1px solid #d1d5db;">Data</th>
                            <th style="text-align:left;padding:8px;border-bottom:1px solid #d1d5db;">Rekomendasi</th>
                            <th style="text-align:left;padding:8px;border-bottom:1px solid #d1d5db;">Mean Growth</th>
                            <th style="text-align:left;padding:8px;border-bottom:1px solid #d1d5db;">Std Growth</th>
                            <th style="text-align:left;padding:8px;border-bottom:1px solid #d1d5db;">Alasan Rekomendasi</th>
                            <th style="text-align:left;padding:8px;border-bottom:1px solid #d1d5db;">Catatan Risiko</th>
                            <th style="text-align:left;padding:8px;border-bottom:1px solid #d1d5db;">Confidence</th>
                        </tr>
                    </thead>
                    <tbody>{''.join(rows)}</tbody>
                </table>
            </div>
            """
        )

    distribution_recommendation_html.short_description = "Rekomendasi Model Distribusi"

    def distribution_analysis_snapshot_html(self, obj):
        if not obj or not obj.pk:
            return "-"

        selected_label = dict(MonteCarloKorporatConfig.DISTRIBUTION_CHOICES).get(
            obj.selected_distribution or obj.distribution_type,
            obj.selected_distribution or obj.distribution_type or "-",
        )
        recommended_label = dict(MonteCarloKorporatConfig.DISTRIBUTION_CHOICES).get(
            obj.recommended_distribution,
            obj.recommended_distribution or "-",
        )
        warnings = obj.distribution_data_quality_warnings or []
        warning_items = "".join(f"<li>{escape(warning)}</li>" for warning in warnings) or "<li>-</li>"
        metric_analyses = (obj.simulation_snapshot or {}).get("distribution_analysis", {}).get("metric_analyses", [])
        metric_blocks = []
        for row in metric_analyses:
            row_warnings = "".join(f"<li>{escape(warning)}</li>" for warning in (row.get("warnings") or [])) or "<li>-</li>"
            alternatives = "".join(
                f"<li><strong>{escape(item.get('distribution', '-'))}</strong>: "
                f"{escape(item.get('reason', '-'))} <em>{escape(item.get('limitation', ''))}</em></li>"
                for item in (row.get("alternative_distributions") or [])
            ) or "<li>-</li>"
            metric_blocks.append(
                f"""
                <details style="padding:10px;border:1px solid #e5e7eb;border-radius:8px;background:#fff;">
                    <summary style="cursor:pointer;font-weight:700;">
                        {escape(row.get("metric_name") or "-")} - {escape(row.get("recommended_label") or row.get("recommended_distribution") or "-")}
                        ({escape(row.get("confidence") or "-")})
                    </summary>
                    <p><strong>Alasan:</strong> {escape(row.get("reason_detail") or row.get("reason_summary") or "-")}</p>
                    <p><strong>Keterbatasan:</strong> {escape(row.get("limitations") or "-")}</p>
                    <strong>Warning</strong>
                    <ul>{row_warnings}</ul>
                    <strong>Alternatif</strong>
                    <ul>{alternatives}</ul>
                </details>
                """
            )

        return mark_safe(
            f"""
            <div style="padding:14px;background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;">
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-bottom:12px;">
                    <div><strong>Rekomendasi Sistem</strong><br>{escape(recommended_label)}</div>
                    <div><strong>Distribusi Dipilih</strong><br>{escape(selected_label)}</div>
                    <div><strong>Confidence</strong><br>{escape(obj.distribution_confidence or "-")}</div>
                </div>
                <p><strong>Alasan agregat:</strong> {escape(obj.distribution_reason_detail or obj.distribution_reason_summary or "-")}</p>
                <p><strong>Keterbatasan:</strong> {escape(obj.distribution_limitations or "-")}</p>
                <p><strong>Justifikasi user:</strong> {escape(obj.selected_distribution_justification or "-")}</p>
                <strong>Warning Data Quality</strong>
                <ul>{warning_items}</ul>
                <div style="display:grid;gap:10px;margin-top:12px;">{''.join(metric_blocks) or "<p>-</p>"}</div>
            </div>
            """
        )

    distribution_analysis_snapshot_html.short_description = "Analisa Pemilihan Distribusi Tersimpan"

    def target_distribution_chart_html(self, obj):
        analysis = self._target_analysis(obj)
        distribution = analysis.get("distribution_sample") or []
        if not distribution:
            return "-"

        chart_id = f"targetDistributionChart_{obj.id}"
        values = [float(v) for v in distribution]
        target_value = float(obj.target_value or 0)
        trials = len(values)

        return mark_safe(
            f"""
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;max-width:1200px;margin-bottom:12px;">
                <div style="padding:10px 12px;border:1px solid #d9e1ec;border-radius:10px;background:#fff;">
                    <div style="font-size:11px;font-weight:800;color:#64748b;text-transform:uppercase;">Forecast DMP</div>
                    <div style="font-size:20px;font-weight:800;color:#0d2e5e;">{self._fmt(obj.baseline_value, 0)}</div>
                </div>
                <div style="padding:10px 12px;border:1px solid #d9e1ec;border-radius:10px;background:#fff;">
                    <div style="font-size:11px;font-weight:800;color:#64748b;text-transform:uppercase;">Certainty Target Tercapai</div>
                    <div style="font-size:20px;font-weight:800;color:#0d2e5e;">{self._fmt(obj.probability_achieve_target, 2)}%</div>
                </div>
                <div style="padding:10px 12px;border:1px solid #d9e1ec;border-radius:10px;background:#fff;">
                    <div style="font-size:11px;font-weight:800;color:#64748b;text-transform:uppercase;">Trials</div>
                    <div style="font-size:20px;font-weight:800;color:#0d2e5e;">{self._fmt(trials or obj.n_simulations or 10000, 0)}</div>
                </div>
                <div style="padding:10px 12px;border:1px solid #d9e1ec;border-radius:10px;background:#fff;">
                    <div style="font-size:11px;font-weight:800;color:#64748b;text-transform:uppercase;">Cut-off Target</div>
                    <div style="font-size:20px;font-weight:800;color:#0d2e5e;">{self._fmt(obj.target_value, 0)}</div>
                </div>
            </div>
            <div style="width:100%;max-width:1200px;height:430px;">
                <canvas id="{chart_id}"></canvas>
            </div>
            <div style="margin-top:10px;padding:10px;background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;font-size:13px;">
                Forecast DMP menampilkan histogram frekuensi hasil Monte Carlo. Area merah adalah skenario di bawah target,
                area biru adalah skenario yang mencapai/melewati target.
            </div>
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
            <script>
            (function() {{
                const canvas = document.getElementById("{chart_id}");
                if (!canvas || typeof Chart === "undefined") return;
                const existing = Chart.getChart("{chart_id}");
                if (existing) existing.destroy();
                const values = {json.dumps(values)};
                const targetValue = {json.dumps(target_value)};
                const minValue = Math.min(...values);
                const maxValue = Math.max(...values);
                const binCount = Math.min(44, Math.max(18, Math.round(Math.sqrt(values.length))));
                const binWidth = maxValue > minValue ? (maxValue - minValue) / binCount : 1;
                const bins = Array.from({{ length: binCount }}, (_, index) => {{
                    const start = minValue + (index * binWidth);
                    return {{ center: start + (binWidth / 2), count: 0 }};
                }});
                values.forEach((value) => {{
                    const rawIndex = Math.floor((value - minValue) / binWidth);
                    const index = Math.max(0, Math.min(binCount - 1, rawIndex));
                    bins[index].count += 1;
                }});
                const compact = new Intl.NumberFormat("en-US", {{ notation: "compact", maximumFractionDigits: 1 }});
                const labels = bins.map((bin) => compact.format(bin.center));
                const counts = bins.map((bin) => bin.count);
                const probabilities = bins.map((bin) => values.length ? bin.count / values.length : 0);
                const colors = bins.map((bin) => bin.center < targetValue ? "rgba(220,38,38,.78)" : "rgba(37,99,235,.82)");
                const targetBinIndex = Math.max(0, Math.min(binCount - 1, Math.floor((targetValue - minValue) / binWidth)));
                const targetPlugin = {{
                    id: "adminDmpTargetPlugin",
                    afterDatasetsDraw(chart) {{
                        const {{ ctx, chartArea, scales }} = chart;
                        if (!chartArea || !scales.x) return;
                        const x = scales.x.getPixelForValue(targetBinIndex);
                        ctx.save();
                        ctx.strokeStyle = "#0d2e5e";
                        ctx.lineWidth = 2;
                        ctx.setLineDash([6, 4]);
                        ctx.beginPath();
                        ctx.moveTo(x, chartArea.top);
                        ctx.lineTo(x, chartArea.bottom);
                        ctx.stroke();
                        ctx.setLineDash([]);
                        ctx.fillStyle = "#0d2e5e";
                        ctx.font = "bold 12px Arial";
                        ctx.fillText("Target", Math.min(x + 8, chartArea.right - 48), chartArea.top + 14);
                        ctx.restore();
                    }}
                }};
                new Chart(canvas, {{
                    type: "bar",
                    plugins: [targetPlugin],
                    data: {{
                        labels: labels,
                        datasets: [
                            {{
                                label: "Frequency",
                                data: counts,
                                backgroundColor: colors,
                                borderColor: colors,
                                borderWidth: 1,
                                barPercentage: 1,
                                categoryPercentage: 1
                            }},
                            {{
                                label: "Probability",
                                type: "line",
                                data: probabilities,
                                yAxisID: "y1",
                                borderColor: "#f59e0b",
                                backgroundColor: "rgba(245,158,11,.16)",
                                borderWidth: 2,
                                pointRadius: 0,
                                tension: .25
                            }}
                        ]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{
                            legend: {{ position: "bottom" }},
                            title: {{ display: true, text: "Forecast DMP - " + values.length.toLocaleString("en-US") + " Trials" }}
                        }},
                        scales: {{
                            x: {{ title: {{ display: true, text: "Forecast Total" }} }},
                            y: {{ title: {{ display: true, text: "Frequency" }}, beginAtZero: true }},
                            y1: {{
                                position: "right",
                                title: {{ display: true, text: "Probability" }},
                                beginAtZero: true,
                                grid: {{ drawOnChartArea: false }},
                                ticks: {{ callback: (value) => `${{(Number(value) * 100).toFixed(0)}}%` }}
                            }}
                        }}
                    }}
                }});
            }})();
            </script>
            """
        )

    target_distribution_chart_html.short_description = "Grafik Distribusi Output"

    def mitigation_recommendation_html(self, obj):
        analysis = self._target_analysis(obj)
        if not analysis:
            return "-"

        if obj.requires_mitigation:
            actions = [
                "Review ulang asumsi demand dan data historis yang menjadi driver simulasi.",
                "Siapkan aksi peningkatan penjualan untuk menutup gap target terbesar.",
                "Prioritaskan mitigasi pada faktor risiko yang paling sensitif terhadap penurunan demand.",
                "Tetapkan trigger monitoring bulanan ketika probabilitas tidak tercapai naik di atas risk appetite.",
            ]
            color = "#fef2f2"
            border = "#fecaca"
            title = "Rekomendasi: Perlu Mitigasi"
        else:
            actions = [
                "Belum perlu mitigasi tambahan di luar rencana berjalan.",
                "Tetap monitor realisasi YTD, forecast, dan probabilitas tidak tercapai setiap bulan.",
                "Update data historis agar distribusi Monte Carlo mencerminkan kondisi terbaru.",
            ]
            color = "#f0fdf4"
            border = "#bbf7d0"
            title = "Rekomendasi: Monitoring Berkala"

        list_items = "".join(f"<li>{action}</li>" for action in actions)
        return mark_safe(
            f"""
            <div style="padding:14px;border:1px solid {border};border-radius:10px;background:{color};">
                <h3 style="margin-top:0;">{title}</h3>
                <p>{analysis.get("recommendation", "")}</p>
                <ul>{list_items}</ul>
            </div>
            """
        )

    mitigation_recommendation_html.short_description = "Rekomendasi Mitigasi Otomatis"

    def save_model(self, request, obj, form, change):
        result = run_multi_metric_monte_carlo_for_korporat_item(
            item=obj.corporate_risk_item,
            forecast_periode=obj.forecast_periode,
            months_ahead=obj.forecast_periods or 9,
            n_simulations=obj.n_simulations or 10000,
            scenario_percentile=obj.scenario_percentile,
            distribution_type=obj.distribution_type or "normal",
            selected_distribution_justification=obj.selected_distribution_justification or "",
        )

        result.forecasting_method = obj.forecasting_method or result.forecasting_method
        result.forecast_periods = obj.forecast_periods or result.forecast_periods
        result.prediction_interval = obj.prediction_interval or result.prediction_interval
        result.n_simulations = obj.n_simulations or result.n_simulations
        result.distribution_type = obj.distribution_type or result.distribution_type
        result.selected_distribution = obj.distribution_type or result.selected_distribution
        result.selected_distribution_justification = obj.selected_distribution_justification or ""
        result.save(update_fields=[
            "forecasting_method",
            "forecast_periods",
            "prediction_interval",
            "n_simulations",
            "distribution_type",
            "selected_distribution",
            "selected_distribution_justification",
            "updated_at",
        ])

        obj.composite_score = result.composite_score
        obj.p80_score = result.p80_score
        obj.forecast_total = result.forecast_total
        obj.target_value = result.target_value
        obj.target_gap = result.target_gap
        obj.average_selling_price = result.average_selling_price
        obj.potential_loss = result.potential_loss
        obj.probability_achieve_target = result.probability_achieve_target
        obj.probability_not_achieve_target = result.probability_not_achieve_target
        obj.target_status = result.target_status
        obj.risk_status = result.risk_status
        obj.worst_case_value = result.worst_case_value
        obj.baseline_value = result.baseline_value
        obj.best_case_value = result.best_case_value
        obj.var_95 = result.var_95
        obj.requires_mitigation = result.requires_mitigation
        obj.status_hasil = result.status_hasil
        obj.metric_snapshot = result.metric_snapshot
        obj.simulation_snapshot = result.simulation_snapshot
        obj.distribution_type = result.distribution_type
        obj.recommended_distribution = result.recommended_distribution
        obj.distribution_reason_summary = result.distribution_reason_summary
        obj.distribution_reason_detail = result.distribution_reason_detail
        obj.distribution_limitations = result.distribution_limitations
        obj.distribution_confidence = result.distribution_confidence
        obj.distribution_data_quality_warnings = result.distribution_data_quality_warnings
        obj.selected_distribution = result.selected_distribution
        obj.selected_distribution_justification = result.selected_distribution_justification
        obj.pk = result.pk
        obj._state.adding = False

        def generate_insight_after_commit():
            try:
                insight = generate_rule_based_ai_insight_for_multi_metric_result(result)
                self.message_user(
                    request,
                    f"AI Insight Multi Metric otomatis dibuat/diperbarui. Insight ID: {insight.pk}",
                    level=messages.SUCCESS,
                )
            except Exception as exc:
                self.message_user(
                    request,
                    f"Data tersimpan, tetapi AI Insight gagal dibuat otomatis: {exc}",
                    level=messages.WARNING,
                )

        transaction.on_commit(generate_insight_after_commit)

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

    multi_metric_history_rows_html.short_description = "Histori Aktual Multi Metric (Tahap 1)"

    def multi_metric_descriptive_projection_rows_html(self, obj):
        snapshot = obj.simulation_snapshot or {}
        descriptive = snapshot.get("descriptive_projection_rows", []) or []
        stats = snapshot.get("descriptive_stats") or {}

        if not descriptive:
            return mark_safe(
                "<div style='padding:12px;background:#fff3cd;border:1px solid #ffeeba;border-radius:6px;'>"
                "Tahap 2 (Analisis Deskriptif) belum tersedia. Generate ulang Multi Metric Monte Carlo Result."
                "</div>"
            )

        stats_html = ""
        try:
            stats_html = f"""
            <div style="padding:10px 12px;margin-bottom:10px;background:#eef7fb;border:1px solid #cfe3ec;border-radius:6px;color:#24586a;font-size:13px;">
                Window SMA: <strong>{stats.get('sma_window','-')}</strong>,
                f_p50: <strong>{self._fmt(stats.get('f_p50'), 3)}</strong>,
                f_p15: <strong>{self._fmt(stats.get('f_p15'), 3)}</strong>,
                Std Dev: <strong>{self._fmt(stats.get('std_dev') or stats.get('std_dev', None) or stats.get('std_dev'), 3)}</strong>
            </div>
            """
        except Exception:
            stats_html = ""

        rows = []
        for row in descriptive:
            bulan = row.get("bulan") or f"Bulan-{row.get('bulan_index')}"
            rows.append(f"""
                <tr>
                    <td style="padding:8px;border:1px solid #ddd;">{bulan}</td>
                    <td style="padding:8px;border:1px solid #ddd;text-align:right;font-weight:800;">{self._fmt(row.get('f_p50'), 3)}</td>
                    <td style="padding:8px;border:1px solid #ddd;text-align:right;">{self._fmt(row.get('f_p15'), 3)}</td>
                    <td style="padding:8px;border:1px solid #ddd;text-align:right;font-weight:800;">{self._fmt(row.get('std_dev'), 3)}</td>
                </tr>
            """)

        return mark_safe(f"""
            {stats_html}
            <table style="border-collapse:collapse;width:100%;font-size:13px;">
                <thead>
                    <tr style="background:#f3f4f6;">
                        <th style="padding:8px;border:1px solid #ddd;">Bulan</th>
                        <th style="padding:8px;border:1px solid #ddd;text-align:right;">F P50</th>
                        <th style="padding:8px;border:1px solid #ddd;text-align:right;">F P15</th>
                        <th style="padding:8px;border:1px solid #ddd;text-align:right;">Std Dev (P50-P15)</th>
                    </tr>
                </thead>
                <tbody>{''.join(rows)}</tbody>
            </table>
        """)


    def multi_metric_projection_rows_html(self, obj):
        snapshot = obj.simulation_snapshot or {}
        target_rows = snapshot.get("target_projection_rows", [])
        rows = snapshot.get("projection_rows", [])

        if not target_rows and not rows:
            return mark_safe(
                "<div style='padding:12px;background:#fff3cd;border:1px solid #ffeeba;border-radius:6px;'>"
                "Proyeksi bulanan belum tersedia. Generate ulang Multi Metric Monte Carlo Result."
                "</div>"
            )

        table_rows = []

        if target_rows:
            for row in target_rows:
                bulan = row.get("bulan") or f"Bulan-{row.get('bulan_index')}"
                table_rows.append(f"""
                    <tr>
                        <td style="padding:8px;border:1px solid #ddd;">{bulan}</td>
                        <td style="padding:8px;border:1px solid #ddd;text-align:right;font-weight:bold;">{self._fmt(row.get("forecast_median"), 0)}</td>
                        <td style="padding:8px;border:1px solid #ddd;text-align:right;font-weight:bold;">{self._fmt(row.get("forecast_p15"), 0)}</td>
                        <td style="padding:8px;border:1px solid #ddd;text-align:right;">{self._fmt(row.get("stdev_f"), 0)}</td>
                        <td style="padding:8px;border:1px solid #ddd;">{row.get("metric_name") or "-"}</td>
                    </tr>
                """)

            html = f"""
            <div style="padding:10px 12px;margin-bottom:10px;background:#eef7fb;border:1px solid #cfe3ec;border-radius:6px;color:#24586a;">
                Forecast mengikuti contoh Excel: P50/median, P15,8655254, dan STDEV F = P50 - P15,8655254.
            </div>
            <table style="border-collapse:collapse;width:100%;font-size:13px;">
                <thead>
                    <tr style="background:#f3f4f6;">
                        <th style="padding:8px;border:1px solid #ddd;">Bulan</th>
                        <th style="padding:8px;border:1px solid #ddd;text-align:right;">Forecast Penjualan Bulanan (Median/P50)</th>
                        <th style="padding:8px;border:1px solid #ddd;text-align:right;">Forecast Penjualan Bulanan (P15,8655254)</th>
                        <th style="padding:8px;border:1px solid #ddd;text-align:right;">STDEV F Penjualan</th>
                        <th style="padding:8px;border:1px solid #ddd;">Metric</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(table_rows)}
                </tbody>
            </table>
            """
            return mark_safe(html)

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
        target_analysis = (obj.simulation_snapshot or {}).get("target_analysis") or {}
        risk_item = obj.corporate_risk_item
        risk_title = getattr(risk_item, "peristiwa_risiko", None) or str(risk_item)
        risk_number = getattr(risk_item, "no_item", None)
        risk_label = f"Risiko {risk_number} - {risk_title}" if risk_number else risk_title

        if target_analysis:
            mitigation_text = (
                "perlu mitigasi"
                if obj.requires_mitigation
                else "cukup dimonitor dengan trigger bulanan"
            )
            html = f"""
            <div style="padding:16px; background:#f8fafc; border:1px solid #e5e7eb; border-radius:10px;">
                <h3 style="margin-top:0;">Ringkasan Eksekutif Risiko</h3>
                <p>
                    <strong>{risk_label}</strong> untuk periode forecast
                    <strong>{obj.forecast_periode}</strong> memiliki status target
                    <strong>{obj.target_status or "-"}</strong> dan status risiko
                    <strong>{obj.risk_status or "-"}</strong>.
                </p>
                <p>
                    Forecast total berbasis median/P50 sebesar
                    <strong>{self._fmt(obj.forecast_total, 0)}</strong>, dibandingkan target RKAP
                    <strong>{self._fmt(obj.target_value, 0)}</strong>. Gap terhadap target sebesar
                    <strong>{self._fmt(obj.target_gap, 0)}</strong> dengan estimasi potential loss
                    <strong>{self._fmt(obj.potential_loss, 0)}</strong>.
                </p>
                <p>
                    Probabilitas target tercapai sebesar
                    <strong>{self._fmt(obj.probability_achieve_target, 2)}%</strong>, sedangkan
                    probabilitas target tidak tercapai sebesar
                    <strong>{self._fmt(obj.probability_not_achieve_target, 2)}%</strong>.
                    VaR 95% tercatat sebesar <strong>{self._fmt(obj.var_95, 0)}</strong>.
                </p>
                <p>
                    Berdasarkan risk appetite, risiko ini <strong>{mitigation_text}</strong>.
                    Faktor dominan simulasi adalah <strong>{top_metric.get("metric_name", "-")}</strong>.
                </p>
            </div>
            """
            return mark_safe(html)

        html = f"""
        <div style="padding:16px; background:#f8fafc; border:1px solid #e5e7eb; border-radius:10px;">
            <h3 style="margin-top:0;">Ringkasan Eksekutif Risiko</h3>
            <p>
                <strong>{risk_label}</strong> untuk periode forecast
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

    def generate_ai_insight_button(self, obj):
        url = reverse(
            f"{self.admin_site.name}:corporate_risk_generate_ai_insight_multi_metric",
            args=[obj.pk],
        )
        return format_html('<a class="button" href="{}">Generate AI Insight</a>', url)

    generate_ai_insight_button.short_description = "AI Insight"


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
