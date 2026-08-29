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

  function fieldByPrefix(prefix, fieldName) {
    return document.getElementById(`${prefix}${fieldName}`);
  }

  function prefixFrom(element, suffix) {
    if (!element || !element.id || !element.id.endsWith(suffix)) return null;
    return element.id.slice(0, -suffix.length);
  }

  function setNumericState(element, riskType) {
    if (!element) return;

    const qualitative = riskType === "kualitatif";
    const quantitative = riskType === "kuantitatif";
    const unresolved = !qualitative && !quantitative;

    element.readOnly = qualitative || unresolved;

    if (qualitative || unresolved) {
      element.required = false;
      element.setAttribute("aria-disabled", "true");
      element.setAttribute("tabindex", "-1");
    } else {
      element.removeAttribute("aria-disabled");
      element.removeAttribute("tabindex");
    }

    element.classList.toggle("qualitative-optional-input", qualitative);
    element.classList.toggle("risk-type-unresolved-input", unresolved);

    if (qualitative) {
      element.setAttribute(
        "title",
        "Tidak wajib untuk risiko kualitatif. Nilai eksposur diisi langsung."
      );
      element.setAttribute("placeholder", "Tidak wajib (kualitatif)");
    } else if (unresolved) {
      element.setAttribute("title", "Pilih Jenis Risiko terlebih dahulu.");
      element.setAttribute("placeholder", "Pilih Jenis Risiko");
    } else {
      element.removeAttribute("title");
      element.removeAttribute("placeholder");
    }
  }

  function updateQuarter(prefix, quarter, riskType) {
    const qualitative = riskType === "kualitatif";
    const quantitative = riskType === "kuantitatif";
    const unresolved = !qualitative && !quantitative;

    const impact = fieldByPrefix(prefix, `nilai_dampak_q${quarter}`);
    const probability = fieldByPrefix(prefix, `nilai_probabilitas_q${quarter}`);
    const exposure = fieldByPrefix(prefix, `eksposur_risiko_q${quarter}`);
    if (!exposure) return;

    setNumericState(impact, riskType);
    setNumericState(probability, riskType);

    exposure.readOnly = !qualitative;
    exposure.classList.toggle("qualitative-exposure-input", qualitative);
    exposure.classList.toggle("quantitative-exposure-input", quantitative);
    exposure.classList.toggle("risk-type-unresolved-input", unresolved);

    if (unresolved) {
      exposure.setAttribute(
        "title",
        "Jenis Risiko belum ditetapkan. Nilai eksposur existing tidak dihitung ulang."
      );
      exposure.setAttribute("placeholder", "Pilih Jenis Risiko");
      return;
    }

    if (qualitative) {
      exposure.setAttribute(
        "title",
        "Isi langsung Nilai Eksposur Risiko untuk quarter ini."
      );
      exposure.setAttribute("placeholder", "Input eksposur risiko");
      return;
    }

    exposure.setAttribute(
      "title",
      "Dihitung otomatis dari Nilai Dampak × Nilai Probabilitas."
    );
    exposure.setAttribute("placeholder", "Dihitung otomatis");

    const impactValue = parseDecimal(impact && impact.value);
    const probabilityValue = parseDecimal(probability && probability.value);
    if (impactValue === null || probabilityValue === null) {
      exposure.value = "";
      return;
    }

    const calculated = impactValue * (probabilityValue / 100);
    exposure.value = Number.isFinite(calculated) ? calculated.toFixed(2) : "";
  }

  function updateRiskType(selector) {
    const prefix = prefixFrom(selector, "jenis_risiko");
    if (prefix === null) return;

    let riskType = (selector.value || "").toLowerCase();

    // Kategori Dampak menjadi penentu tambahan.
    // Jika kategori dipilih "Dampak Kualitatif", field numerik dampak
    // dan probabilitas harus nonaktif meskipun jenis_risiko belum berubah.
    const impactCategory = fieldByPrefix(prefix, "kategori_dampak");
    if (impactCategory && impactCategory.selectedIndex >= 0) {
      const categoryText = (
        impactCategory.options[impactCategory.selectedIndex].text || ""
      ).trim().toLowerCase();

      if (categoryText.includes("kualitatif")) {
        riskType = "kualitatif";
      } else if (categoryText.includes("kuantitatif")) {
        riskType = "kuantitatif";
      }
    }

    const qualitative = riskType === "kualitatif";
    const quantitative = riskType === "kuantitatif";
    const unresolved = !qualitative && !quantitative;

    const root = selector.closest("tr.form-row, .inline-related, form") || document;
    root.classList.toggle("risk-mode-qualitative", qualitative);
    root.classList.toggle("risk-mode-quantitative", quantitative);
    root.classList.toggle("risk-mode-unresolved", unresolved);

    setNumericState(fieldByPrefix(prefix, "nilai_dampak"), riskType);
    setNumericState(fieldByPrefix(prefix, "nilai_probabilitas"), riskType);

    for (let quarter = 1; quarter <= 4; quarter += 1) {
      updateQuarter(prefix, quarter, riskType);
    }
  }

  function bindSelector(selector) {
    if (!selector || selector.dataset.exposureBound === "1") return;
    selector.dataset.exposureBound = "1";
    selector.addEventListener("change", function () {
      updateRiskType(selector);
    });

    const prefix = prefixFrom(selector, "jenis_risiko");
    if (prefix !== null) {
      const impactCategory = fieldByPrefix(prefix, "kategori_dampak");
      if (impactCategory && impactCategory.dataset.exposureBound !== "1") {
        impactCategory.dataset.exposureBound = "1";
        impactCategory.addEventListener("change", function () {
          updateRiskType(selector);
        });
      }

      for (let quarter = 1; quarter <= 4; quarter += 1) {
        const impact = fieldByPrefix(prefix, `nilai_dampak_q${quarter}`);
        const probability = fieldByPrefix(prefix, `nilai_probabilitas_q${quarter}`);
        [impact, probability].forEach(function (element) {
          if (!element || element.dataset.exposureBound === "1") return;
          element.dataset.exposureBound = "1";
          element.addEventListener("input", function () {
            updateRiskType(selector);
          });
        });
      }
    }
    updateRiskType(selector);
  }

  function bindAll() {
    document.querySelectorAll('[id$="jenis_risiko"]').forEach(bindSelector);
  }

  document.addEventListener("DOMContentLoaded", bindAll);
  document.addEventListener("formset:added", bindAll);
})();
