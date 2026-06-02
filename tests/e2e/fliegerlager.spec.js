const { expect, test } = require("@playwright/test");

const VIEWPORTS = [
  { name: "13 Zoll Laptop", width: 1280, height: 800 },
  { name: "Laptop", width: 1440, height: 900 },
  { name: "Monitor", width: 1920, height: 1080 },
  { name: "27 Zoll Monitor", width: 2560, height: 1440 },
  { name: "iPhone 14", width: 390, height: 844 },
  { name: "iPhone 17 Pro", width: 393, height: 852 },
  { name: "iPhone 17 Pro Max", width: 430, height: 932 },
];

async function isVisible(locator) {
  return locator.isVisible().catch(() => false);
}

async function assertNoUnexpectedOverflow(page) {
  const result = await page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth;
    const bodyOverflow = document.documentElement.scrollWidth - viewportWidth;
    const failures = [];
    const selectors = [
      "header.topbar",
      ".brand",
      ".topbar nav",
      ".toolbar",
      ".actions",
      ".exportbar",
      "button",
      "a.button",
      "input",
      "select",
      "textarea",
      "label",
      "h1",
    ];

    for (const element of document.querySelectorAll(selectors.join(","))) {
      const rect = element.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) {
        continue;
      }
      if (rect.left < -1 || rect.right > viewportWidth + 1) {
        failures.push(`${element.tagName.toLowerCase()} ${element.textContent.trim().slice(0, 80)}`);
      }
      if (element.scrollWidth > element.clientWidth + 1 && !element.closest("table")) {
        failures.push(`text overflow: ${element.tagName.toLowerCase()} ${element.textContent.trim().slice(0, 80)}`);
      }
    }

    return { bodyOverflow, failures };
  });

  expect(result.bodyOverflow, "Unerwarteter horizontaler Seiten-Overflow").toBeLessThanOrEqual(1);
  expect(result.failures, "Elemente laufen aus der Anzeige oder aus ihrem Container").toEqual([]);
}

async function setupFirstAdmin(page) {
  await page.goto("/");
  if (page.url().includes("/login/")) {
    await loginAsAdmin(page);
    return;
  }
  await expect(page).toHaveURL(/\/setup\/?$/);
  await expect(page.getByRole("heading", { name: "Ersteinrichtung" })).toBeVisible();
  await expect(page.getByAltText("Luftsportfreunde Wesel-Rheinhausen e.V.")).toBeVisible();

  await page.locator("#id_username").fill("admin");
  await page.locator("#id_email").fill("admin@example.test");
  await page.locator("#id_password1").fill("strong-test-pass-123");
  await page.locator("#id_password2").fill("strong-test-pass-123");
  await page.getByRole("button", { name: "Admin anlegen" }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Lager" })).toBeVisible();
}

async function logout(page) {
  const logoutButton = page.getByRole("button", { name: "Abmelden" });
  if (await isVisible(logoutButton)) {
    await logoutButton.click();
  }
}

async function loginAsAdmin(page) {
  await page.goto("/login/");
  await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
  await page.locator("#id_username").fill("admin@example.test");
  await page.locator("#id_password").fill("strong-test-pass-123");
  await page.getByRole("button", { name: "Anmelden" }).click();
  await expect(page.getByRole("heading", { name: "Lager" })).toBeVisible();
}

async function createCamp(page) {
  await page.getByRole("link", { name: "Lager anlegen" }).click();
  await expect(page.getByRole("heading", { name: "Lager anlegen" })).toBeVisible();
  const suffix = Date.now().toString();
  await page.getByLabel("Name").fill(`Sommerlager ${suffix}`);
  await page.getByLabel("Jahr").fill("2026");
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByRole("heading", { name: `Sommerlager ${suffix} 2026` })).toBeVisible();
}

async function createParticipant(page, firstName, lastName) {
  await page.getByRole("link", { name: "Teilnehmer anlegen" }).click();
  await expect(page.getByRole("heading", { name: "Teilnehmer anlegen" })).toBeVisible();
  await page.getByLabel("Vorname").fill(firstName);
  await page.getByLabel("Nachname").fill(lastName);
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByRole("heading", { name: `${firstName} ${lastName}` })).toBeVisible();
}

