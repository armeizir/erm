(function () {
    "use strict";

    function relatedElement(element, suffix) {
        const prefix = element.name.replace(
            /(pic_organization_unit|pic_user_assignment|use_owner_organization)$/,
            ""
        );
        return document.querySelector('[name="' + prefix + suffix + '"]');
    }

    async function refreshAssignments(organizationSelect) {
        const assignmentSelect = relatedElement(
            organizationSelect,
            "pic_user_assignment"
        );
        if (!assignmentSelect) {
            return;
        }

        const selectedAssignment = assignmentSelect.value;
        assignmentSelect.replaceChildren(new Option("---------", ""));
        if (!organizationSelect.value) {
            return;
        }

        const endpoint = assignmentSelect.dataset.endpoint;
        if (!endpoint) {
            return;
        }
        const url = new URL(endpoint, window.location.origin);
        url.searchParams.set("organization_unit", organizationSelect.value);
        const summarySelect = relatedElement(organizationSelect, "summary");
        if (summarySelect && summarySelect.value) {
            url.searchParams.set("summary", summarySelect.value);
        }

        const response = await fetch(url, {
            credentials: "same-origin",
            headers: {"X-Requested-With": "XMLHttpRequest"}
        });
        if (!response.ok) {
            return;
        }
        const payload = await response.json();
        payload.results.forEach(function (result) {
            assignmentSelect.add(
                new Option(result.text, result.id, false, String(result.id) === selectedAssignment)
            );
        });
    }

    document.addEventListener("change", function (event) {
        if (event.target.name && event.target.name.endsWith("pic_organization_unit")) {
            const ownerCheckbox = relatedElement(
                event.target,
                "use_owner_organization"
            );
            if (ownerCheckbox && !event.target.dataset.ownerSelection) {
                ownerCheckbox.checked = false;
            }
            refreshAssignments(event.target);
        }

        if (event.target.name && event.target.name.endsWith("use_owner_organization")) {
            const organizationSelect = relatedElement(
                event.target,
                "pic_organization_unit"
            );
            if (!organizationSelect || !event.target.checked) {
                return;
            }
            const ownerId = organizationSelect.dataset.ownerOrganizationId;
            if (ownerId) {
                organizationSelect.dataset.ownerSelection = "true";
                organizationSelect.value = ownerId;
                organizationSelect.dispatchEvent(new Event("change", {bubbles: true}));
                delete organizationSelect.dataset.ownerSelection;
            }
        }
    });
})();
