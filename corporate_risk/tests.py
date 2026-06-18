from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from corporate_risk.models import MultiMetricMonteCarloResult
from corporate_risk.services import recommend_monte_carlo_distribution


class DistributionRecommendationAnalysisTests(SimpleTestCase):
    def test_recommendation_contains_analysis_fields(self):
        recommendation = recommend_monte_carlo_distribution([10, 12, 15, 19, 28, 43])

        self.assertIn("reason_summary", recommendation)
        self.assertIn("reason_detail", recommendation)
        self.assertIn("limitations", recommendation)
        self.assertIn("confidence", recommendation)
        self.assertIn("data_quality_warnings", recommendation)

    def test_history_count_under_24_warns_limited_data(self):
        recommendation = recommend_monte_carlo_distribution([10, 11, 13, 17, 23, 31])

        warnings = recommendation["data_quality_warnings"]

        self.assertTrue(any("kurang dari 24 periode" in warning for warning in warnings))

    def test_non_negative_skewed_data_gets_tail_or_bounded_recommendation(self):
        recommendation = recommend_monte_carlo_distribution([1, 1, 2, 3, 5, 9, 20, 55])

        self.assertIn(recommendation["recommended"], {"lognormal", "gamma", "beta", "weibull"})

    def test_distribution_override_requires_user_justification(self):
        result = MultiMetricMonteCarloResult(
            recommended_distribution="lognormal",
            selected_distribution="normal",
            distribution_type="normal",
            selected_distribution_justification="",
        )

        with self.assertRaises(ValidationError):
            result.clean()
