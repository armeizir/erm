from __future__ import annotations

from pathlib import Path

from risk.executive_signage import _build_risk_card
from risk.models import ProfilRisikoKorporatItem


YEAR = 2026
TEMPLATE = Path("templates/executive_risk_dashboard.html")
BLANKS = (None, "", "–", "-")


def get_card(no):
    risk = ProfilRisikoKorporatItem.objects.get(summary__tahun=YEAR, no_risiko=no)
    return _build_risk_card(risk, YEAR)


def check(label, condition, detail=""):
    status = "PASS" if condition else "REVIEW"
    suffix = f" | {detail}" if detail else ""
    print(f"{status:<8} {label}{suffix}")
    return bool(condition)


print("=" * 156)
print("ERM LOCAL — EXECUTIVE RISK VISUAL SEMANTICS V4.7 — READ ONLY")
print("=" * 156)
print("DB WRITE : NONE")

template = TEMPLATE.read_text(encoding="utf-8")

print()
print("A. TEMPLATE SEMANTICS")
print("-" * 156)
checks = [
    check(
        "IMPACT headline removed",
        '<div class="ik">IMPACT' not in template,
    ),
    check(
        "Worst Case percentile template present",
        "WORST CASE{% if risk_card.worst_case_percentile %} ({{ risk_card.worst_case_percentile }}){% endif %}"
        in template,
    ),
    check(
        "Indicator source label is dynamic",
        "{{ risk_card.rows_source|upper }} — indikator risiko" in template,
    ),
    check(
        "Direction header says ARAH METRIK",
        "<div>ARAH METRIK</div>" in template,
    ),
    check(
        "Up/down arrows use neutral color",
        ".trend.up,.trend.down{color:#2c5d89}" in template,
    ),
]

print()
print("B. DIRECTION-AWARE WORST CASE LABELS")
print("-" * 156)

cards = {no: get_card(no) for no in (2, 4, 5, 8, 9, 10)}
for no in (2, 4, 5, 8, 9, 10):
    c = cards[no]
    print(
        f"RISK #{no:<2} | WORST={c.get('worst_case')} | "
        f"PCTL={c.get('worst_case_percentile')!r} | "
        f"VALID={c.get('model_validation')!r}"
    )

checks.extend([
    check("Risk #2 worst case label P5", cards[2].get("worst_case_percentile") == "P5"),
    check("Risk #4 worst case label P5", cards[4].get("worst_case_percentile") == "P5"),
    check(
        "Risk #5 REVIEW has no percentile label",
        cards[5].get("worst_case_percentile") in BLANKS
        and cards[5].get("worst_case") in BLANKS,
    ),
    check(
        "Risk #8 Actual+Target has no percentile label",
        cards[8].get("worst_case_percentile") in BLANKS
        and cards[8].get("worst_case") in BLANKS,
    ),
    check("Risk #9 worst case label P95", cards[9].get("worst_case_percentile") == "P95"),
    check("Risk #10 worst case label P95", cards[10].get("worst_case_percentile") == "P95"),
    check(
        "Risk #9 potential impact still populated",
        cards[9].get("potential_loss") not in BLANKS,
        f"potential_loss={cards[9].get('potential_loss')}",
    ),
])

print()
print("C. EXPECTED VISUAL RESULT")
print("-" * 156)
print("Risk #2/#4  : WORST CASE (P5)")
print("Risk #9/#10 : WORST CASE (P95)")
print("Risk #5/#8  : WORST CASE with value – and no percentile")
print("Indicator   : RISK METRIC or KRI PROFIL RISIKO — indikator risiko")
print("Arrow       : neutral blue; direction only, not status")

print()
print("=" * 156)
if all(checks):
    print("OVERALL V4.7 VISUAL SEMANTICS : PASS — SAFE FOR SCREENSHOT UAT")
else:
    print("OVERALL V4.7 VISUAL SEMANTICS : REVIEW — FIX BEFORE SCREENSHOT UAT")
print("=" * 156)
