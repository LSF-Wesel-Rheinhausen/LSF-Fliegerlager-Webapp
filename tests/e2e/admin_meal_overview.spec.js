const { expect, test } = require("./fixtures");

test.use({ serviceWorkers: "block" });

test("Admin meal overview keeps dinner and breakfast details separate and keyboard accessible", async ({ page }) => {
  await page.goto("/setup/");
  await page.getByLabel("Benutzername").fill("admin");
  await page.getByLabel("E-Mail-Adresse").fill("admin@example.test");
  await page.getByLabel("Passwort:", { exact: true }).fill("strong-test-pass-123");
  await page.getByLabel("Passwort wiederholen:", { exact: true }).fill("strong-test-pass-123");
  await page.getByRole("button", { name: "Admin anlegen" }).click();

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
  await dinnerDay.focus();
  await page.keyboard.press("Enter");
  const dinnerDialog = page.locator("#dinner-detail-20260701");
  await expect(dinnerDialog).toBeVisible();
  await expect(dinnerDialog.getByText("Keine Buchungen für diesen Tag.")).toBeVisible();
  await dinnerDialog.getByRole("button", { name: "Schließen" }).click();
  await expect(dinnerDialog).toBeHidden();
  await expect(dinnerDay).toBeFocused();

  await page.setViewportSize({ width: 390, height: 844 });
  const mobileLayout = await page.evaluate(() => ({
    pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    sections: [...document.querySelectorAll("[data-meal-section]")].map((section) => ({
      clientWidth: section.clientWidth,
      scrollWidth: section.scrollWidth,
      tableWrappers: section.querySelectorAll(".kiosk-table__wrapper").length,
      unwrappedTables: [...section.querySelectorAll("table")].filter(
        (table) => !table.closest(".kiosk-table__wrapper"),
      ).length,
    })),
  }));
  expect(mobileLayout.pageOverflow).toBeLessThanOrEqual(1);
  expect(mobileLayout.sections).toEqual([
    expect.objectContaining({ tableWrappers: 1, unwrappedTables: 0 }),
    expect.objectContaining({ tableWrappers: 1, unwrappedTables: 0 }),
  ]);
  for (const section of mobileLayout.sections) {
    expect(section.scrollWidth).toBeLessThanOrEqual(section.clientWidth + 1);
  }
});
