const { expect, test } = require("./fixtures");

async function signInApplicationAdmin(page) {
  await page.goto("/setup/");
  if (await page.getByRole("heading", { name: "Ersteinrichtung" }).isVisible().catch(() => false)) {
    await page.locator("#id_username").fill("admin");
    await page.locator("#id_email").fill("admin@example.test");
    await page.locator("#id_password1").fill("strong-test-pass-123");
    await page.locator("#id_password2").fill("strong-test-pass-123");
    await page.getByRole("button", { name: "Admin anlegen" }).click();
  }
  await page.goto("/login/");
  if (await page.getByRole("heading", { name: "Anmelden" }).isVisible().catch(() => false)) {
    await page.getByLabel("Benutzername oder E-Mail:").fill("admin@example.test");
    await page.getByLabel("Passwort:").fill("strong-test-pass-123");
    await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  }
  await expect(page).toHaveURL(/\/camps\/?$/);
}

async function setupAdminWithCamp(page) {
  await signInApplicationAdmin(page);
  await page.goto("/camps/");
  await page.getByRole("link", { name: "Lager anlegen" }).click();
  const campName = `Übersicht ${Date.now()}`;
  await page.getByLabel("Name").fill(campName);
  await page.getByLabel("Jahr").fill(String(new Date().getFullYear()));
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByRole("heading", { name: "Übersicht", exact: true })).toBeVisible();
  return { campUrl: page.url() };
}

async function createParticipant(page, campUrl, firstName, lastName) {
  await page.goto(campUrl);
  await page.getByRole("link", { name: "Teilnehmer anlegen" }).click();
  await page.getByLabel("Vorname").fill(firstName);
  await page.getByLabel("Nachname").fill(lastName);
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByRole("heading", { name: `${firstName} ${lastName}` })).toBeVisible();
}

