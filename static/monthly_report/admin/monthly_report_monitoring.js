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

  function thresholdMatches(expression, value) {
    var text = (expression || "").replace(/[–—]/g, "-").toLowerCase();
    var numbers = (text.match(/\d+(?:[.,]\d+)?/g) || []).map(function (number) {
      return Number(number.replace(",", "."));
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
    var categories = [
      ["green", "Hijau", input.dataset.kriGreen],
      ["yellow", "Kuning", input.dataset.kriYellow],
      ["red", "Merah", input.dataset.kriRed]
    ].filter(function (entry) { return thresholdMatches(entry[2], value); });
    if (categories.length !== 1) {
      statusTarget.textContent = "Konfigurasi perlu diperiksa";
      rangeTarget.textContent = "Threshold tumpang tindih atau memiliki celah";
      return;
    }
    statusTarget.innerHTML = '<span class="kri-status-badge kri-' + categories[0][0] + '">' + categories[0][1] + "</span>";
    rangeTarget.textContent = categories[0][2];
  });
})();
