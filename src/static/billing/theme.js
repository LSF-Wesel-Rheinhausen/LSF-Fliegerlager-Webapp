(() => {
  const storageKey = "fliegerlager-theme";
  const colorSchemeQuery = window.matchMedia("(prefers-color-scheme: dark)");

  const storedTheme = () => {
    try {
      const value = window.localStorage.getItem(storageKey);
      return value === "light" || value === "dark" ? value : null;
    } catch {
      return null;
    }
  };

  const preferredTheme = () => storedTheme() || (colorSchemeQuery.matches ? "dark" : "light");

  const applyTheme = (theme) => {
    document.documentElement.dataset.theme = theme;
    document.querySelectorAll("[data-theme-toggle]").forEach((toggle) => {
      toggle.setAttribute("aria-checked", String(theme === "dark"));
    });
  };

  const storeTheme = (theme) => {
    try {
      window.localStorage.setItem(storageKey, theme);
    } catch {
      // The selected theme still applies for this page when storage is unavailable.
    }
  };

  applyTheme(preferredTheme());

  document.addEventListener("DOMContentLoaded", () => {
    applyTheme(preferredTheme());
    document.querySelectorAll("[data-theme-toggle]").forEach((toggle) => {
      toggle.addEventListener("click", () => {
        const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
        storeTheme(theme);
        applyTheme(theme);
      });
    });

    const campNavigation = document.querySelector(".camp-task-nav");
    if (campNavigation) {
      const desktopNavigation = window.matchMedia("(min-width: 701px)");
      const syncNavigation = () => {
        campNavigation.open = desktopNavigation.matches;
      };
      syncNavigation();
      desktopNavigation.addEventListener("change", syncNavigation);
    }

    const globalNavigation = document.querySelector(".admin-global-menu");
    if (globalNavigation) {
      const desktopGlobalNavigation = window.matchMedia("(min-width: 781px)");
      const syncGlobalNavigation = () => {
        globalNavigation.open = desktopGlobalNavigation.matches;
      };
      syncGlobalNavigation();
      desktopGlobalNavigation.addEventListener("change", syncGlobalNavigation);
    }
  });

  colorSchemeQuery.addEventListener("change", () => {
    if (!storedTheme()) {
      applyTheme(preferredTheme());
    }
  });
})();