test("Admin completes setup, login, camp workflow and logout", async ({ page }) => {
  await setupFirstAdmin(page);
  await createCamp(page);

  await expect(page.getByRole("link", { name: "Teilnehmer anlegen" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Preise verwalten" }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Auslage erfassen" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Teilnehmer importieren" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Abrechnung als CSV herunterladen" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Arbeitsmappe herunterladen" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Getränke als CSV herunterladen" })).toBeVisible();

  await assertNoUnexpectedOverflow(page);
  await logout(page);
  await expect(page).toHaveURL(/\/login\/?$/);
  await loginAsAdmin(page);
});

test("Admin edits a booking and sees the audit log", async ({ page }) => {
  await setupFirstAdmin(page);
  await createCamp(page);
  await createParticipant(page, "Ada", "Lovelace");

  await page.getByRole("link", { name: "Kosten erfassen" }).click();
  await expect(page.getByRole("heading", { name: "Kostenposition erfassen" })).toBeVisible();
  await page.getByLabel("Art").selectOption("drink");
  await page.getByLabel("Beschreibung").fill("Cola");
  await page.getByLabel("Menge").fill("2");
  await page.getByLabel("Einzelpreis").fill("2.50");
  await page.getByLabel("Förderfähig").check();
  await page.getByRole("button", { name: "Speichern" }).click();

  await expect(page.getByRole("heading", { name: "Ada Lovelace" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Buchungen", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Bearbeiten" }).click();
  await expect(page.getByRole("heading", { name: "Buchung bearbeiten" })).toBeVisible();
  await page.getByLabel("Beschreibung").fill("Cola korrigiert");
  await page.getByLabel("Menge").fill("3");
  await page.getByLabel("Datum").fill("2026-07-01");
  await page.getByRole("button", { name: "Speichern" }).click();

  await expect(page.getByRole("heading", { name: "Ada Lovelace" })).toBeVisible();
  await expect(page.getByText("Buchung wurde gespeichert und protokolliert.")).toBeVisible();
  await expect(page.getByRole("cell", { name: "Cola korrigiert" }).first()).toBeVisible();
  await expect(page.getByRole("cell", { name: "7,50 €" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Audit-Protokoll Buchungen" })).toBeVisible();
  await expect(page.getByText("Cola · 2.00 x 2.50")).toBeVisible();
  await expect(page.getByText("Cola korrigiert · 3.00 x 2.50")).toBeVisible();
});

test("Admin can open and close price rule dialogs natively", async ({ page }) => {
  await setupFirstAdmin(page);
  await createCamp(page);

  await page.getByRole("link", { name: "Preise verwalten" }).first().click();

  // Open dialog
  await page.getByRole("button", { name: "Einzelpreis anlegen" }).click();
  await expect(page.locator("dialog#price-rule-dialog")).toBeVisible();
  await expect(page.locator("#dialog-title")).toHaveText("Preisregel anlegen");

  // Close dialog via native form button
  await page.getByRole("button", { name: "Schließen" }).click();
  await expect(page.locator("dialog#price-rule-dialog")).toBeHidden();

  // Open another dialog to ensure it resets/works again
  await page.getByRole("button", { name: "Getränk anlegen" }).click();
  await expect(page.locator("dialog#price-rule-dialog")).toBeVisible();
  await expect(page.locator("#dialog-title")).toHaveText("Getränk anlegen");

  // Close dialog via Escape key (native behavior)
  await page.keyboard.press("Escape");
  await expect(page.locator("dialog#price-rule-dialog")).toBeHidden();
});

for (const viewport of VIEWPORTS) {
  test(`Layout has no unexpected overflow at ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await setupFirstAdmin(page);
    await createCamp(page);
    await assertNoUnexpectedOverflow(page);

    await page.getByRole("link", { name: "Teilnehmer anlegen" }).click();
    await expect(page.getByRole("heading", { name: "Teilnehmer anlegen" })).toBeVisible();
    await assertNoUnexpectedOverflow(page);
  });
}
