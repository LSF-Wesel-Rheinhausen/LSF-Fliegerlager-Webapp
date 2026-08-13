const { test, expect } = require("./fixtures");

const MOBILE_VIEWPORTS = [
  { name: "portrait", width: 375, height: 667, safeAreaBottom: 34, safeAreaLeft: 0, safeAreaRight: 0 },
  { name: "landscape", width: 667, height: 375, safeAreaBottom: 21, safeAreaLeft: 24, safeAreaRight: 18 },
  { name: "short portrait", width: 320, height: 568, safeAreaBottom: 34, safeAreaLeft: 0, safeAreaRight: 0 },
];

async function loadOverlayHarness(page, viewport, colorScheme = "light") {
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  await page.emulateMedia({ colorScheme });
  await page.addInitScript(() => {
    const nativeMatchMedia = window.matchMedia.bind(window);
    window.matchMedia = (query) => {
      if (query === "(display-mode: standalone)") return { matches: true, media: query, addEventListener() {}, removeEventListener() {} };
      return nativeMatchMedia(query);
    };
    Object.defineProperty(navigator, "standalone", { configurable: true, value: true });
  });
  await page.goto("/kiosk/login/");
  await page.evaluate(() => {
    document.documentElement.style.setProperty("--test-safe-area-bottom", "34px");
    document.documentElement.style.setProperty("--test-safe-area-left", "0px");
    document.documentElement.style.setProperty("--test-safe-area-right", "0px");
    document.documentElement.style.setProperty("--mobile-safe-area-bottom", "var(--test-safe-area-bottom)");
    document.documentElement.style.setProperty("--mobile-safe-area-left", "var(--test-safe-area-left)");
    document.documentElement.style.setProperty("--mobile-safe-area-right", "var(--test-safe-area-right)");
    document.body.style.minHeight = "2400px";
    window.scrollTo(0, 420);
    const nav = document.createElement("nav");
    nav.className = "kiosk-mobile-bottom-nav";
    nav.setAttribute("aria-label", "Mobile Navigation");
    nav.innerHTML = ["Kiosk", "Dienste", "Essen", "Mehr", "Abmelden"]
      .map((label) => `<a class="kiosk-mobile-bottom-nav__item" href="#${label.toLowerCase()}"><span aria-hidden="true">●</span><span>${label}</span></a>`)
      .join("");
    document.body.append(nav);
  });
}

async function addDialogs(page) {
  return page.evaluate(() => {
    const dialogTypes = ["kiosk-menu", "food", "compact", "admin"];
    const dialogs = dialogTypes.map((type) => {
      const dialog = document.createElement("dialog");
      dialog.id = `${type}-dialog`;
      dialog.className = type === "compact" ? "kiosk-dialog kiosk-dialog--compact" : "kiosk-dialog";
      dialog.dataset.surface = type === "admin" ? "admin" : "kiosk";
      dialog.innerHTML = `<h2>${type}</h2><div style="height: 1600px">long content</div><button type="button" data-close-dialog>Schließen</button>`;
      document.body.append(dialog);
      return dialog;
    });
    document.addEventListener("click", (event) => {
      const button = event.target.closest("[data-close-dialog]");
      if (button) button.closest("dialog")?.close();
      if (event.target instanceof HTMLDialogElement && event.target.open) {
        const rect = event.target.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) {
          event.target.close();
        }
      }
    });
    return dialogs.map((dialog) => dialog.id);
  });
}

async function openDialog(page, id) {
  await page.evaluate((dialogId) => document.getElementById(dialogId).showModal(), id);
  await expect(page.locator(`#${id}`)).toBeVisible();
}

