const { expect, test } = require("./fixtures");
const {
  isAllowedAdminMobileCancelledFailure,
  isBenignPageRequestFailure,
  requestFailureDetails,
} = require("./requestFailureFilter");

async function signInAdmin(page) {
  await page.goto("/setup/");
  if (await page.getByRole("heading", { name: "Ersteinrichtung" }).isVisible().catch(() => false)) {
    await page.locator("#id_username").fill("admin");
    await page.locator("#id_email").fill("admin@example.test");
    await page.locator("#id_password1").fill("strong-test-pass-123");
    await page.locator("#id_password2").fill("strong-test-pass-123");
    await page.getByRole("button", { name: "Admin anlegen" }).click();
  }
  await page.goto("/admin/login/");
  if (page.url().includes("/admin/login")) {
    await page.locator("#id_username").fill("admin");
    await page.locator("#id_password").fill("strong-test-pass-123");
    await page.getByRole("button", { name: /Log in|Anmelden/ }).click();
  }
  await expect(page).toHaveURL(/\/admin\/?$/);
}

async function createParticipant(page, suffix) {
  await page.goto("/admin/billing/participant/add/");
  await page.locator("#id_camp").selectOption({ index: 1 });
  await page.locator("#id_first_name").fill(`Mobiler Teilnehmer ${suffix}`);
  await page.locator("#id_last_name").fill(`Langer Tabellenwert ${suffix}`);
  await page.locator('input[name="_save"]').click();
  await expect(page).toHaveURL(/\/admin\/billing\/participant\/$/);
}

for (const viewport of [
  { name: "portrait", width: 390, height: 844 },
  { name: "landscape", width: 844, height: 390 },
]) {
  test(`Django Admin mobile navigation and table remain usable in ${viewport.name}`, async ({ page }) => {
    const browserErrors = [];
    const failedRequests = [];
    const httpFailures = [];
    page.on("console", (message) => { if (message.type() === "error") browserErrors.push(message.text()); });
    page.on("pageerror", (error) => browserErrors.push(error.message));
    page.on("response", (response) => {
      if (response.status() >= 400) httpFailures.push(`${response.status()} ${response.url()}`);
    });
    page.on("requestfailed", (request) => {
      const details = requestFailureDetails(request);
      if (!isAllowedAdminMobileCancelledFailure(details) && !isBenignPageRequestFailure(details)) {
        failedRequests.push(details);
      }
    });

    await signInAdmin(page);
    await createParticipant(page, viewport.name);
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.reload();
    await page.waitForLoadState("networkidle");

    const menu = page.locator(".admin-mobile-menu-toggle");
    await expect(menu).toBeVisible();
    await expect(menu).toHaveCSS("min-width", "44px");
    await expect(menu).toHaveCSS("min-height", "44px");
    const menuSize = await menu.boundingBox();
    expect(menuSize.width).toBeGreaterThanOrEqual(44);
    expect(menuSize.height).toBeGreaterThanOrEqual(44);

    await menu.click();
    await expect(page.locator("#admin-nav-drawer")).toBeVisible();
    await expect(menu).toHaveAttribute("aria-expanded", "true");
    await expect(page.locator(".admin-nav-drawer__close")).toBeFocused();
    expect(await page.evaluate(() => getComputedStyle(document.body).overflow)).toBe("hidden");
    await page.keyboard.press("Escape");
    await expect(menu).toBeFocused();
    await expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(await page.evaluate(() => getComputedStyle(document.body).overflow)).not.toBe("hidden");

    const results = page.locator(".admin-results-scroll");
    await expect(results).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
    const filterToggle = page.locator("#admin-filter-toggle");
    if (await filterToggle.count()) {
      const filterSize = await filterToggle.boundingBox();
      expect(filterSize.height).toBeGreaterThanOrEqual(44);
      await filterToggle.click();
      await expect(page.locator("#admin-filter-drawer")).toHaveAttribute("open", "");
      await expect(filterToggle).toHaveAttribute("aria-expanded", "true");
      await filterToggle.click();
      await expect(filterToggle).toHaveAttribute("aria-expanded", "false");
    }
    await expect(results).toHaveCSS("overflow-x", "auto");
    expect(browserErrors).toEqual([]);
    expect(failedRequests).toEqual([]);
    expect(httpFailures).toEqual([]);
  });
}

test("Django Admin keeps the desktop navigation layout outside the mobile breakpoint", async ({ page }) => {
  const browserErrors = [];
  const failedRequests = [];
  const httpFailures = [];
  page.on("console", (message) => { if (message.type() === "error") browserErrors.push(message.text()); });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("response", (response) => {
    if (response.status() >= 400) httpFailures.push(`${response.status()} ${response.url()}`);
  });
  page.on("requestfailed", (request) => {
    const details = requestFailureDetails(request);
    if (!isAllowedAdminMobileCancelledFailure(details) && !isBenignPageRequestFailure(details)) {
      failedRequests.push(details);
    }
  });

  await page.setViewportSize({ width: 1280, height: 800 });
  await signInAdmin(page);
  await page.goto("/admin/billing/participant/");
  await page.waitForLoadState("networkidle");

  await expect(page.locator(".admin-mobile-menu-toggle")).toBeHidden();
  await expect(page.locator("#admin-nav-drawer")).toBeVisible();
  await expect(page.locator("#admin-nav-drawer")).toHaveAttribute("role", "navigation");
  await expect(page.locator("#admin-nav-drawer")).not.toHaveAttribute("aria-modal");
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  expect(browserErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
  expect(httpFailures).toEqual([]);
});

test("mobile admin navigation keeps modal focus inside the drawer", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signInAdmin(page);
  await page.goto("/admin/billing/participant/");
  await page.waitForLoadState("networkidle");

  const toggle = page.locator(".admin-mobile-menu-toggle");
  const drawer = page.locator("#admin-nav-drawer");
  const focusable = drawer.locator("a[href]:visible, button:not([disabled]):visible, input:not([disabled]):visible, select:not([disabled]):visible, textarea:not([disabled]):visible");

  await toggle.click();
  await expect(drawer).toHaveAttribute("role", "dialog");
  await expect(drawer).toHaveAttribute("aria-modal", "true");
  await expect(focusable).not.toHaveCount(0);

  await focusable.first().focus();
  await page.keyboard.press("Shift+Tab");
  await expect(focusable.last()).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(focusable.first()).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(toggle).toBeFocused();
  await expect(drawer).toHaveAttribute("aria-hidden", "true");
});

test.describe("mobile admin navigation without JavaScript", () => {
  test.use({ javaScriptEnabled: false });

  test("keeps the persistent navigation reachable", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await signInAdmin(page);
    await page.goto("/admin/billing/participant/");

    const drawer = page.locator("#admin-nav-drawer");
    const participantLink = drawer.getByRole("link", { name: "Teilnehmer", exact: true });
    await expect(page.locator(".admin-mobile-menu-toggle")).toBeHidden();
    await expect(drawer).toBeVisible();
    await expect(participantLink).toBeVisible();
  });
});
