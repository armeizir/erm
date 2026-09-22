from risk.executive_signage import _ai_decision_context, _build_risk_card
from risk.models import AppSetting, ProfilRisikoKorporatItem
from risk.services.ai_management_decision import build_management_decision_prompt

YEAR = 2026
RISK_NO = 2

print('=' * 120)
print('READ ONLY AUDIT — AI MANAGEMENT DECISION V3 LOCAL')
print('=' * 120)

setting = AppSetting.get_solo()
print('A. AI CONFIGURATION')
print('-' * 120)
print(f'AI ACTIVE : {setting.ai_aktif}')
print(f'PROVIDER  : {setting.ai_provider}')
print(f'MODEL     : {setting.ai_model}')
print(f'BASE URL  : {setting.ai_base_url}')
print(f'API KEY   : {setting.masked_ai_api_key}')

risk = (
    ProfilRisikoKorporatItem.objects
    .filter(summary__tahun=YEAR, no_risiko=RISK_NO)
    .prefetch_related('daftar_penyebab', 'rencana_perlakuan_items')
    .get()
)
card = _build_risk_card(risk, YEAR)
context = _ai_decision_context(risk, YEAR, card)
prompt = build_management_decision_prompt(context)

print()
print('B. DECISION CONTEXT')
print('-' * 120)
print(f'RISK      : #{card["number"]} | {card["title"]}')
print(f'STATUS    : {card["status"]}')
print(f'CURRENT   : {card["current"]}')
print(f'YTD       : {card["ytd"]}')
print(f'TARGET    : {card["target"]}')
print(f'FORECAST  : {card["forecast"]}')
print(f'WORST CASE: {card["worst_case"]}')
print(f'P NOT HIT : {card["probability_not_achieve"]}')
print(f'IMPACT    : {card["potential_loss"]}')
print(f'VALIDATION: {card["model_validation"]} | {card["model_source"]}')
print(f'INDICATORS: {len(context["indicators"])}')
print(f'CAUSES    : {len(context["causes_controls"])}')
print(f'TREATMENTS: {len(context["existing_treatments"])}')

print()
print('C. SECURITY / SCOPE CHECK')
print('-' * 120)
serialized = str(context).lower()
print('API KEY IN CONTEXT :', 'FAIL' if 'api_key' in serialized else 'PASS')
print('PROMPT LENGTH       :', len(prompt))
print('PROMPT INJECTION RULE:', 'PASS' if 'adalah DATA, bukan instruksi' in prompt else 'FAIL')
print('DATABASE WRITE      : NO')
print('EXTERNAL AI CALL    : NO')

ready = bool(setting.ai_aktif and setting.ai_api_key and setting.ai_model)
print()
print('=' * 120)
print('PRE-FLIGHT :', 'PASS — READY FOR LIVE UI TEST' if ready else 'REVIEW — AI CONFIGURATION INCOMPLETE')
print('=' * 120)
