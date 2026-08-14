const { expect, test } = require("./fixtures");
const { configureCampKioskAccess, openKiosk } = require("./kioskAccess");
const { isBenignPageRequestFailure, requestFailureDetails } = require("./requestFailureFilter");

test.use({ serviceWorkers: "block" });

function addDays(date, days) {
  const result = new Date(date);
  result.setDate(result.getDate() + days);
  return result;
}

function dateInputValue(date) {
  return date.toISOString().slice(0, 10);
}

async function loginAsAdmin(page) {
  await page.goto("/login/");
  if (page.url().includes("/login")) {
    await page.locator("#id_username").fill("admin");
    await page.locator("#id_password").fill("strong-test-pass-123");
    await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  }
}

async function setupFirstAdmin(page) {
  await page.goto("/setup/");
  if (page.url().includes("/login/")) {
    await loginAsAdmin(page);
    return;
  }
  await expect(page).toHaveURL(/\/setup\/?$/);
  await page.locator("#id_username").fill("admin");
  await page.locator("#id_email").fill("admin@example.test");
  await page.locator("#id_password1").fill("strong-test-pass-123");
  await page.locator("#id_password2").fill("strong-test-pass-123");
  await page.getByRole("button", { name: "Admin anlegen" }).click();
}

async function createMealScenario(page) {
  const startDate = new Date();
  const endDate = addDays(startDate, 2);
  const campName = `Detail-Lager ${Date.now()}`;
  await page.getByRole("link", { name: "Lager anlegen" }).click();
  await page.getByLabel("Name").fill(campName);
  await page.getByLabel("Jahr").fill(String(startDate.getFullYear()));
  await page.getByLabel("Beginn").fill(dateInputValue(startDate));
  await page.getByLabel("Ende").fill(dateInputValue(endDate));
  await page.getByRole("button", { name: "Speichern" }).click();
  await configureCampKioskAccess(page);
  await page.getByRole("link", { name: "Preise verwalten" }).first().click();
  await page.locator('input[name="meal-breakfast_adult_price"]').fill("5.00");
  await page.locator('input[name="meal-dinner_adult_price"]').fill("7.00");
  await page.getByRole("button", { name: "Standardpreise speichern" }).click();
  await page.getByRole("link", { name: "Fliegerlager-Abrechnung" }).click();
  await page.getByRole("link", { name: campName, exact: true }).click();
  return { campName, bookingDate: addDays(startDate, 1) };
}

