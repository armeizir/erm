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
})();
