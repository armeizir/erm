from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from corporate_risk.services import (
    _generate_management_language,
    _openai_generate_management_language,
    _openai_response_output_text,
)
from risk.models import AppSetting


class OpenAIMultiMetricInsightV41112Test(SimpleTestCase):
    def _setting(self):
        setting = Mock(spec=AppSetting)
        setting.ai_provider = AppSetting.AI_PROVIDER_OPENAI
        setting.ai_model = "gpt-5.6-sol"
        setting.ai_base_url = "https://api.openai.com/v1"
        setting.ai_temperature = 0.20
        setting.runtime_ai_api_key = "test-secret"
        return setting

    def test_extracts_responses_api_output_text(self):
        payload = {
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": '{"executive_summary":"A","key_findings":"B","recommended_actions":"C"}',
                }],
            }]
        }
        text = _openai_response_output_text(payload)
        self.assertIn('"executive_summary":"A"', text)

    @patch("corporate_risk.services.httpx.post")
    def test_openai_uses_responses_endpoint_and_structured_output(self, post):
        response = Mock()
        response.status_code = 200
        response.headers = {"x-request-id": "req_test"}
        response.json.return_value = {
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": (
                        '{"executive_summary":"A",'
                        '"key_findings":"B",'
                        '"recommended_actions":"C"}'
                    ),
                }],
            }]
        }
        response.raise_for_status.return_value = None
        post.return_value = response

        data = _openai_generate_management_language(self._setting(), "test prompt")

        self.assertEqual(data["executive_summary"], "A")
        self.assertEqual(data["key_findings"], "B")
        self.assertEqual(data["recommended_actions"], "C")

        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.openai.com/v1/responses")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-secret")
        self.assertEqual(kwargs["json"]["model"], "gpt-5.6-sol")
        self.assertEqual(kwargs["json"]["text"]["format"]["type"], "json_schema")

    @patch("corporate_risk.services._openai_generate_management_language")
    def test_dispatches_openai_provider(self, openai_call):
        openai_call.return_value = {
            "executive_summary": "A",
            "key_findings": "B",
            "recommended_actions": "C",
        }

        result = _generate_management_language(self._setting(), "prompt")

        self.assertEqual(result["executive_summary"], "A")
        openai_call.assert_called_once()