test.describe("Mobile native dialog scroll locking", () => {
  for (const viewport of MOBILE_VIEWPORTS) {
    test(`locks background and preserves dialog scroll in ${viewport.name}`, async ({ page }) => {
      await loadOverlayHarness(page, viewport);
      await addDialogs(page);

      for (const dialogId of ["kiosk-menu-dialog", "food-dialog", "compact-dialog", "admin-dialog"]) {
        await openDialog(page, dialogId);
        const state = await page.evaluate(() => {
          const dialog = document.querySelector("dialog[open]");
          const before = window.scrollY;
          dialog.scrollTop = 600;
          window.scrollBy(0, 140);
          return {
            before,
            afterBackgroundScrollAttempt: window.scrollY,
            dialogScrollTop: dialog.scrollTop,
            dialogCanScroll: dialog.scrollHeight > dialog.clientHeight,
          };
        });
        expect(state.afterBackgroundScrollAttempt).toBe(state.before);
        expect(state.dialogCanScroll).toBe(true);
        expect(state.dialogScrollTop).toBeGreaterThan(0);
        await page.keyboard.press("Escape");
        await expect(page.locator(`#${dialogId}`)).toBeHidden();
        await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(420);
      }
    });
  }

  test("keeps the lock across dialog replacement and unlocks only after the last close", async ({ page }) => {
    await loadOverlayHarness(page, MOBILE_VIEWPORTS[0]);
    await addDialogs(page);
    await openDialog(page, "kiosk-menu-dialog");
    await page.evaluate(() => {
      window.scrollLockDroppedDuringReplacement = false;
      const observer = new MutationObserver(() => {
        if (!document.documentElement.classList.contains("dialog-scroll-lock")) {
          window.scrollLockDroppedDuringReplacement = true;
        }
      });
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
      window.kioskDialogs.open(document.getElementById("food-dialog"));
    });
    await expect(page.locator("#food-dialog")).toBeVisible();
    expect(await page.evaluate(() => ({
      bodyPosition: getComputedStyle(document.body).position,
      lockedScrollY: Number.parseFloat(document.body.style.top) * -1,
      lockDropped: window.scrollLockDroppedDuringReplacement,
    }))).toEqual({ bodyPosition: "fixed", lockedScrollY: 420, lockDropped: false });
    await page.evaluate(() => {
      window.scrollLockDroppedDuringReplacement = false;
    });
    await page.locator("#food-dialog").getByRole("button", { name: "Schließen" }).click();
    await expect(page.locator("#kiosk-menu-dialog")).toBeVisible();
    await expect.poll(() => page.evaluate(() => getComputedStyle(document.body).position)).toBe("fixed");
    expect(await page.evaluate(() => window.scrollLockDroppedDuringReplacement)).toBe(false);
    await page.evaluate(() => document.getElementById("kiosk-menu-dialog").close());
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(420);
  });

  for (const closeMethod of ["escape", "backdrop", "button", "programmatic"]) {
    test(`unlocks reliably through ${closeMethod}`, async ({ page }) => {
      await loadOverlayHarness(page, MOBILE_VIEWPORTS[0]);
      await addDialogs(page);
      await openDialog(page, "compact-dialog");
      if (closeMethod === "escape") await page.keyboard.press("Escape");
      if (closeMethod === "backdrop") await page.mouse.click(2, 2);
      if (closeMethod === "button") await page.locator("#compact-dialog").getByRole("button", { name: "Schließen" }).click();
      if (closeMethod === "programmatic") await page.evaluate(() => document.getElementById("compact-dialog").close());
      await expect(page.locator("#compact-dialog")).toBeHidden();
      await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(420);
    });
  }
});

