import json
from openai import OpenAI

from risk.models import AppSetting

from .models import AIInsightKorporat, MonteCarloKorporatResult


def generate_ai_insight_for_result(result_id: int, model_name: str | None = None):
    app_setting = AppSetting.get_solo()
    api_key = app_setting.runtime_ai_api_key
    if not api_key:
        raise ValueError("API Key AI belum dikonfigurasi pada Pengaturan Aplikasi.")
    model_name = model_name or app_setting.ai_model or "gpt-5.4-mini"

    result = MonteCarloKorporatResult.objects.select_related(
        "corporate_risk_item"
    ).get(pk=result_id)

    payload = {
        "risk_name": result.corporate_risk_item.peristiwa_risiko,
        "metric_name": result.metric_name,
        "target_value": float(result.target_value) if result.target_value else None,
        "mean": float(result.mean_value) if result.mean_value is not None else None,
        "p80": float(result.p80_value) if result.p80_value is not None else None,
        "probability": float(result.probability_meet_target)
        if result.probability_meet_target is not None else None,
    }

    prompt = f"""
Anda adalah analis risiko PLN Batam.

Buat JSON valid dengan field:
- executive_summary
- key_drivers
- recommended_actions

Gunakan bahasa Indonesia formal dan jangan menambah data di luar input.

Data:
{json.dumps(payload, ensure_ascii=False)}
"""

    client = OpenAI(api_key=api_key)

    response = client.responses.create(
        model=model_name,
        input=prompt,
    )

    text = response.output_text
    data = json.loads(text)

    insight = AIInsightKorporat.objects.create(
        corporate_risk_item=result.corporate_risk_item,
        monte_carlo_result=result,
        executive_summary=data.get("executive_summary"),
        key_drivers=data.get("key_drivers", []),
        recommended_actions=data.get("recommended_actions", []),
    )

    return insight