test("camp task menu is keyboard accessible on mobile and becomes a desktop sidebar", async ({ page }) => {
  await signInApplicationAdmin(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/camps/");
  await page.getByRole("link", { name: /E2E-Lagerzugang/ }).click();
  const heading = await page.getByRole("heading", { name: "Übersicht", exact: true }).boundingBox();
  const primaryAction = await page.getByRole("link", { name: "Teilnehmer anlegen", exact: true }).boundingBox();
  expect(primaryAction.y - heading.y - heading.height, "Die Hauptaktion folgt mobil unmittelbar auf den Titel").toBeLessThanOrEqual(100);
  const globalMenu = page.locator(".admin-global-menu");
  const globalSummary = globalMenu.locator("summary");
  await expect(globalSummary).toBeVisible();
  await expect(globalMenu).not.toHaveAttribute("open", "");
  await globalSummary.focus();
  await page.keyboard.press("Enter");
  await expect(globalMenu).toHaveAttribute("open", "");
  await expect(globalMenu.getByRole("link", { name: "Hilfe" })).toBeVisible();
  await expect(globalMenu.getByRole("link", { name: "Nutzer" })).toBeVisible();
  await expect(globalMenu.getByRole("button", { name: "Abmelden" })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(globalMenu).not.toHaveAttribute("open", "");
  await expect(page.locator("[data-theme-toggle]")).toBeVisible();

  const taskNav = page.locator(".camp-task-nav");
  const summary = taskNav.locator("summary");
  await expect(taskNav).toBeVisible();
  await expect(taskNav).not.toHaveAttribute("open", "");
  await summary.focus();
  await page.keyboard.press("Enter");
  await expect(taskNav).toHaveAttribute("open", "");
  await expect(taskNav.getByRole("link", { name: "Teilnehmer importieren" })).toBeVisible();

  await page.evaluate(() => localStorage.setItem("fliegerlager-theme", "dark"));
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator("body")).toHaveCSS("background-color", "rgb(17, 25, 35)");

  await page.setViewportSize({ width: 1280, height: 800 });
  await expect(taskNav).toHaveAttribute("open", "");
  await expect(globalMenu).toHaveAttribute("open", "");
  await expect(page.locator("html")).toHaveJSProperty("scrollWidth", 1280);

  await page.setViewportSize({ width: 1100, height: 800 });
  await expect(taskNav).not.toHaveAttribute("open", "");
  await expect(globalMenu).toHaveAttribute("open", "");
  await page.setViewportSize({ width: 1101, height: 800 });
  await expect(taskNav).toHaveAttribute("open", "");
  await expect(globalMenu).toHaveAttribute("open", "");
  await page.setViewportSize({ width: 900, height: 800 });
  await expect(taskNav).not.toHaveAttribute("open", "");
  await expect(globalMenu).not.toHaveAttribute("open", "");
  await page.setViewportSize({ width: 901, height: 800 });
  await expect(globalMenu).toHaveAttribute("open", "");
});

test("camp overview groups finance figures and keeps wide tables inside the page", async ({ page }) => {
  const { campUrl } = await setupAdminWithCamp(page);
  await createParticipant(page, campUrl, "Alexandria-Maria-Longname", "Rheinhausen-Wesel-Fliegerlager-Teilnehmende");
  const widths = [320, 390, 768, 1024, 1280, 1440, 1920];

  for (const width of widths) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(campUrl);

    await expect(page.locator(".overview-summary__group")).toHaveCount(2);
    await expect(page.locator(".metric")).toHaveCount(6);
    await expect(page.getByRole("navigation", { name: "Lagerberichte und Exporte" }).getByRole("link").first()).toBeVisible();
    await expect(page.locator(".admin-table-scroll").first()).toHaveAttribute("role", "region");
    await expect(page.locator(".admin-table-scroll").first()).toHaveAttribute("tabindex", "0");

    const dimensions = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      document: document.documentElement.scrollWidth,
      overview: document.querySelector(".admin-shell").getBoundingClientRect().width,
      table: document.querySelector(".admin-table-scroll").getBoundingClientRect().width,
      tableScroll: document.querySelector(".admin-table-scroll").scrollWidth,
    }));
    expect(dimensions.document, `${width}px viewport has no page-level horizontal overflow`).toBeLessThanOrEqual(width + 1);
    expect(dimensions.table, `${width}px table viewport stays within the overview`).toBeLessThanOrEqual(dimensions.overview + 1);
    if (width <= 390) {
      expect(dimensions.tableScroll, `${width}px wide table scrolls inside its region`).toBeGreaterThan(dimensions.table);
    }
    if (width === 1440) expect(dimensions.overview, "wide camp overview uses available width").toBeGreaterThan(1300);
    if (width === 320) {
      await expect(page.locator(".participant-settlements tbody tr").first()).toContainText("Rheinhausen-Wesel-Fliegerlager-Teilnehmende");
      await page.locator(".metric strong").first().evaluate((element) => {
        element.firstChild.textContent = "1234567890123456789,99";
      });
      await page.evaluate(() => {
        document.documentElement.style.fontSize = "200%";
      });
      const expandedDocumentWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      expect(expandedDocumentWidth, "320px viewport remains page-scrollable with expanded text and a long amount").toBeLessThanOrEqual(321);
    }
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(campUrl);
  await page.emulateMedia({ reducedMotion: "reduce" });
  const transitionDuration = await page.locator(".panel").first().evaluate((element) => getComputedStyle(element).transitionDuration);
  expect(transitionDuration).toBe("0s");
});

test("technical admin intro precedes model lists and follows the native automatic theme", async ({ page }) => {
  await signInApplicationAdmin(page);
  await page.goto("/admin/");
  await page.emulateMedia({ colorScheme: "dark" });
  await page.evaluate(() => {
    document.documentElement.dataset.theme = "auto";
  });

  const intro = page.locator(".admin-page-intro");
  const firstModule = page.locator("#content-main .module").first();
  await expect(intro).toBeVisible();
  await expect(intro.getByRole("heading", { level: 1 })).toBeVisible();
  const positions = await page.evaluate(() => ({
    introBottom: document.querySelector(".admin-page-intro").getBoundingClientRect().bottom,
    firstModuleTop: document.querySelector("#content-main .module").getBoundingClientRect().top,
    pageBackground: getComputedStyle(document.body).getPropertyValue("--body-bg").trim(),
    moduleLink: getComputedStyle(document.querySelector("#content-main .module caption a")).color,
  }));
  await expect(firstModule).toBeVisible();
  expect(positions.introBottom).toBeLessThanOrEqual(positions.firstModuleTop);
  expect(positions.pageBackground).toBe("#111923");

  await page.emulateMedia({ colorScheme: "light" });
  const lightTheme = await page.evaluate(() => ({
    background: getComputedStyle(document.body).getPropertyValue("--body-bg").trim(),
    moduleLink: getComputedStyle(document.querySelector("#content-main .module caption a")).color,
  }));
  expect(lightTheme.background).toBe("#f7f8fa");
});

