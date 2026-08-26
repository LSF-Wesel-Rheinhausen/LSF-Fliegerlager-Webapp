(() => {
  "use strict";

  document.documentElement.classList.add("admin-mobile-enhanced");
  const toggle = document.querySelector(".admin-mobile-menu-toggle");
  const drawer = document.getElementById("admin-nav-drawer");
  const closeButton = drawer?.querySelector(".admin-nav-drawer__close");
  if (!toggle || !drawer) return;

  const desktop = window.matchMedia("(min-width: 901px)");
  const focusableSelector = "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])";

  const focusableElements = () => [...drawer.querySelectorAll(focusableSelector)].filter((element) => {
    const style = window.getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden" && element.getClientRects().length > 0;
  });

  document.querySelectorAll(".admin-filter-drawer").forEach((filterDrawer) => {
    const summary = filterDrawer.querySelector("summary");
    if (!desktop.matches && filterDrawer.dataset.hasActiveFilters !== "true") filterDrawer.open = false;
    const syncFilterState = () => summary?.setAttribute("aria-expanded", String(filterDrawer.open));
    filterDrawer.addEventListener("toggle", syncFilterState);
    syncFilterState();
  });

  const setOpen = (open) => {
    const isDesktop = desktop.matches;
    const visible = isDesktop || open;
    drawer.classList.toggle("is-open", visible);
    drawer.setAttribute("aria-hidden", String(!visible));
    if (isDesktop || !open) {
      drawer.setAttribute("role", "navigation");
      drawer.setAttribute("aria-label", "Admin-Menü");
      drawer.removeAttribute("aria-modal");
      drawer.removeAttribute("aria-labelledby");
    } else {
      drawer.setAttribute("role", "dialog");
      drawer.setAttribute("aria-modal", "true");
      drawer.setAttribute("aria-labelledby", "admin-nav-title");
      drawer.removeAttribute("aria-label");
    }
    toggle.setAttribute("aria-expanded", String(open));
    if (!isDesktop) document.body.classList.toggle("admin-nav-open", open);
  };

  const open = () => {
    setOpen(true);
    drawer.querySelector("a, button")?.focus();
  };

  const close = () => {
    setOpen(false);
    if (!desktop.matches) toggle.focus();
  };

  const trapFocus = (event) => {
    if (event.key !== "Tab" || desktop.matches || toggle.getAttribute("aria-expanded") !== "true") return;
    const elements = focusableElements();
    if (!elements.length) return;
    const first = elements[0];
    const last = elements[elements.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  toggle.addEventListener("click", () => (toggle.getAttribute("aria-expanded") === "true" ? close() : open()));
  closeButton?.addEventListener("click", close);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") close();
    trapFocus(event);
  });
  document.addEventListener("focusin", (event) => {
    if (!desktop.matches && toggle.getAttribute("aria-expanded") === "true" && !drawer.contains(event.target)) {
      focusableElements()[0]?.focus();
    }
  });
  desktop.addEventListener("change", () => setOpen(false));
  setOpen(false);
})();
