(function () {
  function getRiskItemsUrl() {
    return window.location.pathname.replace(/(?:add\/|\d+\/change\/)?$/, "risk-items/");
  }

  function getRiskItemSelects() {
    return Array.from(document.querySelectorAll("select[name$='-risk_event']"));
  }

  function urlWithReassessment(url, reassessmentId) {
    var parsed = new URL(url, window.location.origin);
    parsed.searchParams.set("reassessment", reassessmentId);
    return parsed.pathname + parsed.search;
  }

  function refreshAutocomplete(select) {
    if (!window.django || !django.jQuery) {
      return;
    }
    var $select = django.jQuery(select);
    if (!$select.hasClass("admin-autocomplete")) {
      return;
    }
    if ($select.data("select2")) {
      $select.select2("destroy");
    }
    if ($select.djangoAdminSelect2) {
      $select.djangoAdminSelect2();
    }
  }

  function updateAutocompleteUrl(select, reassessmentId) {
    if (!select.classList.contains("admin-autocomplete")) {
      return;
    }
    var baseUrl = select.dataset.baseAutocompleteUrl || select.getAttribute("data-ajax--url");
    if (!baseUrl) {
      return;
    }
    select.dataset.baseAutocompleteUrl = baseUrl;
    select.setAttribute("data-ajax--url", urlWithReassessment(baseUrl, reassessmentId));
    refreshAutocomplete(select);
  }

  function resetSelect(select, placeholder) {
    select.innerHTML = "";
    var option = document.createElement("option");
    option.value = "";
    option.textContent = placeholder;
    select.appendChild(option);
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
        if (select.dataset.baseAutocompleteUrl) {
          select.setAttribute("data-ajax--url", select.dataset.baseAutocompleteUrl);
          refreshAutocomplete(select);
        }
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
          updateAutocompleteUrl(select, reassessmentId);
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
