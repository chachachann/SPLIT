(function () {
    const STORAGE_KEY = "split-theme";

    function normalizeTheme(theme) {
        return theme === "light" ? "light" : "dark";
    }

    function readSavedTheme() {
        try {
            return normalizeTheme(localStorage.getItem(STORAGE_KEY));
        } catch (error) {
            return "dark";
        }
    }

    function applyTheme(theme) {
        const resolvedTheme = normalizeTheme(theme);

        document.documentElement.dataset.theme = resolvedTheme;
        document.documentElement.style.colorScheme = resolvedTheme;
        updateThemeControls(resolvedTheme);

        return resolvedTheme;
    }

    function persistTheme(theme) {
        try {
            localStorage.setItem(STORAGE_KEY, normalizeTheme(theme));
        } catch (error) {
            return;
        }

        fetch("/profile/theme", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest"
            },
            credentials: "same-origin",
            body: JSON.stringify({ theme: normalizeTheme(theme) })
        }).catch(function () {
            return;
        });
    }

    function updateThemeControls(theme) {
        const isLight = theme === "light";

        document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
            button.setAttribute("aria-checked", String(isLight));
            button.dataset.state = theme;
        });

        document.querySelectorAll("[data-theme-label]").forEach((label) => {
            label.textContent = isLight ? "Light mode" : "Dark mode";
        });
    }

    function toggleTheme() {
        const nextTheme = document.documentElement.dataset.theme === "light" ? "dark" : "light";
        applyTheme(nextTheme);
        persistTheme(nextTheme);
    }

    function bindThemeControls() {
        document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
            if (button.dataset.bound === "true") {
                return;
            }

            button.dataset.bound = "true";
            button.addEventListener("click", function (event) {
                event.preventDefault();
                toggleTheme();
            });
        });
    }

    function isMobile() {
        return window.matchMedia("(max-width: 768px)").matches;
    }

    function setMobileSidebar(open) {
        const sidebar = document.getElementById("sidebar");
        const backdrop = document.getElementById("backdrop");

        if (!sidebar || !backdrop) {
            return;
        }

        sidebar.classList.toggle("is-open", open);
        backdrop.classList.toggle("show", open);
        document.body.classList.toggle("sidebar-open", open);
    }

    function setSidebarCollapsed(collapsed) {
        const sidebar = document.getElementById("sidebar");

        if (!sidebar || isMobile()) {
            return;
        }

        sidebar.classList.toggle("collapsed", !!collapsed);
        document.body.classList.toggle("sidebar-collapsed", !!collapsed);
    }

    function toggleSidebar() {
        const sidebar = document.getElementById("sidebar");

        if (!sidebar) {
            return;
        }

        if (isMobile()) {
            setMobileSidebar(!sidebar.classList.contains("is-open"));
            return;
        }

        setSidebarCollapsed(!sidebar.classList.contains("collapsed"));
    }

    function openSidebar() {
        if (isMobile()) {
            setMobileSidebar(true);
        }
    }

    function closeSidebar() {
        if (isMobile()) {
            setMobileSidebar(false);
        }
    }

    function handleResize() {
        const sidebar = document.getElementById("sidebar");

        if (!sidebar) {
            syncManagerLayouts();
            return;
        }

        if (isMobile()) {
            sidebar.classList.remove("collapsed");
            document.body.classList.remove("sidebar-collapsed");
        } else {
            setMobileSidebar(false);
        }

        syncManagerLayouts();
    }

    function handleStorage(event) {
        if (event.key === STORAGE_KEY) {
            applyTheme(readSavedTheme());
        }
    }

    function hasVisibleChildren(element) {
        return Array.from(element.children).some((child) => {
            if (child.hidden) {
                return false;
            }

            return window.getComputedStyle(child).display !== "none";
        });
    }

    function syncManagerLayouts() {
        document.querySelectorAll(".manager-content").forEach((container) => {
            const contentColumns = Array.from(
                container.querySelectorAll(":scope > .manager-column, :scope > .manager-main-column")
            ).filter((column) => hasVisibleChildren(column));

            container.classList.toggle("manager-content-single-column", contentColumns.length <= 1);
        });
    }

    function syncNotificationVisualState(card, isRead) {
        if (!card) {
            return;
        }

        card.setAttribute("data-notification-read", isRead ? "true" : "false");
        card.classList.toggle("is-unread", !isRead);

        const actionInput = card.querySelector("[data-action-input]");
        const actionButton = card.querySelector("[data-action-button]");
        if (actionInput) {
            actionInput.value = isRead ? "mark-unread" : "mark-read";
        }
        if (actionButton) {
            actionButton.textContent = isRead ? "Mark Unread" : "Mark Read";
        }
    }

    function syncNotificationMenuState(menu) {
        if (!menu) {
            return;
        }

        const cards = Array.from(menu.querySelectorAll("[data-notification-card]"));
        const unreadCount = cards.filter((card) => card.getAttribute("data-notification-read") !== "true").length;
        const badge = menu.querySelector("[data-notification-badge]");
        const unreadLabel = menu.querySelector("[data-notification-unread-label]");
        const list = menu.querySelector("[data-notification-list]");
        let emptyState = menu.querySelector("[data-notification-empty]");

        if (badge) {
            if (unreadCount > 0) {
                badge.textContent = String(unreadCount);
                badge.hidden = false;
            } else {
                badge.textContent = "";
                badge.hidden = true;
            }
        }
        if (unreadLabel) {
            unreadLabel.textContent = unreadCount + " unread";
        }

        if (!list) {
            return;
        }
        if (!cards.length) {
            if (!emptyState) {
                emptyState = document.createElement("div");
                emptyState.className = "notification-empty";
                emptyState.setAttribute("data-notification-empty", "");
                emptyState.textContent = "No active notifications.";
                list.appendChild(emptyState);
            }
            emptyState.hidden = false;
        } else if (emptyState) {
            emptyState.hidden = true;
        }
    }

    function bindNotificationActions() {
        document.querySelectorAll("[data-notification-action-form]").forEach((form) => {
            if (form.dataset.bound === "true") {
                return;
            }

            form.dataset.bound = "true";
            form.addEventListener("submit", function (event) {
                event.preventDefault();

                const card = form.closest("[data-notification-card]");
                const menu = form.closest("[data-notification-menu]");
                if (!card || card.getAttribute("data-notification-pending") === "true") {
                    return;
                }

                const formData = new FormData(form);
                const action = String(formData.get("action") || "").trim().toLowerCase();
                const previousRead = card.getAttribute("data-notification-read") === "true";
                const actionUrl = form.getAttribute("action") || window.location.href;

                card.setAttribute("data-notification-pending", "true");
                if (action === "mark-read") {
                    syncNotificationVisualState(card, true);
                } else if (action === "mark-unread") {
                    syncNotificationVisualState(card, false);
                }

                fetch(actionUrl, {
                    method: "POST",
                    body: formData,
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                    credentials: "same-origin"
                }).then(function (response) {
                    if (!response.ok) {
                        throw new Error("Notification request failed.");
                    }

                    if (action === "hide") {
                        card.remove();
                    }
                    syncNotificationMenuState(menu);
                }).catch(function () {
                    if (action === "mark-read" || action === "mark-unread") {
                        syncNotificationVisualState(card, previousRead);
                    }
                    syncNotificationMenuState(menu);
                }).finally(function () {
                    card.removeAttribute("data-notification-pending");
                });
            });
        });

        document.querySelectorAll("[data-notification-menu]").forEach((menu) => {
            syncNotificationMenuState(menu);
        });
    }

    function init() {
        applyTheme(document.documentElement.dataset.theme || readSavedTheme());
        bindThemeControls();
        bindNotificationActions();
        syncManagerLayouts();
        handleResize();
        window.addEventListener("resize", handleResize);
        window.addEventListener("storage", handleStorage);
    }

    window.AppShell = {
        applyTheme,
        closeSidebar,
        handleResize,
        isMobile,
        openSidebar,
        syncManagerLayouts,
        setSidebarCollapsed,
        toggleSidebar,
        toggleTheme
    };

    window.closeSidebar = closeSidebar;
    window.openSidebar = openSidebar;
    window.toggleSidebar = toggleSidebar;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
        init();
    }
})();
