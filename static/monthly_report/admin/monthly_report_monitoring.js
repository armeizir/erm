(function () {
  function updateAddButtonText() {
    document.querySelectorAll("#items-group .add-row a").forEach(function (link) {
      link.textContent = "Tambah Risiko untuk Dipantau";
    });
  }

  document.addEventListener("DOMContentLoaded", updateAddButtonText);
  document.body.addEventListener("formset:added", function (event) {
    updateAddButtonText();
    var row = event.target && event.target.closest ? event.target.closest(".monitoring-risk") : null;
    var details = row && row.querySelector("details");
    if (details) details.open = true;
  });

  function parseThresholdNumber(rawValue, unit) {
    var text = String(rawValue || "").replace(/\s+/g, "");
    var sign = "";
    if (text[0] === "+" || text[0] === "-") {
      sign = text[0];
      text = text.slice(1);
    }
    var normalizedUnit = String(unit || "").trim().toLowerCase();
    var percentUnit = ["%", "persen", "percent", "percentage"].indexOf(normalizedUnit) !== -1;

    if (text.indexOf(".") !== -1 && text.indexOf(",") !== -1) {
      if (text.lastIndexOf(",") > text.lastIndexOf(".")) {
        text = text.replace(/\./g, "").replace(",", ".");
      } else {
        text = text.replace(/,/g, "");
      }
    } else if (text.indexOf(",") !== -1) {
      text = text.replace(",", ".");
    } else if (text.indexOf(".") !== -1) {
      var parts = text.split(".");
      var looksGroupedInteger = !percentUnit && parts[0] !== "0" && parts[0].length <= 3 &&
        parts.length >= 2 && parts.slice(1).every(function (part) {
          return /^\d{3}$/.test(part);
        });
      if (looksGroupedInteger) text = parts.join("");
    }
    return Number(sign + text);
  }

  function thresholdMatches(expression, value, unit) {
    var text = (expression || "").replace(/[–—]/g, "-").toLowerCase();
    var numbers = (text.match(/\d+(?:[.,]\d+)*/g) || []).map(function (number) {
      return parseThresholdNumber(number, unit);
    });
    if (!numbers.length) return false;
    if (numbers.length > 1) {
      var lowerOk = text.indexOf(">") !== -1 ? value > numbers[0] : value >= numbers[0];
      return lowerOk && value <= numbers[1];
    }
    if (text.indexOf(">=") !== -1 || text.indexOf("≥") !== -1) return value >= numbers[0];
    if (text.indexOf("<=") !== -1 || text.indexOf("≤") !== -1) return value <= numbers[0];
    if (text.indexOf(">") !== -1) return value > numbers[0];
    if (text.indexOf("<") !== -1) return value < numbers[0];
    return value === numbers[0];
  }

  document.addEventListener("input", function (event) {
    var input = event.target.closest("input[data-kri-direction]");
    if (!input) return;
    var body = input.closest(".monitoring-risk-body");
    var statusTarget = body && body.querySelector(".field-status_threshold_kri .readonly");
    var rangeTarget = body && body.querySelector(".field-rentang_threshold_kri .readonly");
    if (!statusTarget || !rangeTarget) return;
    if (input.value === "") {
      statusTarget.textContent = "Belum diisi";
      rangeTarget.textContent = "Belum diisi";
      return;
    }
    var value = Number(input.value);
    var unit = input.dataset.kriUnit || "";
    var categories = [
      ["green", "Hijau", input.dataset.kriGreen],
      ["yellow", "Kuning", input.dataset.kriYellow],
      ["red", "Merah", input.dataset.kriRed]
    ].filter(function (entry) { return thresholdMatches(entry[2], value, unit); });
    if (categories.length !== 1) {
      statusTarget.textContent = "Konfigurasi perlu diperiksa";
      rangeTarget.textContent = "Threshold tumpang tindih atau memiliki celah";
      return;
    }
    statusTarget.innerHTML = '<span class="kri-status-badge kri-' + categories[0][0] + '">' + categories[0][1] + "</span>";
    rangeTarget.textContent = categories[0][2];
  });
})();