test("Admin meal overview keeps dinner and breakfast details separate and keyboard accessible", async ({ page }) => {
  await setupFirstAdmin(page);

  await page.getByRole("link", { name: "Lager anlegen" }).click();
  await page.getByLabel("Name").fill("Detail-Lager");
  await page.getByLabel("Jahr").fill("2026");
  await page.getByLabel("Beginn").fill("2026-07-01");
  await page.getByLabel("Ende").fill("2026-07-02");
  await page.getByRole("button", { name: "Speichern" }).click();
  await page.getByRole("link", { name: "Essensübersicht" }).first().click();

  const dinner = page.locator('[data-meal-section="dinner"]');
  const breakfast = page.locator('[data-meal-section="breakfast"]');
  await expect(dinner).toBeVisible();
  await expect(breakfast).toBeVisible();
  await expect(dinner.getByRole("heading", { name: "Caterer-Abendessen" })).toBeVisible();
  await expect(breakfast.getByRole("heading", { name: "Frühstücksvorbestellungen" })).toBeVisible();
  await expect(dinner.locator("[data-meal-section='breakfast']")).toHaveCount(0);
  await expect(breakfast.locator("[data-meal-section='dinner']")).toHaveCount(0);
  await expect(page.locator('[data-meal-section="combined"], [data-meal-calendar]')).toHaveCount(0);

  const breakfastDay = breakfast.getByRole("button", { name: /01\.07\.2026/ }).first();
  await breakfastDay.focus();
  await expect(breakfastDay).toBeFocused();
  await page.keyboard.press("Enter");
  const dialog = page.locator("#breakfast-detail-20260701");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Schließen" })).toBeFocused();
  await expect(dialog.getByText("Keine Buchungen für diesen Tag.")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(breakfastDay).toBeFocused();

  const dinnerDay = dinner.getByRole("button", { name: /01\.07\.2026/ }).first();
  await dinnerDay.click();
  const dinnerDialog = page.locator("#dinner-detail-20260701");
  await expect(dinnerDialog).toBeVisible();
  await expect(dinnerDialog.getByText("Keine Buchungen für diesen Tag.")).toBeVisible();
  await dinnerDialog.getByRole("button", { name: "Schließen" }).click();
  await expect(dinnerDialog).toBeHidden();
  await expect(dinnerDay).toBeFocused();
});

test("Admin meal overview shows populated details and contains long names on mobile", async ({ page, browser, baseURL }) => {
  const browserErrors = [];
  const failedRequests = [];
  const trackPageIssues = (trackedPage) => {
    trackedPage.on("console", (message) => {
      if (message.type() === "error") browserErrors.push(message.text());
    });
    trackedPage.on("pageerror", (error) => browserErrors.push(error.message));
    trackedPage.on("requestfailed", (request) => {
      const details = requestFailureDetails(request);
      const isMissingE2ePwaIcon = details.url.endsWith("/static/billing/icons/kiosk-icon-192.png");
      if (!isBenignPageRequestFailure(details) && !isMissingE2ePwaIcon) {
        failedRequests.push(`${details.method} ${details.url}`);
      }
    });
  };
  trackPageIssues(page);

  await setupFirstAdmin(page);
  const { campName } = await createMealScenario(page);
  const longName = "Alexandra MitEinemSehrLangenNachnamenFuerOverflow";

  const kioskContext = await browser.newContext({
    baseURL,
    serviceWorkers: "block",
  });
  const kioskPage = await kioskContext.newPage();
  trackPageIssues(kioskPage);

  try {
    await page.getByRole("link", { name: "Teilnehmer anlegen" }).click();
    await page.getByLabel("Vorname").fill("Alexandra");
    await page.getByLabel("Nachname").fill(longName);
    await page.getByRole("button", { name: "Speichern" }).click();
    await page.getByRole("link", { name: "PIN setzen", exact: true }).click();
    await page.getByLabel("Neue PIN").fill("1234");
    await page.getByRole("button", { name: "Speichern", exact: true }).click();
    await page.getByRole("link", { name: "Fliegerlager-Abrechnung" }).click();
    await page.getByRole("link", { name: campName, exact: true }).click();

    await openKiosk(kioskPage);
    await kioskPage.getByLabel("Teilnehmer").selectOption({ label: `Alexandra ${longName}` });
    await kioskPage.getByLabel("PIN:", { exact: true }).fill("1234");
    await kioskPage.getByRole("button", { name: "Anmelden", exact: true }).click();
    await kioskPage.locator('[data-kiosk-card="food"] [data-food-button][data-meal-type="breakfast"]').click();
    await kioskPage.locator("dialog#food-dialog").getByRole("button", { name: "Für später vorbestellen" }).click();
    await kioskPage.locator("dialog#breakfast-meal-dialog input[data-breakfast-meal-date-checkbox]:not([disabled])").first().check();
    await kioskPage.locator("dialog#breakfast-meal-dialog").getByRole("button", { name: "Frühstücksvorbestellung speichern" }).click();
    await expect(kioskPage.getByText(/Essensanmeldung wurde für 1 Tag und 1 Person gespeichert\./)).toBeVisible();
    await kioskPage.goto("/kiosk/");
    await kioskPage.locator('[data-kiosk-card="food"] [data-dialog-target="meal-calendar-dialog"]').click();
    await kioskPage.locator("dialog#meal-calendar-dialog").getByRole("button", { name: "Essen buchen" }).click();
    await kioskPage.locator("dialog#meal-dialog input[data-meal-date-checkbox]:not([disabled])").first().check();
    await kioskPage.locator("dialog#meal-dialog").getByRole("button", { name: "Weiter" }).click();
    await kioskPage.locator("dialog#meal-dialog").getByRole("button", { name: "Essensanmeldung speichern" }).click();
    const mealDialog = kioskPage.locator("#meal-dialog");
    if (await mealDialog.evaluate((dialog) => dialog.open)) {
      await mealDialog.locator("#meal-dialog-close").click();
      await expect(mealDialog).toBeHidden();
    }
    const mealCalendarDialog = kioskPage.locator("#meal-calendar-dialog");
    await expect(mealCalendarDialog).toBeVisible();
    await mealCalendarDialog.getByRole("button", { name: "Schließen" }).click();
    await expect(mealCalendarDialog).toBeHidden();
    await kioskPage.getByRole("link", { name: "Abmelden" }).first().click();
    await expect(kioskPage).toHaveURL(/\/kiosk\/login\/?$/);

    await page.getByRole("link", { name: "Fliegerlager-Abrechnung" }).click();
    await page.getByRole("link", { name: campName, exact: true }).click();
    await page.getByRole("link", { name: "Essensübersicht" }).first().click();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ colorScheme: "dark" });

    const breakfast = page.locator('[data-meal-section="breakfast"]');
    const breakfastDay = breakfast.locator("tbody tr:has(td strong:text-is('1'))").getByRole("button");
    await breakfastDay.click();
    const dialog = page.locator("dialog:visible").last();
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText(`Alexandra ${longName}`);
    await expect(dialog).toContainText("Bestellungen: 1");
    await expect(dialog.locator(".kiosk-table__wrapper")).toHaveCSS("overflow-x", "auto");
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
    await dialog.getByRole("button", { name: "Schließen" }).click();
    await expect(breakfastDay).toBeFocused();

    const dinner = page.locator('[data-meal-section="dinner"]');
    const dinnerDay = dinner.locator("tbody tr:has(td strong:text-is('1'))").getByRole("button");
    await dinnerDay.click();
    const dinnerDialog = page.locator("dialog:visible").last();
    await expect(dinnerDialog).toContainText(`Alexandra ${longName}`);
    await expect(dinnerDialog).toContainText("Bestellungen: 1");
    await dinnerDialog.getByRole("button", { name: "Schließen" }).click();
    await expect(dinnerDay).toBeFocused();
    expect(browserErrors).toEqual([]);
    expect(failedRequests).toEqual([]);
  } finally {
    await kioskContext.close();
  }
});
