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
    const label = page.locator("label").first();
    await expect(label).toBeVisible();

    const labelBox = await label.boundingBox();
    expect(labelBox).not.toBeNull();
    expect(labelBox.height).toBeGreaterThanOrEqual(44);
  });

  test("Kiosk form controls keep 44px targets in portrait and landscape", async ({ page }) => {
    for (const viewport of [
      { width: 390, height: 844 },
      { width: 844, height: 390 },
    ]) {
      await page.setViewportSize(viewport);
      await openKiosk(page, "/kiosk/login/");

      const controls = await page.locator("button, a.button, input, select, textarea, label").evaluateAll((elements) =>
        elements
          .filter((element) => {
            const style = window.getComputedStyle(element);
            const box = element.getBoundingClientRect();
            return style.display !== "none" && style.visibility !== "hidden" && box.width > 0 && box.height > 0;
          })
          .map((element) => {
            const box = element.getBoundingClientRect();
            return { tag: element.tagName, text: element.textContent.trim(), width: box.width, height: box.height };
          })
      );

      expect(controls, `${viewport.width}x${viewport.height}`).not.toEqual([]);
      for (const control of controls) {
        expect(control.width, `${control.tag} ${control.text}`).toBeGreaterThanOrEqual(44);
        expect(control.height, `${control.tag} ${control.text}`).toBeGreaterThanOrEqual(44);
      }
    }
  });
});
