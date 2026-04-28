from django.db import models
from core.models import TimeStampedModel
from masterdata.models import PeriodeLaporan
from risk.models import ProfilRisikoKorporatItem


class MonteCarloKorporatConfig(TimeStampedModel):
    DIRECTION_CHOICES = [
        ("lower", "Semakin rendah semakin baik"),
        ("higher", "Semakin tinggi semakin baik"),
    ]

    DISTRIBUTION_CHOICES = [
        ("normal", "Normal"),
        ("triangular", "Triangular"),
    ]

    corporate_risk_item = models.OneToOneField(
        ProfilRisikoKorporatItem,
        on_delete=models.CASCADE,
        related_name="monte_carlo_config",
    )

    metric_name = models.CharField(max_length=100)
    metric_unit = models.CharField(max_length=50, null=True, blank=True)

    direction = models.CharField(
        max_length=10,
        choices=DIRECTION_CHOICES,
        default="lower",
    )

    distribution_type = models.CharField(
        max_length=20,
        choices=DISTRIBUTION_CHOICES,
        default="normal",
    )

    n_simulations = models.PositiveIntegerField(default=1000)
    minimum_history_points = models.PositiveIntegerField(default=2)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "cr_mc_config"

    def __str__(self):
        return f"{self.corporate_risk_item} - {self.metric_name}"


class MonteCarloKorporatHistory(TimeStampedModel):
    corporate_risk_item = models.ForeignKey(
        ProfilRisikoKorporatItem,
        on_delete=models.CASCADE,
        related_name="mc_histories",
    )

    periode = models.ForeignKey(PeriodeLaporan, on_delete=models.PROTECT)
    tanggal_data = models.DateField()

    metric_name = models.CharField(max_length=100)
    metric_value = models.DecimalField(max_digits=18, decimal_places=4)

    target_value = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "cr_mc_history"
        ordering = ["tanggal_data"]


class MonteCarloKorporatResult(TimeStampedModel):
    corporate_risk_item = models.ForeignKey(
        ProfilRisikoKorporatItem,
        on_delete=models.CASCADE,
        related_name="mc_results",
    )

    forecast_periode = models.ForeignKey(PeriodeLaporan, on_delete=models.PROTECT)

    metric_name = models.CharField(max_length=100)

    mean_value = models.DecimalField(max_digits=18, decimal_places=4, null=True)
    p50_value = models.DecimalField(max_digits=18, decimal_places=4, null=True)
    p80_value = models.DecimalField(max_digits=18, decimal_places=4, null=True)
    p90_value = models.DecimalField(max_digits=18, decimal_places=4, null=True)
    min_value = models.DecimalField(max_digits=18, decimal_places=4, null=True)
    max_value = models.DecimalField(max_digits=18, decimal_places=4, null=True)

    probability_meet_target = models.DecimalField(max_digits=6, decimal_places=2, null=True)

    target_value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    status_hasil = models.CharField(max_length=20, null=True, blank=True)

    history_snapshot = models.JSONField(default=list, blank=True)
    simulation_snapshot = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "cr_mc_result"

    def __str__(self):
        return f"{self.corporate_risk_item} - Forecast"

class AIInsightKorporat(TimeStampedModel):
    corporate_risk_item = models.ForeignKey(
        ProfilRisikoKorporatItem,
        on_delete=models.CASCADE,
        related_name="ai_insights",
    )
    monte_carlo_result = models.ForeignKey(
        "corporate_risk.MonteCarloKorporatResult",
        on_delete=models.CASCADE,
        related_name="ai_insights",
        null=True,
        blank=True,
    )

    executive_summary = models.TextField(null=True, blank=True)
    key_drivers = models.JSONField(default=list, blank=True)
    recommended_actions = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "cr_ai_insight_korporat"
        ordering = ["-created_at"]

    def __str__(self):
        return f"AI Insight - {self.corporate_risk_item}"

