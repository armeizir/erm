(function () {
    "use strict";

    const LEVELS = [
        [1, 5, "Rendah", "risk-level-low"],
        [6, 11, "Rendah ke Moderat", "risk-level-low-moderate"],
        [12, 15, "Moderat", "risk-level-moderate"],
        [16, 19, "Moderat ke Tinggi", "risk-level-moderate-high"],
        [20, 25, "Tinggi", "risk-level-high"],
    ];

    function classify(value) {
        if (value === null || String(value).trim() === "") return null;
        const scale = Number(value);
        if (!Number.isInteger(scale) || scale < 1 || scale > 25) return null;
        const match = LEVELS.find(([lower, upper]) => scale >= lower && scale <= upper);
        return match ? {label: match[2], className: match[3]} : null;
    }

    function decorate(element, result) {
        element.classList.remove(
            "risk-level-badge",
            "risk-level-low",
            "risk-level-low-moderate",
            "risk-level-moderate",
            "risk-level-moderate-high",
            "risk-level-high"
        );
        if (!result) return;
        element.textContent = result.label;
        element.classList.add("risk-level-badge", result.className);
    }

    function updateContainer(container) {
        for (let quarter = 1; quarter <= 4; quarter += 1) {
            const scale = container.querySelector(
                `[name$="skala_risiko_q${quarter}"], .field-skala_risiko_q${quarter} .readonly`
            );
            const level = container.querySelector(
                `.field-level_risiko_q${quarter}_display .readonly, ` +
                `.field-level_nilai_risiko_q${quarter} .readonly`
            );
            if (scale && level) decorate(level, classify(scale.value || scale.textContent));
        }
    }

    function updateAll() {
        document.querySelectorAll("fieldset, tr.form-row, form").forEach(updateContainer);
    }

    document.addEventListener("change", function (event) {
        if (/skala_risiko_q[1-4]$/.test(event.target.name || "")) updateAll();
    });
    document.addEventListener("DOMContentLoaded", updateAll);
    document.addEventListener("formset:added", updateAll);
})();