test("pending registration review wraps long identity and date fields without hiding actions", async ({ page }) => {
  const { campUrl } = await setupAdminWithCamp(page);
  await page.goto("/admin/billing/participant/add/");
  const campId = new URL(campUrl).pathname.match(/\/camps\/(\d+)\//)[1];
  await page.locator("#id_camp").selectOption(campId);
  await page.locator("#id_first_name").fill("Alexandria-Maria-Winterlagerteilnehmerin");
  await page.locator("#id_last_name").fill("HinterdemSonnenuntergangmitSonderzeichen");
  await page.locator("#id_email").fill("alexandria.maria.long-registration@example.test");
  await page.locator("#id_status").selectOption("pending_approval");
  await page.locator("#id_arrival_date").fill("2026-07-02");
  await page.locator("#id_departure_date").fill("2026-07-09");
  await page.locator('input[name="_save"]').click();

  for (const width of [320, 390, 768, 1128, 1440]) {
    await page.setViewportSize({ width, height: 960 });
    await page.goto(campUrl);
    const row = page.locator("#pending-registrations tbody tr").filter({ hasText: "Alexandria-Maria-Winterlagerteilnehmerin" });
    await expect(row).toBeVisible();
    await expect(row.getByRole("button", { name: "Freigeben" })).toBeVisible();

    const layout = await row.evaluate((element) => {
      const cells = Array.from(element.cells).slice(0, 5);
      return {
        cellsFit: cells.every((cell) => cell.scrollWidth <= cell.clientWidth + 1),
        ordered: cells.every((cell, index) => index === 0 || cells[index - 1].getBoundingClientRect().right <= cell.getBoundingClientRect().left + 1),
        pageWidth: document.documentElement.scrollWidth,
      };
    });
    expect(layout.cellsFit, `${width}px applicant names, email and dates wrap inside cells`).toBe(true);
    expect(layout.ordered, `${width}px review columns stay separated`).toBe(true);
    expect(layout.pageWidth, `${width}px has no page-level horizontal overflow`).toBeLessThanOrEqual(width + 1);

    const viewport = page.locator("#pending-registrations .admin-table-scroll");
    if (width <= 390) expect(await viewport.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
  }
});

test("camp navigation and tables remain available without JavaScript", async ({ browser, page }) => {
  const { campUrl } = await setupAdminWithCamp(page);
  const cookies = await page.context().cookies();
  const noJsContext = await browser.newContext({ javaScriptEnabled: false });
  const noJsPage = await noJsContext.newPage();

  try {
    await noJsContext.addCookies(cookies);
    await noJsPage.setViewportSize({ width: 390, height: 844 });
    await noJsPage.goto(campUrl);
    await expect(noJsPage.getByRole("heading", { name: "Übersicht", exact: true })).toBeVisible();
    await expect(noJsPage.locator(".admin-global-menu")).toHaveAttribute("open", "");
    await expect(noJsPage.locator(".admin-global-menu").getByRole("link", { name: "Hilfe" })).toBeVisible();
    await expect(noJsPage.locator(".camp-task-nav").getByRole("link", { name: "Lager bearbeiten" })).toBeVisible();
    await expect(noJsPage.locator(".admin-table-scroll").first()).toBeVisible();
    expect(await noJsPage.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391);
  } finally {
    await noJsContext.close();
  }
});
