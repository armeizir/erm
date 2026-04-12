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