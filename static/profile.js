(function () {
    function setActiveTab(root, tabName) {
        root.querySelectorAll("[data-profile-tab]").forEach(function (button) {
            var isActive = button.dataset.profileTab === tabName;
            button.classList.toggle("is-active", isActive);
            button.setAttribute("aria-selected", String(isActive));
        });

        root.querySelectorAll("[data-profile-panel]").forEach(function (panel) {
            panel.classList.toggle("is-active", panel.dataset.profilePanel === tabName);
        });
    }

    function bindTabs(root) {
        var initialTab = root.dataset.activeTab || "basic";
        if (!root.querySelector("[data-profile-tab='" + initialTab + "']")) {
            initialTab = "basic";
        }
        root.querySelectorAll("[data-profile-tab]").forEach(function (button) {
            button.addEventListener("click", function () {
                setActiveTab(root, button.dataset.profileTab);
            });
        });
        setActiveTab(root, initialTab);
    }

    function bindPasswordToggles(root) {
        root.querySelectorAll("[data-password-toggle]").forEach(function (button) {
            button.addEventListener("click", function () {
                var input = root.querySelector(button.dataset.passwordToggle);
                if (!input) {
                    return;
                }
                var showPassword = input.type === "password";
                input.type = showPassword ? "text" : "password";
                button.textContent = showPassword ? "Hide" : "Show";
            });
        });
    }

    function bindThemePreferenceForm(root) {
        var form = root.querySelector("[data-profile-preferences-form]");
        if (!form) {
            return;
        }

        form.addEventListener("submit", function () {
            var select = form.querySelector("[name='theme_preference']");
            if (!select) {
                return;
            }
            try {
                localStorage.setItem("split-theme", select.value === "light" ? "light" : "dark");
            } catch (error) {
                return;
            }
        });
    }

    function bindPrivacyPreview(root) {
        root.querySelectorAll(".profile-checkbox-row").forEach(function (row) {
            var checkbox = row.querySelector("input[type='checkbox']");
            var pill = row.querySelector(".profile-privacy-pill");
            if (!checkbox || !pill) {
                return;
            }

            function syncRow() {
                pill.textContent = checkbox.checked ? "Private" : "Visible";
            }

            checkbox.addEventListener("change", syncRow);
            syncRow();
        });
    }

    function initProfilePage(root) {
        bindTabs(root);
        bindPasswordToggles(root);
        bindThemePreferenceForm(root);
        bindPrivacyPreview(root);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            document.querySelectorAll("[data-profile-page]").forEach(initProfilePage);
        }, { once: true });
    } else {
        document.querySelectorAll("[data-profile-page]").forEach(initProfilePage);
    }
})();
