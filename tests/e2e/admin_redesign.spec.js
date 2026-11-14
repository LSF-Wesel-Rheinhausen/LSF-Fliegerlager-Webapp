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
});
