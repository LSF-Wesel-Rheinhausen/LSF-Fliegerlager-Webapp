const { expect, test } = require("./fixtures");
const { openKiosk } = require("./kioskAccess");

test.use({ serviceWorkers: "block" });

test.describe("Screen Reader Live Region Announcements", () => {
  test("Live region elements exist and receive announcements", async ({ page }) => {
    await openKiosk(page, "/kiosk/login/");

    const politeAnnouncer = page.locator("#sr-announcer-polite");
    await expect(politeAnnouncer).toBeAttached();

    const assertiveAnnouncer = page.locator("#sr-announcer-assertive");
    await expect(assertiveAnnouncer).toBeAttached();

    await page.evaluate(() => {
      if (typeof window.announceToScreenReader === "function") {
        window.announceToScreenReader("Essen gebucht", "polite");
      }
    });

    await expect(politeAnnouncer).toHaveText("Essen gebucht");
  });
});
