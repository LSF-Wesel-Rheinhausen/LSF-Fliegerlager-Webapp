const { expect, test } = require("./fixtures");

test.use({ serviceWorkers: "block" });

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
      const display = window.getComputedStyle(element).display;
      if (display !== "inline" && element.scrollWidth > element.clientWidth + 1 && !element.closest("table")) {
        failures.push(`text overflow: ${element.tagName.toLowerCase()} ${element.textContent.trim().slice(0, 80)}`);
      }
    }

    return { bodyOverflow, failures };
  });

  expect(result.bodyOverflow, "Unerwarteter horizontaler Seiten-Overflow").toBeLessThanOrEqual(1);
  expect(result.failures, "Elemente laufen aus der Anzeige oder aus ihrem Container").toEqual([]);
}

async function assertKioskCardsDoNotOverlap(page) {
  const overlaps = await page.locator("[data-kiosk-card]").evaluateAll((cards) => {
    const rectangles = cards.map((card) => ({
      key: card.dataset.kioskCard,
      rect: card.getBoundingClientRect(),
    }));
    const failures = [];

    for (let leftIndex = 0; leftIndex < rectangles.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < rectangles.length; rightIndex += 1) {
        const left = rectangles[leftIndex];
        const right = rectangles[rightIndex];
        const horizontalOverlap = left.rect.left < right.rect.right - 1 && left.rect.right > right.rect.left + 1;
        const verticalOverlap = left.rect.top < right.rect.bottom - 1 && left.rect.bottom > right.rect.top + 1;
        if (horizontalOverlap && verticalOverlap) failures.push(`${left.key}/${right.key}`);
      }
    }

    return failures;
  });

  expect(overlaps, "Kiosk-Karten überlappen sich").toEqual([]);
}

