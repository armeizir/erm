(function () {
  "use strict";

  const formatter = new Intl.NumberFormat("id-ID", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  function parseDecimal(value) {
    const text = String(value ?? "").trim();
    if (text === "") return null;
    const number = Number(text);
    return Number.isFinite(number) ? number : null;
  }

  function previewQuarter(quarter, impact) {
    const prefix = impact.id.slice(
      0,
      -`nilai_dampak_q${quarter}`.length
    );
    const probability = document.getElementById(
      `${prefix}nilai_probabilitas_q${quarter}`
    );
    const container = impact.closest("tr.form-row") || document;
    const output = container.querySelector(
      `.field-eksposur_risiko_q${quarter} .readonly`
    );
    if (!impact || !probability || !output) return;

    const impactValue = parseDecimal(impact.value);
    const probabilityValue = parseDecimal(probability.value);
    if (impactValue === null || probabilityValue === null) {
      output.textContent = "-";
      return;
    }
    // Preview only. The Django model recalculates with Decimal/ROUND_HALF_UP.
    output.textContent = formatter.format(
      impactValue * (probabilityValue / 100)
    );
  }

  document.addEventListener("DOMContentLoaded", function () {
    for (let quarter = 1; quarter <= 4; quarter += 1) {
      const impacts = document.querySelectorAll(
        `[id$="nilai_dampak_q${quarter}"]`
      );
      impacts.forEach(function (impact) {
        const prefix = impact.id.slice(
          0,
          -`nilai_dampak_q${quarter}`.length
        );
        const probability = document.getElementById(
          `${prefix}nilai_probabilitas_q${quarter}`
        );
        [impact, probability].forEach(function (element) {
          if (!element) return;
          element.addEventListener("input", function () {
            previewQuarter(quarter, impact);
          });
        });
        previewQuarter(quarter, impact);
      });
    }
  });
})();
