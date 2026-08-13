const { expect, test } = require("./fixtures");

test.use({ serviceWorkers: "block" });

async function signInAdmin(page) {
  await page.goto("/setup/");
  if (await page.getByRole("heading", { name: "Ersteinrichtung" }).isVisible().catch(() => false)) {
    await page.locator("#id_username").fill("admin");
    await page.locator("#id_email").fill("admin@example.test");
    await page.locator("#id_password1").fill("strong-test-pass-123");
    await page.locator("#id_password2").fill("strong-test-pass-123");
    await page.getByRole("button", { name: "Admin anlegen" }).click();
  }
  await page.goto("/admin/login/");
  if (page.url().includes("/admin/login")) {
    await page.locator("#id_username").fill("admin");
    await page.locator("#id_password").fill("strong-test-pass-123");
    await page.getByRole("button", { name: /Log in|Anmelden/ }).click();
  }
  await expect(page).toHaveURL(/\/admin\/?$/);
}

async function openParticipantChangePage(page) {
  await page.goto("/admin/billing/participant/add/");
  await page.locator("#id_camp").selectOption({ index: 1 });
  await page.locator("#id_first_name").fill("ARIA");
  const lastName = `Test ${Date.now()}`;
  await page.locator("#id_last_name").fill(lastName);
  await page.locator('input[name="_save"]').click();
  await expect(page).toHaveURL(/\/admin\/billing\/participant\/$/);
  await page.getByRole("link", { name: `ARIA ${lastName}`, exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/billing\/participant\/\d+\/change\/$/);
}

async function collectAriaViolations(page) {
  return page.evaluate(() => {
    const ids = new Set([...document.querySelectorAll("[id]")].map((element) => element.id));
    const violations = [];
    for (const element of document.querySelectorAll("[aria-describedby], [aria-labelledby]")) {
      for (const attribute of ["aria-describedby", "aria-labelledby"]) {
        for (const reference of (element.getAttribute(attribute) || "").split(/\s+/).filter(Boolean)) {
          if (!ids.has(reference)) violations.push({ attribute, reference });
        }
      }
    }
    return violations;
  });
}

test("Participant-Admin-DOM has no dangling ARIA references", async ({ page }) => {
  const browserErrors = [];
  const failedRequests = [];
  page.on("console", (message) => { if (message.type() === "error") browserErrors.push(message.text()); });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("requestfailed", (request) => failedRequests.push(`${request.method()} ${request.url()}`));
  await signInAdmin(page);
  await openParticipantChangePage(page);

  for (const [colorScheme, viewport] of [["light", { width: 1280, height: 800 }], ["dark", { width: 390, height: 844 }]]) {
    await page.emulateMedia({ colorScheme });
    await page.setViewportSize(viewport);
    const result = await page.evaluate(() => {
      const ids = [...document.querySelectorAll("[id]")].map((element) => element.id);
      const referencedIds = [];
      for (const element of document.querySelectorAll("[aria-describedby], [aria-labelledby]")) {
        for (const attribute of ["aria-describedby", "aria-labelledby"]) {
          referencedIds.push(...(element.getAttribute(attribute) || "").split(/\s+/).filter(Boolean));
        }
      }
      return {
        duplicateIds: ids.filter((id, index) => ids.indexOf(id) !== index),
        missingIds: referencedIds.filter((id) => !ids.includes(id)),
        dateIds: ["id_arrival_date", "id_departure_date", "id_archived_at_0", "id_archived_at_1"].map((id) => Boolean(document.getElementById(id))),
      };
    });
    expect(result.duplicateIds).toEqual([]);
    expect(result.missingIds).toEqual([]);
    expect(result.dateIds).toEqual([true, true, true, true]);
  }
  expect(browserErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});

test("Participant-Admin axe aria-valid-attr-value regression stays clean", async ({ page }) => {
  await signInAdmin(page);
  await openParticipantChangePage(page);
  expect(await collectAriaViolations(page)).toEqual([]);
});

test("Participant-Admin date form submits through keyboard focus", async ({ page }) => {
  await signInAdmin(page);
  await openParticipantChangePage(page);
  await page.locator("#id_arrival_date").fill("2026-07-01");
  await page.locator("#id_departure_date").fill("2026-07-03");
  const saveButton = page.locator('input[name="_save"]');
  await saveButton.focus();
  await expect(saveButton).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByText(/was changed successfully|wurde erfolgreich geändert/)).toBeVisible();
});