async function assertReadableContrast(locator, minimumRatio = 4.5) {
  const colors = await locator.evaluate((element) => {
    const styles = window.getComputedStyle(element);
    return { background: styles.backgroundColor, foreground: styles.color };
  });

  const parseRgb = (value) => value.match(/[\d.]+/g).slice(0, 3).map(Number);
  const luminance = (value) => {
    const channels = parseRgb(value).map((channel) => {
      const normalized = channel / 255;
      return normalized <= 0.04045
        ? normalized / 12.92
        : ((normalized + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
  };
  const foreground = luminance(colors.foreground);
  const background = luminance(colors.background);
  const ratio = (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05);

  expect(ratio, `Kontrast ${colors.foreground} auf ${colors.background}`).toBeGreaterThanOrEqual(minimumRatio);
}

function addDays(date, days) {
  const copy = new Date(date);
  copy.setDate(copy.getDate() + days);
  return copy;
}

function dateInputValue(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

async function setupFirstAdmin(page) {
  await page.goto("/setup/");
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

  await expect(page).toHaveURL(/\/camps\/?$/);
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
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Lager" })).toBeVisible();
}

async function createCamp(page, name = "Sommerlager") {
  await page.getByRole("link", { name: "Lager anlegen" }).click();
  await expect(page.getByRole("heading", { name: "Lager anlegen" })).toBeVisible();
  const suffix = Date.now().toString();
  const campName = `${name} ${suffix}`;
  const startDate = addDays(new Date(), 2);
  const endDate = addDays(startDate, 2);
  await page.getByLabel("Name").fill(campName);
  await page.getByLabel("Jahr").fill(String(startDate.getFullYear()));
  await page.getByLabel("Beginn").fill(dateInputValue(startDate));
  await page.getByLabel("Ende").fill(dateInputValue(endDate));
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

test("Admin registers and signs in with a passkey", async ({ context, page }) => {
  const browserErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("requestfailed", (request) => failedRequests.push(`${request.method()} ${request.url()}`));
  await context.credentials.install();
  await setupFirstAdmin(page);

  await page.getByRole("link", { name: "Passkeys" }).click();
  await expect(page.getByRole("heading", { name: "Passkeys" })).toBeVisible();
  await page.getByLabel("Bezeichnung").fill("Playwright Passkey");
  await page.getByRole("button", { name: "Passkey hinzufügen" }).click();
  await expect(page.getByText("Playwright Passkey", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoUnexpectedOverflow(page);
  await page.getByRole("switch", { name: "Dunkles Farbschema" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await assertNoUnexpectedOverflow(page);

  await logout(page);
  await expect(page).toHaveURL(/\/login\/?$/);
  await page.getByRole("button", { name: "Mit Passkey anmelden" }).click();

  await expect(page).toHaveURL(/\/camps\/?$/);
  await expect(page.getByRole("heading", { name: "Lager" })).toBeVisible();
  expect(browserErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
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
  await page.getByLabel("Fördersatz (%)").fill("100");
  await page.getByRole("button", { name: "Speichern" }).click();

  await expect(page.getByRole("heading", { name: "Ada Lovelace" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Buchungen", exact: true })).toBeVisible();
  await expect(page.getByText(/^B#\d{5}$/).first()).toBeVisible();
  await page.getByRole("link", { name: "Bearbeiten", exact: true }).click();
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

test("Admin archives a participant and creates a versioned settlement run", async ({ page }) => {
  await setupFirstAdmin(page);
  const campName = await createCamp(page, "Abrechnungslager");
  await createParticipant(page, "Ada", "Lovelace");

  await page.getByRole("link", { name: "Teilnehmer bearbeiten" }).click();
  const adminArrival = dateInputValue(addDays(new Date(), 2));
  const adminDeparture = dateInputValue(addDays(new Date(), 4));
  await page.getByLabel("Vorname").fill("Augusta Ada");
  await page.getByLabel("Anreise").fill(adminArrival);
  await page.getByLabel("Abreise").fill(adminDeparture);
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByRole("heading", { name: "Augusta Ada Lovelace" })).toBeVisible();
  await page.getByRole("link", { name: "Teilnehmer bearbeiten" }).click();
  await expect(page.getByLabel("Anreise")).toHaveValue(adminArrival);
  await expect(page.getByLabel("Abreise")).toHaveValue(adminDeparture);
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByRole("heading", { name: "Augusta Ada Lovelace" })).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Teilnehmer archivieren" }).click();
  await expect(page.getByRole("heading", { name: "Archivierte Teilnehmer" })).toBeVisible();
  await page.getByRole("button", { name: "Wiederherstellen" }).click();
  await expect(page.getByRole("heading", { name: "Augusta Ada Lovelace" })).toBeVisible();

  await page.goto("/camps/");
  await page.getByRole("link", { name: campName }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Abrechnungslauf erstellen" }).click();
  await expect(page.getByRole("heading", { name: /Abrechnung .* V1/ })).toBeVisible();
  await expect(page.getByRole("link", { name: "CSV herunterladen" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Excel herunterladen" })).toBeVisible();
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
  const campName = await createCamp(page, "Sommerlager Kiosk");
  await createParticipant(page, "Marie", "Curie");

  await page.getByRole("link", { name: "Fliegerlager-Abrechnung" }).click();
  await page.getByRole("link", { name: campName, exact: true }).click();

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
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();

  // Should redirect to PIN setup
  await expect(page).toHaveURL(/.*\/kiosk\/pin\//);
  await page.getByLabel("Neuer PIN").fill("1234");
  await page.getByLabel("PIN wiederholen").fill("1234");
  await page.getByRole("button", { name: "Speichern" }).click();

  // Now in Kiosk Home
  await expect(page).toHaveURL(/.*\/kiosk\//);
  await expect(page.getByText("PIN wurde gesetzt.")).toBeVisible();
  const sessionCookie = (await page.context().cookies()).find((cookie) => cookie.name === "sessionid");
  expect(sessionCookie).toBeDefined();
  expect(sessionCookie.expires).toBeGreaterThan(Date.now() / 1000);

  // Check-in can be entered from the kiosk.
  const checkinArrival = dateInputValue(addDays(new Date(), 2));
  const checkinDeparture = dateInputValue(addDays(new Date(), 4));
  await page.getByRole("button", { name: "Eintragen" }).click();
  await expect(page.locator("dialog#checkin-dialog")).toBeVisible();
  await page.locator("dialog#checkin-dialog").getByLabel("Anreise").fill(checkinArrival);
  await page.locator("dialog#checkin-dialog").getByLabel("Abreise").fill(checkinDeparture);
  await page.locator("dialog#checkin-dialog").getByRole("button", { name: "Check-in speichern" }).click();
  await expect(page.getByText("Check-in-Daten wurden gespeichert.")).toBeVisible();
  await page.getByRole("button", { name: "Eintragen" }).click();
  await expect(page.locator("dialog#checkin-dialog").getByLabel("Anreise")).toHaveValue(checkinArrival);
  await expect(page.locator("dialog#checkin-dialog").getByLabel("Abreise")).toHaveValue(checkinDeparture);
  await page.keyboard.press("Escape");

  // Breakfast is a same-day quick booking and skips the meal calendar.
  await page.locator("[data-food-button]").first().click();
  await expect(page.locator("dialog#food-dialog")).toBeVisible();
  await expect(page.locator("#food-step-date")).toHaveCount(0);
  await expect(page.locator("dialog#food-dialog").getByText("Wer soll eingebucht werden?")).toBeVisible();
  await page.locator("dialog#food-dialog").getByRole("button", { name: "Kostenpflichtig buchen" }).click();
  await expect(page.getByText(/Standard Frühstück.*gebucht\./)).toBeVisible();

  // Book a drink
  await page.getByRole("button", { name: "Apfelsaft" }).click();
  await expect(page.locator("dialog#quick-dialog")).toBeVisible();
  await page.locator("dialog#quick-dialog").getByRole("button", { name: "1x" }).click();
  await expect(page.getByText("Apfelsaft gebucht.")).toBeVisible();

  // The cancellation action stays directly usable on a phone-sized viewport.
  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoUnexpectedOverflow(page);
  await page.getByRole("button", { name: "Menü", exact: true }).click();
  await page.getByRole("button", { name: "Letzte Schnellbuchungen" }).click();
  await expect(page.locator("dialog:open")).toHaveCount(1);
  await page.locator("dialog#quick-bookings-dialog [data-open-quick-cancel-dialog]").first().click();
  await expect(page.locator("dialog#quick-cancel-dialog")).toBeVisible();
  await expect(page.locator("dialog:open")).toHaveCount(1);
  await expect(page.locator("dialog#quick-cancel-dialog")).toContainText("Apfelsaft");
  await page.locator("dialog#quick-cancel-dialog").getByRole("button", { name: "Jetzt stornieren" }).click();
  await expect(page.getByText("Buchung wurde storniert.")).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 800 });

  // Book the same participant for two meal dates in one submission.
  await page.getByRole("button", { name: "Menü", exact: true }).click();
  await page.getByRole("button", { name: "Essenskalender", exact: true }).click();
  await page.locator("dialog#meal-calendar-dialog").getByRole("button", { name: "Essen buchen" }).click();
  await expect(page.locator("dialog#meal-dialog")).toBeVisible();
  const mealDateChoices = page.locator("dialog#meal-dialog input[data-meal-date-checkbox]:not([disabled])");
  await mealDateChoices.nth(0).check();
  await mealDateChoices.nth(1).check();
  await page.locator("dialog#meal-dialog").getByRole("button", { name: "Weiter" }).click();
  await expect(page.locator("#meal-selected-date")).toContainText("2 Tage ausgewählt");
  await page.locator("dialog#meal-dialog").getByRole("button", { name: "Essensanmeldung speichern" }).click();
  await expect(page.getByText("Essensanmeldung wurde für 2 Tage und 1 Person gespeichert.")).toBeVisible();
  await expect(page).toHaveURL(/.*\/kiosk\/#meal-calendar$/);

  await page.locator("dialog#meal-calendar-dialog").getByRole("button", { name: "Essen buchen" }).click();
  await expect(page.locator("dialog#meal-dialog").getByText("Gebucht für Marie Curie").first()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("dialog#meal-calendar-dialog")).toBeVisible();
  await page.keyboard.press("Escape");

  await page.getByRole("link", { name: "Abmelden" }).click();
  await expect(page).toHaveURL(/.*\/kiosk\/login\//);
});

test("Kiosk masonry and expense cards stay responsive and accessible", async ({ page }) => {
  const browserErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("requestfailed", (request) => failedRequests.push(`${request.method()} ${request.url()}`));

  await setupFirstAdmin(page);
  const campName = await createCamp(page, "Masonry-Lager");
  await createParticipant(page, "Marie", "Curie");
  await logout(page);

  await page.goto("/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Marie Curie" });
  await page.getByLabel("PIN").fill("0000");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await page.getByLabel("Neuer PIN").fill("1234");
  await page.getByLabel("PIN wiederholen").fill("1234");
  await page.getByRole("button", { name: "Speichern" }).click();

  await page.getByRole("button", { name: "Menü", exact: true }).click();
  await page.getByRole("button", { name: "Gemeinschaftsausgaben" }).click();
  await page.getByRole("link", { name: "Antrag einreichen" }).click();
  await page.getByLabel("Kategorie").selectOption({ label: "Verbrauchsmaterial" });
  await page.getByLabel("Beschreibung").fill("Sehr langer Gemeinschaftseinkauf für das gesamte Fliegerlager");
  await page.getByLabel("Betrag").fill("42.00");
  await page.getByLabel("Zahlungsdatum").fill(dateInputValue(new Date()));
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByText("Antrag auf Gemeinschaftsausgabe eingereicht.")).toBeVisible();
  await page.getByRole("link", { name: "Abmelden" }).click();

  await loginAsAdmin(page);
  await page.getByRole("link", { name: campName, exact: true }).click();
  await page.getByRole("button", { name: "Ablehnen" }).click();
  await page.getByLabel("Begründung (Pflichtfeld)").fill(
    "Der eingereichte Nachweis ist nicht lesbar. Bitte reiche einen neuen Beleg mit vollständigem Betrag ein."
  );
  await page.getByRole("button", { name: "Antrag endgültig ablehnen" }).click();
  await expect(page.getByText(/Antrag abgelehnt/)).toBeVisible();
  await logout(page);

  await page.goto("/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Marie Curie" });
  await page.getByLabel("PIN").fill("1234");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await page.waitForLoadState("networkidle");
  browserErrors.length = 0;
  failedRequests.length = 0;
  await page.setViewportSize({ width: 1280, height: 900 });

  const masonry = page.locator("[data-kiosk-masonry]");
  await expect(masonry).toHaveClass(/is-enhanced/);
  await expect(page.locator(".meal-signup-compact")).toHaveCount(0);
  const desktopLayout = await page.locator("[data-kiosk-card]").evaluateAll((cards) => ({
    columns: new Set(cards.map((card) => Math.round(card.getBoundingClientRect().left))).size,
    spans: cards.map((card) => card.style.gridRowEnd),
  }));
  expect(desktopLayout.columns).toBe(2);
  expect(desktopLayout.spans.every((span) => span.startsWith("span "))).toBe(true);
  await assertKioskCardsDoNotOverlap(page);
  await assertNoUnexpectedOverflow(page);

  const cardOrder = await page.locator("[data-kiosk-card]").evaluateAll((cards) => cards.map((card) => card.dataset.kioskCard));
  expect(cardOrder).toEqual([
    "drinks",
    "food",
    "shifts",
    "check-in",
  ]);

  const firstCardControl = masonry.locator("button:visible, a[href]:visible").first();
  await firstCardControl.focus();
  const focusedCardIndexes = [];
  for (let index = 0; index < 10; index += 1) {
    const focusedCardIndex = await page.evaluate(() => {
      const card = document.activeElement?.closest("[data-kiosk-card]");
      return card ? Array.from(document.querySelectorAll("[data-kiosk-card]")).indexOf(card) : -1;
    });
    if (focusedCardIndex < 0 && focusedCardIndexes.length) break;
    if (focusedCardIndex >= 0) focusedCardIndexes.push(focusedCardIndex);
    await page.keyboard.press("Tab");
  }
  expect(focusedCardIndexes).toEqual([...focusedCardIndexes].sort((left, right) => left - right));

  const menuButton = page.getByRole("button", { name: "Menü", exact: true });
  await menuButton.focus();
  await menuButton.click();
  const menuDialog = page.locator("dialog#kiosk-menu-dialog");
  const familyMenuButton = menuDialog.getByRole("button", { name: "Familie", exact: true });
  await familyMenuButton.click();
  await expect(page.locator("dialog#family-management-dialog")).toBeVisible();
  await expect(page.locator("dialog:open")).toHaveCount(1);
  await page.keyboard.press("Escape");
  await expect(menuDialog).toBeVisible();
  await expect(familyMenuButton).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menuButton).toBeFocused();

  await menuButton.click();
  await menuDialog.getByRole("button", { name: "Gemeinschaftsausgaben" }).click();
  const expenseSection = page.locator("dialog#shared-expenses-dialog");
  await expenseSection.getByText("Ablehnungsgrund anzeigen").click();
  await expect(expenseSection.locator("details")).toHaveAttribute("open", "");
  await assertNoUnexpectedOverflow(page);

  await expenseSection.getByRole("button", { name: "Schließen" }).click();
  await expect(menuDialog).toBeVisible();
  await page.keyboard.press("Escape");
  await page.locator("[data-theme-toggle]").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await menuButton.click();
  await menuDialog.getByRole("button", { name: "Gemeinschaftsausgaben" }).click();
  await expect(expenseSection).toBeVisible();
  await assertKioskCardsDoNotOverlap(page);

  await expenseSection.getByRole("button", { name: "Schließen" }).click();
  await expect(menuDialog).toBeVisible();
  await page.keyboard.press("Escape");

  await page.setViewportSize({ width: 780, height: 900 });
  await expect(masonry).not.toHaveClass(/is-enhanced/);
  const mobileLayout = await page.locator("[data-kiosk-card]").evaluateAll((cards) => ({
    columns: new Set(cards.map((card) => Math.round(card.getBoundingClientRect().left))).size,
    spans: cards.map((card) => card.style.gridRowEnd),
  }));
  expect(mobileLayout.columns).toBe(1);
  expect(mobileLayout.spans).toEqual(Array(mobileLayout.spans.length).fill(""));
  await assertKioskCardsDoNotOverlap(page);
  await assertNoUnexpectedOverflow(page);

  expect(browserErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});

test("Theme switch persists across kiosk and admin layouts", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/kiosk/login/");

  const themeToggle = page.locator("[data-theme-toggle]");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.getByLabel("Teilnehmer")).toHaveValue("");
  await expect(page.getByLabel("Teilnehmer").locator("option").first()).toHaveText("Bitte Teilnehmer auswählen");
  await expect(themeToggle).toHaveAttribute("role", "switch");
  await expect(themeToggle).toHaveAttribute("aria-checked", "false");

  await themeToggle.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(themeToggle).toHaveAttribute("aria-checked", "true");

  await page.goto("/login/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator("[data-theme-toggle]")).toHaveAttribute("aria-checked", "true");

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("Theme follows the system preference without a saved selection", async ({ page, browserName }) => {
  test.skip(browserName === "firefox", "Firefox does not support Playwright color-scheme emulation.");
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/kiosk/login/");

  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator("[data-theme-toggle]")).toHaveAttribute("aria-checked", "true");
});

test("Dark theme keeps contextual surfaces readable and responsive", async ({ page }) => {
  const browserErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("requestfailed", (request) => failedRequests.push(`${request.method()} ${request.url()}`));

  await setupFirstAdmin(page);
  await createCamp(page, "Dark-Mode-Lager");
  const campId = new URL(page.url()).pathname.match(/\/camps\/(\d+)\//)[1];
  await page.locator("[data-theme-toggle]").click();

  const surfaces = [
    { path: "/help/admin/", selector: ".info-callout" },
    { path: "/help/", selector: ".info-callout" },
    { path: `/camps/${campId}/`, selector: ".info-callout" },
    { path: `/camps/${campId}/prices/`, selector: ".info-callout" },
    { path: `/camps/${campId}/import/`, selector: ".info-callout" },
    { path: `/camps/${campId}/shifts/report/`, selector: ".shift-stat-card" },
  ];

  for (const surface of surfaces) {
    await page.goto(surface.path);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.locator(surface.selector).first()).toBeVisible();
    await assertReadableContrast(page.locator(surface.selector).first());
    await assertNoUnexpectedOverflow(page);
  }

  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ["/help/", `/camps/${campId}/shifts/report/`]) {
    await page.goto(path);
    await assertNoUnexpectedOverflow(page);
  }

  expect(browserErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});

test("Import flow: upload CSV and confirm", async ({ page }) => {
  await setupFirstAdmin(page);
  const campName = await createCamp(page, "Sommerlager Import");

  await page.getByRole("link", { name: "Teilnehmer importieren" }).click();

  const csvContent = "first_name,last_name,arrival_date,departure_date,hilfssatz,berufssatz\nImport,Test,01.07.2026,10.07.2026,0.15,0.08\n";
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
  await page.locator("#id_category").selectOption({ label: "Verbrauchsmaterial" });
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

  const csvLink = page.getByRole("link", { name: "Abrechnung als CSV herunterladen" });
  const csvHref = await csvLink.getAttribute("href");
  const csvResponse = await page.request.get(csvHref);
  expect(csvResponse.ok()).toBeTruthy();
  expect(csvResponse.headers()['content-disposition']).toContain('.csv');

  const xlsxLink = page.getByRole("link", { name: "Arbeitsmappe herunterladen" });
  const xlsxHref = await xlsxLink.getAttribute("href");
  const xlsxResponse = await page.request.get(xlsxHref);
  expect(xlsxResponse.ok()).toBeTruthy();
  expect(xlsxResponse.headers()['content-disposition']).toContain('.xlsx');
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
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();

  await expect(page.getByRole("link", { name: "Lager anlegen" })).toBeHidden();
  await expect(page.getByRole("link", { name: "Nutzer" })).toBeHidden();
});

test("Daily shift template and kiosk shift flow", async ({ page }) => {
  await setupFirstAdmin(page);
  await createCamp(page, "Sommerlager Dienste");
  await createParticipant(page, "Albert", "Einstein");

  // Create a daily shift template via Frontend
  await page.getByRole("link", { name: "Fliegerlager-Abrechnung" }).click();
  await page.getByRole("link", { name: "Sommerlager Dienste" }).click();
  await page.getByRole("link", { name: "Tägliche Vorlagen verwalten" }).click();
  await page.getByRole("button", { name: "Vorlage anlegen" }).click();
  await expect(page.locator("dialog#template-dialog")).toBeVisible();
  await page.getByLabel("Name / Bezeichnung").fill("Spüldienst");
  await page.getByLabel("Benötigte Personen").fill("2");
  await page.getByRole("button", { name: "Speichern", exact: true }).click();
  await expect(page.getByText("Spüldienst").first()).toBeVisible();

  // Generate shifts
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "Dienste generieren" }).click();
  await expect(page.getByText("Dienste generiert")).toBeVisible();

  await logout(page);

  // Login to kiosk
  await page.goto("/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Albert Einstein" });
  await page.getByLabel("PIN").fill("0000");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();

  // Set PIN
  await page.getByLabel("Neuer PIN").fill("1234");
  await page.getByLabel("PIN wiederholen").fill("1234");
  await page.getByRole("button", { name: "Speichern" }).click();

  // Go to Shifts
  await page.getByRole("link", { name: "Dienstplan" }).click();
  await expect(page.getByRole("heading", { name: "Dienstplan" })).toBeVisible();

  // Check progress bar
  await expect(page.getByText("Dein Fortschritt")).toBeVisible();
  await expect(page.getByText("Super! Du hast alle Pflichtdienste übernommen.")).toBeVisible();

  // Sign up for a shift
  await page.getByRole("button", { name: "Eintragen" }).first().click();
  await expect(page.getByText("Du hast dich für 'Spüldienst' eingetragen.")).toBeVisible();

  // "Austragen" should not exist, only "Zum Tausch anbieten"
  await expect(page.getByRole("button", { name: "Austragen" })).toBeHidden();
  await page.getByRole("button", { name: "Zum Tausch anbieten" }).first().click();
  await expect(page.getByText("wird nun zum Tausch angeboten.")).toBeVisible();

  // The shift should now be in the "Meine übernommenen Dienste" and have "Angebot zurückziehen"
  await expect(page.getByRole("button", { name: "Angebot zurückziehen" })).toBeVisible();

  await page.getByRole("link", { name: "Zurück" }).click();
  await page.getByRole("link", { name: "Abmelden" }).click();
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

for (const viewport of [
  { name: "mobile portrait", width: 430, height: 932 },
  { name: "mobile landscape", width: 932, height: 430 },
]) {
  test(`Kiosk meal and drink layout has no overflow in ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await setupFirstAdmin(page);
    const campName = await createCamp(page, "Sommerlager Kiosk Mobile");
    await createParticipant(page, "Mobile", "ExtremLangerUngetrennterTeilnehmername");

    await page.getByRole("link", { name: "Fliegerlager-Abrechnung" }).click();
    await page.getByRole("link", { name: campName, exact: true }).click();
    await page.getByRole("link", { name: "Preise verwalten" }).first().click();
    await page.locator('input[name="meal-breakfast_adult_price"]').fill("5.00");
    await page.locator('input[name="meal-dinner_adult_price"]').fill("7.00");
    await page.getByRole("button", { name: "Standardpreise speichern" }).click();
    await logout(page);

    await page.goto("/kiosk/login/");
    await page.getByLabel("Teilnehmer").selectOption({ label: "Mobile ExtremLangerUngetrennterTeilnehmername" });
    await page.getByLabel("PIN").fill("0000");
    await page.getByRole("button", { name: "Anmelden", exact: true }).click();
    await page.getByLabel("Neuer PIN").fill("1234");
    await page.getByLabel("PIN wiederholen").fill("1234");
    await page.getByRole("button", { name: "Speichern" }).click();

    await expect(page.getByRole("heading", { name: "Getränk buchen" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Verpflegung buchen" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Essenskalender" })).toBeHidden();
    await page.getByRole("button", { name: "Menü", exact: true }).click();
    await page.getByRole("button", { name: "Essenskalender", exact: true }).click();
    await page.locator("dialog#meal-calendar-dialog").getByRole("button", { name: "Essen buchen" }).click();
    await expect(page.locator("dialog#meal-dialog")).toBeVisible();
    await assertNoUnexpectedOverflow(page);
  });
}