test.describe("Mobile bottom navigation touch safety", () => {
  for (const viewport of MOBILE_VIEWPORTS) {
    for (const colorScheme of ["light", "dark"]) {
      test(`keeps ${colorScheme} navigation targets above the safe area in ${viewport.name}`, async ({ page }) => {
        await loadOverlayHarness(page, viewport, colorScheme);
        await page.evaluate(({ bottom, left, right }) => {
          document.documentElement.style.setProperty("--test-safe-area-bottom", `${bottom}px`);
          document.documentElement.style.setProperty("--test-safe-area-left", `${left}px`);
          document.documentElement.style.setProperty("--test-safe-area-right", `${right}px`);
          document.documentElement.style.setProperty("--mobile-safe-area-bottom", "var(--test-safe-area-bottom)");
          document.documentElement.style.setProperty("--mobile-safe-area-left", "var(--test-safe-area-left)");
          document.documentElement.style.setProperty("--mobile-safe-area-right", "var(--test-safe-area-right)");
        }, { bottom: viewport.safeAreaBottom, left: viewport.safeAreaLeft, right: viewport.safeAreaRight });
        await addDialogs(page);
        const measurements = await page.locator(".kiosk-mobile-bottom-nav__item").evaluateAll((items) => {
          const viewportHeight = window.innerHeight;
          const nav = document.querySelector(".kiosk-mobile-bottom-nav");
          const navStyle = getComputedStyle(nav);
          const rootStyle = getComputedStyle(document.documentElement);
          const safeAreaBottom = Number.parseFloat(rootStyle.getPropertyValue("--test-safe-area-bottom")) || 0;
          const safeAreaLeft = Number.parseFloat(rootStyle.getPropertyValue("--test-safe-area-left")) || 0;
          const safeAreaRight = Number.parseFloat(rootStyle.getPropertyValue("--test-safe-area-right")) || 0;
          return {
            nav: nav.getBoundingClientRect().toJSON(),
            navPosition: navStyle.position,
            navBottom: navStyle.bottom,
            navBottomGap: viewportHeight - nav.getBoundingClientRect().bottom,
            navPaddingBottom: Number.parseFloat(navStyle.paddingBottom),
            navPaddingLeft: Number.parseFloat(navStyle.paddingLeft),
            navPaddingRight: Number.parseFloat(navStyle.paddingRight),
            safeAreaBottom,
            safeAreaLeft,
            safeAreaRight,
            pagePaddingBottom: Number.parseFloat(getComputedStyle(document.querySelector("main")).paddingBottom),
            dialogMarginBottom: Number.parseFloat(getComputedStyle(document.querySelector("#kiosk-menu-dialog")).marginBottom),
            viewportHeight,
            viewportWidth: window.innerWidth,
            items: items.map((item) => {
              const rect = item.getBoundingClientRect();
              return { width: rect.width, height: rect.height, top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right };
            }),
            horizontalOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
            standalone: window.matchMedia("(display-mode: standalone)").matches && navigator.standalone === true,
            viewport: document.querySelector('meta[name="viewport"]').content,
          };
        });
        for (const item of measurements.items) {
          expect(item.width).toBeGreaterThanOrEqual(44);
          expect(item.height).toBeGreaterThanOrEqual(44);
          expect(item.bottom).toBeLessThanOrEqual(measurements.viewportHeight - measurements.safeAreaBottom);
        }
        expect(measurements.navBottomGap).toBe(0);
        expect(measurements.navPosition).toBe("fixed");
        expect(measurements.navBottom).toBe("0px");
        expect(measurements.navPaddingBottom).toBe(measurements.safeAreaBottom + 6);
        expect(measurements.navPaddingLeft).toBe(measurements.safeAreaLeft + 4);
        expect(measurements.navPaddingRight).toBe(measurements.safeAreaRight + 4);
        expect(measurements.items[0].left).toBeGreaterThanOrEqual(measurements.safeAreaLeft);
        expect(measurements.items.at(-1).right).toBeLessThanOrEqual(measurements.viewportWidth - measurements.safeAreaRight);
        expect(measurements.pagePaddingBottom).toBe(measurements.nav.height);
        expect(measurements.dialogMarginBottom).toBe(measurements.nav.height);
        expect(measurements.horizontalOverflow).toBeLessThanOrEqual(0);
        expect(measurements.standalone).toBe(true);
        expect(measurements.viewport).toContain("viewport-fit=cover");
      });
    }
  }
});
