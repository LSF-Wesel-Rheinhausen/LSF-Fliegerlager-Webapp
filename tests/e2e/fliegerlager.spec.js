const { expect, test } = require("./fixtures");

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
  await page.getByRole("button", { name: "Abmelden" }).click();
}

async function loginAsAdmin(page) {
  await page.goto("/login/");
  await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
  await page.locator("#id_username").fill("admin@example.test");
  await page.locator("#id_password").fill("strong-test-pass-123");
  await page.getByRole("button", { name: "Anmelden" }).click();
  await expect(page.getByRole("heading", { name: "Lager" })).toBeVisible();
}

async function createCamp(page, name = "Sommerlager") {
  await page.getByRole("link", { name: "Lager anlegen" }).click();
  await expect(page.getByRole("heading", { name: "Lager anlegen" })).toBeVisible();
  const suffix = Date.now().toString();
  const campName = `${name} ${suffix}`;
  await page.getByLabel("Name").fill(campName);
  await page.getByLabel("Jahr").fill("2026");
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
  await expect(page.getByText(campName).first()).toBeVisible();
  return campName;
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

test("Admin edits a booking and sees the change log", async ({ page }) => {
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
  await expect(page.getByText(/^B#\d{5}$/).first()).toBeVisible();
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
  await expect(page.getByRole("heading", { name: "Änderungsprotokoll" })).toBeVisible();
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

test("Kiosk flow: login, pin setup, drink and meal booking", async ({ page }) => {
  await setupFirstAdmin(page);
  await createCamp(page, "Sommerlager Kiosk");
  await createParticipant(page, "Marie", "Curie");

  await page.getByRole("link", { name: "Fliegerlager-Abrechnung" }).click();
  await page.getByText("Sommerlager Kiosk").click();

  // Create drink price rule
  await page.getByRole("link", { name: "Preise verwalten" }).first().click();
  await page.getByRole("button", { name: "Getränk anlegen" }).click();
  await page.locator("#price-rule-dialog").getByLabel("Name").fill("Apfelsaft");
  await page.locator("#price-rule-dialog").getByLabel("Einzelpreis").fill("1.50");
  await page.locator("#price-rule-dialog").getByRole("button", { name: "Speichern" }).click();

  // Set meal standard price
  await page.locator('input[name="meal-breakfast_adult_price"]').fill("5.00");
  await page.locator('input[name="meal-dinner_adult_price"]').fill("7.00");
  await page.getByRole("button", { name: "Standardpreise speichern" }).click();

  await logout(page);

  // Kiosk Flow
  await page.goto("/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Marie Curie" });
  await page.getByLabel("PIN").fill("0000");
  await page.getByRole("button", { name: "Anmelden" }).click();

  // Should redirect to PIN setup
  await expect(page).toHaveURL(/.*\/kiosk\/pin\//);
  await page.getByLabel("Neuer PIN").fill("1234");
  await page.getByLabel("PIN wiederholen").fill("1234");
  await page.getByRole("button", { name: "Speichern" }).click();

  // Now in Kiosk Home
  await expect(page).toHaveURL(/.*\/kiosk\//);
  await expect(page.getByText("PIN wurde gesetzt.")).toBeVisible();

  // Book a drink
  await page.getByRole("button", { name: "Apfelsaft" }).click();
  await expect(page.getByText("Getränk wurde gebucht.")).toBeVisible();

  // Book a meal
  await page.locator('input[name="meal-meal_date"]').fill("2026-06-03");
  await Promise.all([
    page.waitForNavigation(),
    page.locator('section.panel').filter({ hasText: 'Essen anmelden' }).locator('form').evaluate(form => form.submit())
  ]);
  await expect(page.getByText("Essensanmeldung wurde gespeichert.")).toBeVisible();

  await page.getByRole("link", { name: "Abmelden" }).click();
  await expect(page).toHaveURL(/.*\/kiosk\/login\//);
});

test("Import flow: upload CSV and confirm", async ({ page }) => {
  await setupFirstAdmin(page);
  const campName = await createCamp(page, "Sommerlager Import");

  await page.getByRole("link", { name: "Teilnehmer importieren" }).click();

  const csvContent = "first_name,last_name\nImport,Test\n";
  await page.getByLabel("Importdatei").setInputFiles({
    name: "test.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csvContent),
  });
  await page.getByRole("button", { name: "Vorschau" }).click();

  await expect(page.getByText("Import Test")).toBeVisible();
  await page.getByRole("button", { name: "Gültige Zeilen importieren" }).click();

  await expect(page.getByText("1 Teilnehmer wurden importiert.")).toBeVisible();
  await expect(page.locator(".status-badge").first()).toContainText("Sommerlager Import");
});

test("Finance flow: payments and expenses", async ({ page }) => {
  await setupFirstAdmin(page);
  await createCamp(page, "Sommerlager Finance");
  await createParticipant(page, "Marie", "Curie");

  await page.getByRole("link", { name: "Zahlung erfassen" }).click();
  await page.getByLabel("Betrag").fill("50.00");
  await page.locator("#id_paid_on").fill("2026-07-01");
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByText("Zahlung wurde gespeichert.")).toBeVisible();

  // Create an expense
  await page.getByRole("link", { name: "Fliegerlager-Abrechnung" }).click();
  await page.getByText("Sommerlager Finance").click(); // Click on the camp link in the list
  await page.getByRole("link", { name: "Auslage erfassen" }).click();
  await page.getByLabel("Teilnehmer").selectOption({ label: "Marie Curie" });
  await page.locator("#id_category").fill("Bürobedarf");
  await page.getByLabel("Beschreibung").fill("Stifte");
  await page.getByLabel("Betrag").fill("15.50");
  await page.locator("#id_paid_on").fill("2026-07-01");
  await page.getByRole("button", { name: "Speichern" }).click();

  await expect(page.getByText("Auslage wurde gespeichert.")).toBeVisible();
});

test("Export flow: downloading CSV and XLSX returns 200 without deep parsing", async ({ page }) => {
  await setupFirstAdmin(page);
  await createCamp(page, "Sommerlager Export");
  await createParticipant(page, "Marie", "Curie");

  await page.getByRole("link", { name: "Fliegerlager-Abrechnung" }).click();
  await page.getByText("Sommerlager Export").click();

  const [downloadCsv] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole("link", { name: "Abrechnung als CSV herunterladen" }).click()
  ]);
  expect(downloadCsv.suggestedFilename()).toMatch(/\.csv$/);

  const [downloadXlsx] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole("link", { name: "Arbeitsmappe herunterladen" }).click()
  ]);
  expect(downloadXlsx.suggestedFilename()).toMatch(/\.xlsx$/);
});

test("Role flow: editor cannot see admin functions", async ({ page }) => {
  await setupFirstAdmin(page);

  await page.getByRole("link", { name: "Nutzer" }).click();
  await page.getByRole("link", { name: "Nutzer anlegen" }).click();
  await page.getByLabel("Benutzername").fill("editor");
  await page.getByLabel("E-Mail").fill("editor@example.test");
  await page.getByLabel("Rolle").selectOption("Bearbeiter");
  await page.locator("#id_password1").fill("editor-pass-123");
  await page.locator("#id_password2").fill("editor-pass-123");
  await page.getByRole("button", { name: "Speichern" }).click();

  await logout(page);

  await page.goto("/login/");
  await page.locator("#id_username").fill("editor@example.test");
  await page.locator("#id_password").fill("editor-pass-123");
  await page.getByRole("button", { name: "Anmelden" }).click();

  await expect(page.getByRole("link", { name: "Lager anlegen" })).toBeHidden();
  await expect(page.getByRole("link", { name: "Nutzer" })).toBeHidden();
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
