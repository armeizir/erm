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

  var pairingDrawer = null;
  var pairingOverlay = null;
  var pairingContent = null;
  var pairingTrigger = null;
  var pairingDirty = false;

  function initializePairingDrawer() {
    pairingDrawer = document.querySelector("[data-pairing-review-drawer]");
    pairingOverlay = document.querySelector("[data-pairing-review-overlay]");
    pairingContent = document.querySelector("[data-pairing-review-content]");
    if (pairingOverlay && !pairingOverlay.dataset.pairingCloseBound) {
      pairingOverlay.dataset.pairingCloseBound = "1";
      pairingOverlay.addEventListener("click", function () {
        closePairingDrawer(false);
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializePairingDrawer);
  } else {
    initializePairingDrawer();
  }

  function csrfToken() {
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (input) return input.value;
    var match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function closePairingDrawer(force) {
    if (!pairingDrawer || pairingDrawer.hidden) return;
    if (!force && pairingDirty && !window.confirm("Review belum disimpan. Tutup drawer?")) return;
    pairingDrawer.hidden = true;
    pairingOverlay.hidden = true;
    document.body.classList.remove("pairing-review-is-open");
    pairingDirty = false;
    if (pairingTrigger) pairingTrigger.focus();
  }

  function showPairingError(message) {
    var feedback = pairingDrawer && pairingDrawer.querySelector("[data-pairing-review-feedback]");
    if (!feedback) return;
    feedback.textContent = message;
    feedback.classList.add("is-error");
    feedback.hidden = false;
  }

  async function openPairingDrawer(trigger) {
    if (!pairingDrawer || !pairingOverlay || !pairingContent) return;
    pairingTrigger = trigger;
    pairingDirty = false;
    pairingContent.innerHTML = '<div class="pairing-review-drawer-loading">Memuat review risiko…</div>';
    pairingDrawer.hidden = false;
    pairingOverlay.hidden = false;
    document.body.classList.add("pairing-review-is-open");
    try {
      var response = await fetch(trigger.dataset.pairingReviewUrl, {
        credentials: "same-origin",
        headers: {"X-Requested-With": "XMLHttpRequest"}
      });
      if (!response.ok) throw new Error("Review risiko tidak dapat dimuat.");
      pairingContent.innerHTML = await response.text();
      var closeButton = pairingDrawer.querySelector("[data-pairing-review-close]");
      if (closeButton) closeButton.focus();
    } catch (error) {
      pairingContent.innerHTML = '<div class="pairing-review-drawer-loading is-error">' + error.message + "</div>";
    }
  }

  document.addEventListener("click", function (event) {
    var openButton = event.target.closest("[data-pairing-review-url]");
    if (openButton) {
      event.preventDefault();
      event.stopPropagation();
      openPairingDrawer(openButton);
      return;
    }
    if (event.target.closest("[data-pairing-review-close]")) {
      event.preventDefault();
      closePairingDrawer(false);
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && pairingDrawer && !pairingDrawer.hidden) {
      event.preventDefault();
      closePairingDrawer(false);
    }
  });

  document.addEventListener("change", function (event) {
    if (event.target.closest("[data-pairing-review-panel]")) pairingDirty = true;
  });
  document.addEventListener("input", function (event) {
    if (event.target.closest("[data-pairing-review-panel]")) pairingDirty = true;
  });

  document.addEventListener("click", async function (event) {
    var saveButton = event.target.closest("[data-pairing-review-save]");
    if (!saveButton) return;
    event.preventDefault();
    var panel = saveButton.closest("[data-pairing-review-panel]");
    var decision = panel.querySelector('input[type="radio"]:checked');
    var comment = panel.querySelector("[data-pairing-review-comment]");
    if (!decision) {
      showPairingError("Pilih hasil review Pairing.");
      return;
    }
    if (decision.value === "perlu_perbaikan" && !comment.value.trim()) {
      showPairingError("Komentar wajib diisi jika laporan perlu diperbaiki.");
      comment.focus();
      return;
    }
    saveButton.disabled = true;
    var data = new URLSearchParams({
      modal: "1",
      item_id: panel.dataset.itemId,
      decision: decision.value,
      comment: comment.value.trim()
    });
    try {
      var response = await fetch(saveButton.dataset.postUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          "X-CSRFToken": csrfToken(),
          "X-Requested-With": "XMLHttpRequest"
        },
        body: data.toString()
      });
      var result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || "Review gagal disimpan.");
      var status = document.querySelector('[data-pairing-status-for="' + result.item_id + '"]');
      if (status) status.textContent = result.decision_label;
      pairingDirty = false;
      closePairingDrawer(true);
      if (result.report_status !== "approved") {
        document.querySelectorAll("[data-pairing-review-url]").forEach(function (button) {
          button.disabled = true;
        });
      }
    } catch (error) {
      showPairingError(error.message);
      saveButton.disabled = false;
    }
  });
})();
