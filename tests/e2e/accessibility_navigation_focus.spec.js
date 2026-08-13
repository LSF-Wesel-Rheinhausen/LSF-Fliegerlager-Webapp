const { expect, test } = require("./fixtures");
const { openKiosk } = require("./kioskAccess");

test.use({ serviceWorkers: "block" });
test.describe.configure({ mode: "serial" });

test("Skip-Link is keyboard accessible and focuses main content", async ({ page }) => {
  await openKiosk(page, "/kiosk/login/");
  const skipLink = page.locator(".skip-link");
  await skipLink.focus();
  await expect(skipLink).toBeFocused();
  await expect(skipLink).toBeVisible();

  await page.keyboard.press("Enter");
  const mainContent = page.locator("#main-content");
  await expect(mainContent).toBeFocused();
});

test("Kiosk self-registration wizard manages step focus and announcements", async ({ page }) => {
  await openKiosk(page, "/kiosk/login/");
  const registerButton = page.getByRole("button", { name: /Für Fliegerlager registrieren/ });
  await expect(registerButton).toBeVisible();
  await registerButton.click();

  const dialog = page.locator("#self-registration-dialog");
  await expect(dialog).toBeVisible();

  await page.locator("#id_enrollment_first_name").fill("Max");
  await page.locator("#id_enrollment_last_name").fill("Mustermann");

  const nextButton = dialog.locator(".button-step-next");
  await nextButton.click();

  const step2Title = dialog.getByRole("heading", { name: "📅 Anreise & Abreise" });
  await expect(step2Title).toBeFocused();

  const announcer = dialog.locator("#wizard-step-announcer");
  await expect(announcer).toHaveText(/Schritt 2 von 4/);

  const prevButton = dialog.locator(".button-step-prev");
  await prevButton.click();

  const step1Title = dialog.getByRole("heading", { name: "👤 Persönliche Angaben" });
  await expect(step1Title).toBeFocused();
  await expect(announcer).toHaveText(/Schritt 1 von 4/);
});

test("Kiosk dialog sets initial focus and restores focus to trigger on close", async ({ page }) => {
  await openKiosk(page, "/kiosk/login/");
  const registerButton = page.getByRole("button", { name: /Für Fliegerlager registrieren/ });
  await expect(registerButton).toBeVisible();
  await registerButton.focus();
  await expect(registerButton).toBeFocused();

  await registerButton.click();
  const dialog = page.locator("#self-registration-dialog");
  await expect(dialog).toBeVisible();

  const isInitialFocusInside = await page.evaluate(() => {
    const dialog = document.getElementById("self-registration-dialog");
    return dialog && dialog.contains(document.activeElement);
  });
  expect(isInitialFocusInside).toBe(true);

  const cancelButton = dialog.getByRole("button", { name: "Abbrechen" });
  await cancelButton.click();
  await expect(dialog).not.toBeVisible();
  await expect(registerButton).toBeFocused();
});
