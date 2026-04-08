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

    function toggleSidebar() {
        const sidebar = document.getElementById("sidebar");

        if (!sidebar) {
            return;
        }

        if (isMobile()) {
            setMobileSidebar(!sidebar.classList.contains("is-open"));
            return;
        }

        sidebar.classList.toggle("collapsed");
        document.body.classList.toggle("sidebar-collapsed", sidebar.classList.contains("collapsed"));
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
            return;
        }

        if (isMobile()) {
            sidebar.classList.remove("collapsed");
            document.body.classList.remove("sidebar-collapsed");
        } else {
            setMobileSidebar(false);
        }
    }

    function handleStorage(event) {
        if (event.key === STORAGE_KEY) {
            applyTheme(readSavedTheme());
        }
    }

    function init() {
        applyTheme(document.documentElement.dataset.theme || readSavedTheme());
        bindThemeControls();
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
