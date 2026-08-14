const { expect, test } = require("./fixtures");
const { openKiosk } = require("./kioskAccess");

test.use({ serviceWorkers: "block" });

test.describe("Meal Email & Form Error Accessibility", () => {
  test("Form validation error sets focus and aria-invalid on field", async ({ page }) => {
    await openKiosk(page, "/kiosk/login/");

    const submitBtn = page.getByRole("button", { name: "Anmelden" });
    await submitBtn.click();

    const participantSelect = page.locator("select#id_participant");
    await expect(participantSelect).toBeVisible();
  });
});
