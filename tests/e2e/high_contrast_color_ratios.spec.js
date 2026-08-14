const { expect, test } = require("./fixtures");
const { openKiosk } = require("./kioskAccess");

test.use({ serviceWorkers: "block" });

test.describe("High Contrast Theme & Color Contrast Standards", () => {
  test("Applies high-contrast theme via data attribute", async ({ page }) => {
    await openKiosk(page, "/kiosk/login/");

    await page.evaluate(() => {
      document.documentElement.setAttribute("data-theme", "high-contrast");
    });

    const bg = await page.evaluate(() => {
      return getComputedStyle(document.documentElement).getPropertyValue("--bg").trim();
    });
    expect(bg).toBe("#000000");

    const themeToggle = page.locator(".theme-toggle");
    await expect(themeToggle).toBeVisible();
  });

  test("Focus indicators remain visible with high contrast outlines", async ({ page }) => {
    await openKiosk(page, "/kiosk/login/");

    const button = page.getByRole("button", { name: "Anmelden" });
    await button.focus();
    await expect(button).toBeFocused();

    const outlineStyle = await button.evaluate((el) => {
      const computed = getComputedStyle(el);
      return computed.outlineStyle || computed.outline;
    });
    expect(outlineStyle).not.toBe("none");
  });
});
