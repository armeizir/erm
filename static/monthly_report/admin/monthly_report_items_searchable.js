(function () {
  function getRiskItemsUrl() {
    return window.location.pathname.replace(/(?:add\/|\d+\/change\/)?$/, "risk-items/");
  }

  function getRiskItemSelects() {
    return Array.from(document.querySelectorAll("select[name$='-risk_event']"));
  }

  function enhanceLocalSearch(select) {
    if (!window.django || !django.jQuery) {
      return;
    }
    var $select = django.jQuery(select);
    if (!$select.select2) {
      return;
    }
    if ($select.data("select2")) {
      $select.select2("destroy");
    }
    $select.addClass("admin-autocomplete");
    $select.select2({
      allowClear: true,
      dropdownAutoWidth: true,
      placeholder: select.options[0] ? select.options[0].textContent : "---------",
      width: "resolve"
    });
  }

  function resetSelect(select, placeholder) {
    select.innerHTML = "";
    var option = document.createElement("option");
    option.value = "";
    option.textContent = placeholder;
    select.appendChild(option);
    enhanceLocalSearch(select);
  }

  function fillSelect(select, items, selectedValue) {
    resetSelect(select, "---------");
    items.forEach(function (item) {
      var option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.text;
      if (String(item.id) === String(selectedValue)) {
        option.selected = true;
      }
      select.appendChild(option);
    });
    enhanceLocalSearch(select);
  }

  function loadRiskItems() {
    var reassessmentSelect = document.getElementById("id_reassessment");
    if (!reassessmentSelect) {
      return;
    }

    var reassessmentId = reassessmentSelect.value;
    var selects = getRiskItemSelects();

    if (!reassessmentId) {
      selects.forEach(function (select) {
        resetSelect(select, "Pilih Profil Risiko terlebih dahulu");
      });
      return;
    }

    fetch(getRiskItemsUrl() + "?reassessment=" + encodeURIComponent(reassessmentId), {
      headers: { "X-Requested-With": "XMLHttpRequest" },
    })
      .then(function (response) {
        return response.json();
      })
      .then(function (payload) {
        selects.forEach(function (select) {
          fillSelect(select, payload.items || [], select.value);
        });
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var reassessmentSelect = document.getElementById("id_reassessment");
    if (!reassessmentSelect) {
      return;
    }

    reassessmentSelect.addEventListener("change", loadRiskItems);
    document.body.addEventListener("formset:added", loadRiskItems);
    loadRiskItems();
  });
})();
