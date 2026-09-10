from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from corporate_risk.services import generate_rule_based_ai_insight_for_multi_metric_result


class AIInsightSingleFlowV411Test(SimpleTestCase):
    def _result(self):
        risk = SimpleNamespace(
            no_item=9,
            peristiwa_risiko="Kendala Pasokan Energi Primer",
        )
        return SimpleNamespace(
            metric_snapshot={
                "metrics": [
                    {"metric_name": "Realisasi Volume Gas", "mean_score": 100},
                    {"metric_name": "Realisasi Biaya Gas", "mean_score": 40},
                ]
            },
            simulation_snapshot={
                "projection_rows": [{"mean_score": 60}, {"mean_score": 70}],
                "target_analysis": {"enabled": True},
            },
            corporate_risk_item=risk,
            forecast_periode="Aug 2026",
            status_hasil="Berisiko",
            composite_score=100,
            p80_score=100,
            target_status="Tidak Tercapai",
            risk_status="Berisiko",
            forecast_total=43436881.49,
            target_value=42085000,
            target_gap=1351881.49,
            potential_loss=6069000.49,
            probability_achieve_target=31.94,
            probability_not_achieve_target=68.06,
            var_95=6069000.49,
            requires_mitigation=True,
        )

    @patch("corporate_risk.services.MultiMetricAIInsightKorporat.objects.update_or_create")
    @patch("corporate_risk.services._polish_multi_metric_insight_with_ai")
    def test_one_ai_polish_call_and_same_insight_management_draft(
        self, polish_mock, update_mock
    ):
        polish_mock.side_effect = lambda result, summary, findings, actions: (
            "AI SUMMARY",
            findings,
            "1. Action A\n2. Action B\n3. Action C\n4. Action D",
        )
        saved = SimpleNamespace(pk=77)
        update_mock.return_value = (saved, True)

        insight = generate_rule_based_ai_insight_for_multi_metric_result(
            self._result(),
            user_context="Pertimbangkan kontrak gas dan keterbatasan pasokan.",
        )

        self.assertIs(insight, saved)
        self.assertEqual(polish_mock.call_count, 1)
        defaults = update_mock.call_args.kwargs["defaults"]
        self.assertEqual(
            defaults["user_context"],
            "Pertimbangkan kontrak gas dan keterbatasan pasokan.",
        )
        self.assertIn("AI SUMMARY", defaults["management_decision_draft"])
        self.assertIn("Action A", defaults["management_decision_draft"])
        self.assertIn("AI Draft", defaults["management_decision_draft"])

class AIInsightContextAwareV4112Test(AIInsightSingleFlowV411Test):
    @patch("corporate_risk.services.MultiMetricAIInsightKorporat.objects.update_or_create")
    @patch("corporate_risk.services._polish_multi_metric_insight_with_ai")
    def test_context_aware_wrapper_keeps_single_ai_call(
        self,
        polish_mock,
        update_mock,
    ):
        captured = {}

        def fake_polish(result, summary, findings, actions):
            captured["summary"] = summary
            captured["findings"] = findings
            captured["actions"] = actions
            return (
                "AI SUMMARY TERPADU",
                "AI FINDINGS TERPADU",
                "1. ACTION TERPADU",
            )

        polish_mock.side_effect = fake_polish
        update_mock.return_value = (SimpleNamespace(pk=88), True)

        generate_rule_based_ai_insight_for_multi_metric_result(
            self._result(),
            user_context=(
                "Risk driver: keterbatasan pasokan gas. "
                "Program perlakuan: evaluasi kontrak dan optimasi dispatch."
            ),
        )

        self.assertEqual(polish_mock.call_count, 1)
        self.assertNotIn(
            "USER BUSINESS CONTEXT / ANALYSIS DIRECTION",
            captured["summary"],
        )
        self.assertIn(
            "USER BUSINESS CONTEXT / ANALYSIS DIRECTION",
            captured["findings"],
        )
        self.assertIn(
            "keterbatasan pasokan gas",
            captured["findings"],
        )
        self.assertIn(
            "Do NOT force unrelated context into this risk",
            captured["findings"],
        )
        self.assertNotIn(
            "USER BUSINESS CONTEXT / ANALYSIS DIRECTION",
            captured["actions"],
        )

        defaults = update_mock.call_args.kwargs["defaults"]
        self.assertEqual(defaults["executive_summary"], "AI SUMMARY TERPADU")
        self.assertEqual(defaults["key_findings"], "AI FINDINGS TERPADU")
        self.assertIn("ACTION TERPADU", defaults["management_decision_draft"])

