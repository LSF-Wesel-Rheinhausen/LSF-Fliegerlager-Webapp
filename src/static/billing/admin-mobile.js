(() => {
  "use strict";

  const toggle = document.querySelector(".admin-mobile-menu-toggle");
  const drawer = document.getElementById("admin-nav-drawer");
  const closeButton = drawer?.querySelector(".admin-nav-drawer__close");
  if (!toggle || !drawer) return;

  const desktop = window.matchMedia("(min-width: 901px)");

  document.querySelectorAll(".admin-filter-drawer").forEach((filterDrawer) => {
    const summary = filterDrawer.querySelector("summary");
    const syncFilterState = () => summary?.setAttribute("aria-expanded", String(filterDrawer.open));
    filterDrawer.addEventListener("toggle", syncFilterState);
    syncFilterState();
  });

  const setOpen = (open) => {
    const isDesktop = desktop.matches;
    const visible = isDesktop || open;
    drawer.classList.toggle("is-open", visible);
    drawer.setAttribute("aria-hidden", String(!visible));
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

  toggle.addEventListener("click", () => (toggle.getAttribute("aria-expanded") === "true" ? close() : open()));
  closeButton?.addEventListener("click", close);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") close();
  });
  desktop.addEventListener("change", () => setOpen(false));
  setOpen(false);
})();
