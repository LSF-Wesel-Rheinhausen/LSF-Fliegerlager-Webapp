const { expect, test } = require("./fixtures");
const { openKiosk } = require("./kioskAccess");

test.use({ serviceWorkers: "block" });

test.describe("Accessibility Audit Polish & Regression Suite", () => {
  test("Skip link is present and targets main content", async ({ page }) => {
    await openKiosk(page, "/kiosk/login/");

    const skipLink = page.locator("a.skip-link");
    await expect(skipLink).toBeAttached();

    await skipLink.focus();
    await expect(skipLink).toBeFocused();

    await page.keyboard.press("Enter");
    const mainContent = page.locator("#main-content");
    await expect(mainContent).toBeFocused();
  });

  test("Main interactive controls satisfy WCAG AA focus visibility", async ({ page }) => {
    await openKiosk(page, "/kiosk/login/");

    const loginButton = page.getByRole("button", { name: "Anmelden" });
    await loginButton.focus();
    await expect(loginButton).toBeFocused();

    const outlineStyle = await loginButton.evaluate((el) => {
      const computed = getComputedStyle(el);
      return computed.outlineStyle || computed.outline;
    });
    expect(outlineStyle).not.toBe("none");
  });
});
