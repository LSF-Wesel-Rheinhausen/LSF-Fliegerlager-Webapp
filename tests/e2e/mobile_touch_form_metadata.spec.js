const { expect, test } = require("./fixtures");
const { openKiosk } = require("./kioskAccess");

test.use({ serviceWorkers: "block" });

test.describe("Mobile Touch Targets & Form Metadata", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("Theme toggle has at least 44x44px touch target size on mobile", async ({ page }) => {
    await openKiosk(page, "/kiosk/login/");
    const themeToggle = page.locator(".theme-toggle");
    await expect(themeToggle).toBeVisible();

    const box = await themeToggle.boundingBox();
    expect(box).not.toBeNull();
    expect(box.width).toBeGreaterThanOrEqual(44);
    expect(box.height).toBeGreaterThanOrEqual(44);
  });

  test("Buttons and inputs have at least 44px height on mobile", async ({ page }) => {
    await openKiosk(page, "/kiosk/login/");
    const loginButton = page.getByRole("button", { name: "Anmelden" });
    await expect(loginButton).toBeVisible();

    const buttonBox = await loginButton.boundingBox();
    expect(buttonBox).not.toBeNull();
    expect(buttonBox.height).toBeGreaterThanOrEqual(44);

    const participantSelect = page.locator("select#id_participant");
    await expect(participantSelect).toBeVisible();

    const selectBox = await participantSelect.boundingBox();
    expect(selectBox).not.toBeNull();
    expect(selectBox.height).toBeGreaterThanOrEqual(44);
  });

  test("Checkbox/radio label touch targets are at least 44px high on mobile", async ({ page }) => {
    await openKiosk(page, "/kiosk/login/");
    const registerButton = page.getByRole("button", { name: /Für Fliegerlager registrieren/ });
    await expect(registerButton).toBeVisible();
    await registerButton.click();

    const dialog = page.locator("#self-registration-dialog");
    await expect(dialog).toBeVisible();

    await page.evaluate(() => {
      const step3 = document.querySelector("[data-wizard-step='3']");
      if (step3) {
        step3.removeAttribute("hidden");
        step3.classList.add("is-active");
      }
    });

    const label = dialog.locator("label.checkbox-label").first();
    await expect(label).toBeVisible();

    const labelBox = await label.boundingBox();
    expect(labelBox).not.toBeNull();
    expect(labelBox.height).toBeGreaterThanOrEqual(44);
  });
});