class RiskMetric(models.Model):
    DIRECTION_INCREASE = "increase"
    DIRECTION_DECREASE = "decrease"

    DIRECTION_CHOICES = (
        (DIRECTION_INCREASE, "Semakin besar semakin berisiko"),
        (DIRECTION_DECREASE, "Semakin kecil semakin berisiko"),
    )

    corporate_risk_item = models.ForeignKey(
        "risk.ProfilRisikoKorporatItem",
        on_delete=models.CASCADE,
        related_name="risk_metrics",
        verbose_name="Item Risiko Korporat",
    )
    name = models.CharField(
        max_length=255,
        verbose_name="Nama Metric",
    )
    unit = models.CharField(
        max_length=50,
        blank=True,
        default="",
        verbose_name="Satuan",
    )
    direction = models.CharField(
        max_length=20,
        choices=DIRECTION_CHOICES,
        default=DIRECTION_INCREASE,
        verbose_name="Arah Risiko",
    )
    weight = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=1,
        verbose_name="Bobot",
        help_text="Bobot untuk perhitungan composite risk score. Contoh: 0.50, 0.30, 0.20",
    )
    threshold = models.FloatField(
        default=1,
        verbose_name="Threshold Risiko",
        help_text="Nilai batas risiko (untuk normalisasi ke 0–100)"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Aktif",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Dibuat pada",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Diubah pada",
    )
    

    class Meta:
        verbose_name = "Risk Metric"
        verbose_name_plural = "Risk Metrics"
        ordering = ("corporate_risk_item", "name")
        unique_together = ("corporate_risk_item", "name")

    def __str__(self):
        return f"{self.corporate_risk_item} - {self.name}"
    

class MonteCarloMetricHistory(models.Model):
    metric = models.ForeignKey(
        "corporate_risk.RiskMetric",
        on_delete=models.CASCADE,
        related_name="metric_histories",
        verbose_name="Risk Metric",
    )
    periode = models.ForeignKey(
        "masterdata.PeriodeLaporan",
        on_delete=models.PROTECT,
        verbose_name="Periode",
    )
    tanggal_data = models.DateField(
        verbose_name="Tanggal Data",
    )
    metric_value = models.DecimalField(
        max_digits=24,
        decimal_places=4,
        verbose_name="Nilai Aktual",
    )
    target_value = models.DecimalField(
        max_digits=24,
        decimal_places=4,
        blank=True,
        null=True,
        verbose_name="Target",
    )
    keterangan = models.TextField(
        blank=True,
        default="",
        verbose_name="Keterangan",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Dibuat pada",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Diubah pada",
    )

    class Meta:
        verbose_name = "Monte Carlo Metric History"
        verbose_name_plural = "Monte Carlo Metric Histories"
        ordering = ("metric", "tanggal_data")
        unique_together = ("metric", "periode")

    def __str__(self):
        return f"{self.metric} - {self.periode} = {self.metric_value}"


class MultiMetricMonteCarloResult(models.Model):
    corporate_risk_item = models.ForeignKey(
        "risk.ProfilRisikoKorporatItem",
        on_delete=models.CASCADE,
        related_name="multi_metric_results",
        verbose_name="Item Risiko Korporat",
    )
    forecast_periode = models.ForeignKey(
        "masterdata.PeriodeLaporan",
        on_delete=models.PROTECT,
        verbose_name="Periode Forecast",
    )
    SCENARIO_CHOICES = (
        (40, "P40 - Moderat"),
        (50, "P50 - Median"),
        (60, "P60 - Konservatif ringan"),
        (80, "P80 - Konservatif"),
        (90, "P90 - Stress scenario"),
    )

    scenario_percentile = models.PositiveSmallIntegerField(
        choices=SCENARIO_CHOICES,
        default=80,
        verbose_name="Scenario Percentile",
    )
    composite_score = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=0,
        verbose_name="Composite Risk Score",
    )
    p80_score = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=0,
        verbose_name="P80 Composite Score",
    )
    status_hasil = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="Status Hasil",
    )
    metric_snapshot = models.JSONField(
        blank=True,
        default=dict,
        verbose_name="Snapshot Metric",
    )
    simulation_snapshot = models.JSONField(
        blank=True,
        default=dict,
        verbose_name="Snapshot Simulasi",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Dibuat pada",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Diubah pada",
    )

    class Meta:
        verbose_name = "Multi Metric Monte Carlo Result"
        verbose_name_plural = "Multi Metric Monte Carlo Results"
        ordering = ("-created_at",)
        unique_together = ("corporate_risk_item", "forecast_periode")

    def __str__(self):
        return f"{self.corporate_risk_item} - {self.forecast_periode}"
    
