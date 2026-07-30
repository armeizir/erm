(function () {
    "use strict";

    document.addEventListener("click", function (event) {
        const button = event.target.closest(
            ".monthly-select-all, .monthly-clear-all"
        );
        if (!button) {
            return;
        }

        const timeline = button.closest(".monthly-timeline");
        if (!timeline) {
            return;
        }

        const checked = button.classList.contains("monthly-select-all");
        timeline.querySelectorAll('input[type="checkbox"]').forEach(function (input) {
            if (!input.disabled) {
                input.checked = checked;
                input.dispatchEvent(new Event("change", { bubbles: true }));
            }
        });
    });
})();
