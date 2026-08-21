const { expect, test } = require("./fixtures");
const { KIOSK_ACCESS_PIN, configureCampKioskAccess, openKiosk } = require("./kioskAccess");
const { isBenignPageRequestFailure, requestFailureDetails } = require("./requestFailureFilter");

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

function trackPageIssues(page) {
  const browserErrors = [];
  const failedRequests = [];

  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("requestfailed", (request) => {
    const details = requestFailureDetails(request);
    if (!isBenignPageRequestFailure(details)) {
      failedRequests.push(`${details.method} ${details.url}${details.errorText ? ` (${details.errorText})` : ""}`);
    }
  });

  return { browserErrors, failedRequests };
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
      const hasInternallyScrollableValue = element instanceof HTMLInputElement;
      if (
        !hasInternallyScrollableValue &&
        display !== "inline" &&
        element.scrollWidth > element.clientWidth + 1 &&
        !element.closest("table")
      ) {
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

async function expectModalDialogIds(page, expectedIds) {
  await expect
    .poll(() =>
      page.evaluate(() =>
        [...document.querySelectorAll("dialog")]
          .filter((dialog) => dialog.open || dialog.matches(":modal"))
          .map((dialog) => dialog.id),
      ),
    )
    .toEqual(expectedIds);
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

function germanDate(date) {
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(date);
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

async function createCamp(page, name = "Sommerlager", startOffsetDays = 2, durationDays = 2) {
  await page.getByRole("link", { name: "Lager anlegen" }).click();
  await expect(page.getByRole("heading", { name: "Lager anlegen" })).toBeVisible();
  const suffix = Date.now().toString();
  const campName = `${name} ${suffix}`;
  const startDate = addDays(new Date(), startOffsetDays);
  const endDate = addDays(startDate, durationDays);
  await page.getByLabel("Name").fill(campName);
  await page.getByLabel("Jahr").fill(String(startDate.getFullYear()));
  await page.getByLabel("Beginn").fill(dateInputValue(startDate));
  await page.getByLabel("Ende").fill(dateInputValue(endDate));
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
  await expect(page.getByText(campName).first()).toBeVisible();
  await configureCampKioskAccess(page);
  return campName;
}

async function createParticipant(page, firstName, lastName, email = "", pin = null) {
  await page.getByRole("link", { name: "Teilnehmer anlegen" }).click();
  await expect(page.getByRole("heading", { name: "Teilnehmer anlegen" })).toBeVisible();
  await page.getByLabel("Vorname").fill(firstName);
  await page.getByLabel("Nachname").fill(lastName);
  if (email) await page.getByLabel("E-Mail-Adresse").fill(email);
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByRole("heading", { name: `${firstName} ${lastName}` })).toBeVisible();
  if (pin) {
    await page.getByRole("link", { name: "PIN setzen", exact: true }).click();
    await page.getByLabel("Neue PIN").fill(pin);
    await page.getByRole("button", { name: "Speichern", exact: true }).click();
    await expect(page.getByRole("heading", { name: `${firstName} ${lastName}` })).toBeVisible();
  }
}

test("Admin completes setup, login, camp workflow and logout", async ({ page }) => {
  await setupFirstAdmin(page);
  await createCamp(page);

  await expect(page.getByRole("link", { name: "Teilnehmer anlegen" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Preise verwalten" }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Auslage erfassen" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Teilnehmer importieren" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Abrechnung als CSV herunterladen" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Arbeitsmappe herunterladen", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Getränke als CSV herunterladen" })).toBeVisible();
  await expect(page.locator(".participant-settlements").getByRole("table")).toBeVisible();
  await expect(page.getByRole("link", { name: "Dienste verwalten" })).toHaveCount(0);

  await page.setViewportSize({ width: 390, height: 844 });
  const settlementLayout = await page.locator(".participant-settlements").evaluate((panel) => {
    const table = panel.querySelector("table");
    return {
      panelClientWidth: panel.clientWidth,
      panelScrollWidth: panel.scrollWidth,
      tableClientWidth: table.clientWidth,
      tableScrollWidth: table.scrollWidth,
    };
  });
  expect(settlementLayout.panelScrollWidth).toBeLessThanOrEqual(settlementLayout.panelClientWidth + 1);
  expect(settlementLayout.tableScrollWidth).toBeGreaterThan(settlementLayout.tableClientWidth);
  await assertNoUnexpectedOverflow(page);
  await logout(page);
  await expect(page).toHaveURL(/\/login\/?$/);
  await loginAsAdmin(page);
});

test("Admin configures and centrally revokes every camp kiosk access", async ({ page }) => {
  await setupFirstAdmin(page);
  const campName = await createCamp(page, "Lagerzugang");
  await logout(page);

  await page.goto("/kiosk/login/");
  await expect(page).toHaveURL(/\/kiosk\/access\/\?next=/);
  await expect(page.getByRole("heading", { name: "Lager-PIN eingeben" })).toBeVisible();
  await expect(page.getByLabel("Teilnehmer")).toHaveCount(0);
  await expect(page.locator("[data-pwa-install]")).toHaveCount(0);

  await page.getByLabel("Lager-PIN").fill("000000");
  await page.getByRole("button", { name: "Weiter" }).click();
  await expect(page.getByText("Lager-PIN ist ungültig.")).toBeVisible();
  await page.getByLabel("Lager-PIN").fill(KIOSK_ACCESS_PIN);
  await page.getByRole("button", { name: "Weiter" }).click();
  await expect(page).toHaveURL(/\/kiosk\/login\/$/);

  const accessCookie = (await page.context().cookies()).find(
    (cookie) => cookie.name === "fliegerlager_kiosk_access",
  );
  expect(accessCookie).toBeDefined();
  expect(accessCookie.httpOnly).toBe(true);
  expect(accessCookie.sameSite).toBe("Lax");
  expect(accessCookie.expires).toBeGreaterThan(Date.now() / 1000 + 29 * 24 * 60 * 60);

  await page.goto("/kiosk/access/");
  await expect(page).toHaveURL(/\/kiosk\/login\/$/);

  await loginAsAdmin(page);
  await page.getByRole("link", { name: campName, exact: true }).click();
  await page.getByRole("link", { name: "Lager-PIN verwalten" }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Alle Lagerzugänge widerrufen" }).click();
  await expect(page.getByText("Alle bestehenden Lagerzugänge wurden zentral widerrufen.")).toBeVisible();

  await page.goto("/kiosk/login/");
  await expect(page).toHaveURL(/\/kiosk\/access\/\?next=/);
  await expect(page.getByRole("heading", { name: "Lager-PIN eingeben" })).toBeVisible();
});

test("Pre-camp kiosk stays compact and exposes only preparation areas", async ({ page }) => {
  await setupFirstAdmin(page);
  await createCamp(page, "Vorlager", 2, 4);
  await createParticipant(page, "Ada", "Lovelace", "", "1234");
  await logout(page);

  await openKiosk(page, "/kiosk/login/");
  const countdown = page.locator("[data-pre-camp-countdown]");
  const loginShell = page.locator(".kiosk-login-shell--pre-camp");
  await expect(countdown).toBeVisible();
  await expect(loginShell).toBeVisible();
  const loginSpacing = await page.evaluate(() => {
    const countdownRect = document.querySelector("[data-pre-camp-countdown]").getBoundingClientRect();
    const loginRect = document.querySelector(".kiosk-login-shell--pre-camp").getBoundingClientRect();
    return loginRect.top - countdownRect.bottom;
  });
  expect(loginSpacing).toBeLessThanOrEqual(32);

  await page.getByLabel("Teilnehmer").selectOption({ label: "Ada Lovelace" });
  await page.getByLabel("PIN:", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();

  await expect(page.locator("[data-pre-camp-overview]")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Ada Lovelace" })).toBeVisible();
  await expect(page.locator("[data-kiosk-card]")).toHaveCount(0);
  await page.getByRole("button", { name: /Weitere Bereiche öffnen/ }).or(page.locator(".kiosk-mobile-bottom-nav").getByRole("link", { name: "Mehr" })).click();
  const menu = page.locator("dialog#kiosk-menu-dialog");
  await expect(menu.getByRole("button", { name: /Familie/ })).toBeVisible();
  await expect(menu.getByRole("link", { name: /Partner & Aktivitäten/ })).toBeVisible();
  await expect(menu.getByRole("link", { name: /Hilfe/ })).toBeVisible();
  await expect(menu.getByRole("button", { name: /Kontakt Lagerleitung/ })).toBeVisible();
  await expect(menu.getByRole("button", { name: /Abendessen|Gemeinschaftsausgaben/ })).toHaveCount(0);
  await page.keyboard.press("Escape");

  for (const viewport of [
    { width: 1280, height: 800 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await assertNoUnexpectedOverflow(page);
  }
});

test("Admin registers and signs in with a passkey", async ({ context, page }) => {
  const { browserErrors, failedRequests } = trackPageIssues(page);
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

test("Admin creates and edits a manual booking and sees the change log", async ({ page }) => {
  const correctedDescription =
    "Cola korrigiert mit ausführlicher Sonderkostbeschreibung und zusätzlicher Dokumentation für das Änderungsprotokoll";
  const { browserErrors, failedRequests } = trackPageIssues(page);
  await setupFirstAdmin(page);
  await createCamp(page);

  await page.getByRole("link", { name: "Preise verwalten" }).first().click();
  await page.getByRole("button", { name: "Getränk anlegen" }).click();
  const priceDialog = page.locator("dialog#price-rule-dialog");
  await priceDialog.getByLabel("Name / Bezeichnung").fill("Cola");
  await priceDialog.getByLabel("Einzelpreis (EUR)").fill("2.50");
  await priceDialog.getByRole("button", { name: "Speichern", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Preisregel wurde gespeichert.");
  await page.getByRole("link", { name: "Zurück zum Lager" }).click();
  await createParticipant(page, "Ada", "Lovelace");

  const openButton = page.getByRole("button", { name: "Buchung hinzufügen" });
  await openButton.click();

  const manualChargeDialog = page.getByRole("dialog", { name: "Manuelle Buchung" });
  await expect(manualChargeDialog).toBeVisible();
  await expect(manualChargeDialog.getByLabel("Preisregel auswählen")).toBeVisible();
  await expect(manualChargeDialog.getByLabel("Menge")).toHaveValue("1");
  await expect(manualChargeDialog.getByLabel("Notiz (optional)")).toBeVisible();
  expect(await manualChargeDialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await assertNoUnexpectedOverflow(page);
  await page.keyboard.press("Escape");
  await expect(manualChargeDialog).toBeHidden();
  await expect(openButton).toBeFocused();

  await page.setViewportSize({ width: 390, height: 844 });
  await openButton.click();
  const dialogBounds = await manualChargeDialog.boundingBox();
  expect(dialogBounds).not.toBeNull();
  expect(dialogBounds.x).toBeGreaterThanOrEqual(0);
  expect(dialogBounds.y).toBeGreaterThanOrEqual(0);
  expect(dialogBounds.x + dialogBounds.width).toBeLessThanOrEqual(391);
  expect(dialogBounds.y + dialogBounds.height).toBeLessThanOrEqual(845);

  await page.keyboard.press("Escape");
  await expect(manualChargeDialog).toBeHidden();
  await expect(openButton).toBeFocused();

  await page.getByRole("switch", { name: "Dunkles Farbschema" }).click();
  await openButton.click();
  await assertReadableContrast(manualChargeDialog);
  await assertNoUnexpectedOverflow(page);
  await manualChargeDialog.getByLabel("Preisregel auswählen").selectOption({ label: "Cola (2,50 €)" });
  const quantityInput = manualChargeDialog.getByLabel("Menge");
  await quantityInput.evaluate((element) => element.removeAttribute("min"));
  await quantityInput.fill("0");
  await manualChargeDialog.getByRole("button", { name: "Buchen", exact: true }).click();

  await expect(manualChargeDialog).toBeVisible();
  expect(await manualChargeDialog.evaluate((element) => element.matches(":modal"))).toBe(true);
  await expect(manualChargeDialog.getByRole("alert")).toContainText("1");
  await expect(quantityInput).toBeFocused();

  await quantityInput.fill("2");
  await manualChargeDialog.getByLabel("Notiz (optional)").fill("Cola");
  await manualChargeDialog.getByRole("button", { name: "Buchen", exact: true }).click();

  await expect(page.getByRole("heading", { name: "Ada Lovelace" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Buchung 'Cola' hinzugefügt.");
  await expect(page.getByRole("heading", { name: "Buchungen", exact: true })).toBeVisible();
  const bookings = page.locator("section.panel").filter({
    has: page.getByRole("heading", { name: "Buchungen", exact: true }),
  });
  const bookingRow = bookings.getByRole("row").filter({
    has: page.getByRole("cell", { name: /Cola$/ }),
  });
  await expect(bookingRow.getByRole("cell", { name: /B#\d{5}$/ })).toBeVisible();
  await expect(bookingRow.getByRole("cell", { name: /Getränke$/ })).toBeVisible();
  await expect(bookingRow.getByRole("cell", { name: /2,00$/ })).toBeVisible();
  await expect(bookingRow.getByRole("cell", { name: /2,50 €$/ })).toBeVisible();
  await expect(bookingRow.getByRole("cell", { name: /5,00 €$/ })).toBeVisible();
  await bookingRow.getByRole("link", { name: "Bearbeiten", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Buchung bearbeiten" })).toBeVisible();
  await page.getByLabel("Beschreibung").fill(correctedDescription);
  await page.getByLabel("Menge").fill("3");
  await page.getByLabel("Datum").fill("2026-07-01");
  await page.getByRole("button", { name: "Speichern" }).click();

  await page.setViewportSize({ width: 1280, height: 800 });
  await expect(page.getByRole("heading", { name: "Ada Lovelace" })).toBeVisible();
  await expect(page.getByText("Buchung wurde gespeichert und protokolliert.")).toBeVisible();
  await expect(page.getByRole("cell", { name: correctedDescription }).first()).toBeVisible();
  await expect(page.getByRole("cell", { name: "7,50 €" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Änderungsprotokoll" })).toBeVisible();
  await expect(page.getByText("Cola · 2.00 x 2.50")).toBeVisible();
  await expect(page.getByText(`${correctedDescription} · 3.00 x 2.50`)).toBeVisible();
  const auditPanel = page.locator("section.panel").filter({
    has: page.getByRole("heading", { name: "Änderungsprotokoll" }),
  });
  const auditLayout = await auditPanel.evaluate((panel) => ({
    clientWidth: panel.clientWidth,
    scrollWidth: panel.scrollWidth,
  }));
  const bookingLayout = await bookings.evaluate((panel) => ({
    clientWidth: panel.clientWidth,
    scrollWidth: panel.scrollWidth,
  }));
  expect(bookingLayout.scrollWidth).toBeLessThanOrEqual(bookingLayout.clientWidth + 1);
  expect(auditLayout.scrollWidth).toBeLessThanOrEqual(auditLayout.clientWidth + 1);
  expect(browserErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});

test("PWA PDF preview opens in a closable wrapper without leaving the app", async ({ page }) => {
  const { browserErrors, failedRequests } = trackPageIssues(page);
  await setupFirstAdmin(page);
  await createCamp(page, "PDF Vorschau");
  await createParticipant(page, "Ada", "Lovelace");

  await page.setViewportSize({ width: 390, height: 844 });
  const previewLink = page.getByRole("link", { name: "Einzelabrechnung als PDF öffnen" });
  const participantUrl = page.url();
  const pdfResponsePromise = page.waitForResponse((response) => response.url().endsWith("/export/settlement.pdf"));
  await previewLink.click();

  const pdfResponse = await pdfResponsePromise;
  expect(pdfResponse.headers()["x-frame-options"]).toBe("SAMEORIGIN");
  expect(pdfResponse.headers()["content-security-policy"]).toContain("frame-ancestors 'self'");
  const previewDialog = page.locator("#global-pdf-dialog");
  await expect(page.getByRole("dialog", { name: "PDF-Vorschau" })).toBeVisible();
  await expect(previewDialog).toBeVisible();
  const dialogBounds = await previewDialog.boundingBox();
  expect(dialogBounds).not.toBeNull();
  expect(dialogBounds.x).toBeGreaterThanOrEqual(0);
  expect(dialogBounds.y).toBeGreaterThanOrEqual(0);
  expect(dialogBounds.x + dialogBounds.width).toBeLessThanOrEqual(391);
  expect(dialogBounds.y + dialogBounds.height).toBeLessThanOrEqual(845);
  await expect(previewDialog.locator("iframe")).toHaveAttribute("src", /\/export\/settlement\.pdf$/);
  await expect(page).toHaveURL(participantUrl);
  expect(browserErrors).toEqual([]);

  await previewDialog.getByRole("button", { name: "Schließen" }).click();
  await expect(previewDialog).toBeHidden();
  await expect(previewLink).toBeFocused();
  await expect(previewDialog.locator("iframe")).toHaveAttribute("src", "about:blank");
  await expect(page.locator("#global-receipt-dialog")).toBeHidden();
  expect(browserErrors).toEqual([]);
  expect(
    failedRequests.filter(
      (failure) =>
        !failure.includes("/export/settlement.pdf") ||
        (!failure.includes("ERR_ABORTED") && !failure.includes("Frame load interrupted")),
    ),
    "Nur das absichtliche Abbrechen der entfernten PDF-Vorschau ist zulässig",
  ).toEqual([]);
});

test("expense image receipts open in an accessible internal preview", async ({ page }) => {
  const { browserErrors, failedRequests } = trackPageIssues(page);
  await setupFirstAdmin(page);
  await createCamp(page, "Bildbeleg Vorschau");
  const campUrl = page.url();
  await createParticipant(page, "Ada", "Lovelace");

  await page.goto(campUrl);
  await page.getByRole("link", { name: "Auslage erfassen" }).click();
  await page.getByLabel("Teilnehmer").selectOption({ label: "Ada Lovelace" });
  await page.locator("#id_category").selectOption({ label: "Verbrauchsmaterial" });
  await page.getByLabel("Beschreibung").fill("Küche PNG");
  await page.getByLabel("Betrag").fill("12.50");
  await page.locator('input[type="file"]').setInputFiles({
    name: "kueche.png",
    mimeType: "image/png",
    buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64"),
  });
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByText("Auslage wurde gespeichert.")).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  const previewLink = page.locator('a[data-receipt-preview="image"]');
  await expect(previewLink).toHaveAttribute("data-receipt-alt", "Küche PNG");
  const pageUrl = page.url();
  await previewLink.click();

  const dialog = page.getByRole("dialog", { name: "Belegvorschau" });
  await expect(dialog).toBeVisible();
  await expect(dialog.locator("img")).toHaveAttribute("alt", "Küche PNG");
  await expect(dialog.locator("img")).toBeVisible();
  await expect(page).toHaveURL(pageUrl);
  const bounds = await dialog.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.y).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(391);
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(845);
  const imageLayout = await dialog.evaluate((element) => {
    const image = element.querySelector("img");
    return {
      dialogClientWidth: element.clientWidth,
      dialogScrollWidth: element.scrollWidth,
      imageRight: image.getBoundingClientRect().right,
      contentRight: element.getBoundingClientRect().right,
    };
  });
  expect(imageLayout.dialogScrollWidth).toBeLessThanOrEqual(imageLayout.dialogClientWidth + 1);
  expect(imageLayout.imageRight).toBeLessThanOrEqual(imageLayout.contentRight + 1);

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(previewLink).toBeFocused();

  await previewLink.click();
  await dialog.evaluate((element) => element.dispatchEvent(new MouseEvent("click", { bubbles: true })));
  await expect(dialog).toBeHidden();
  await expect(previewLink).toBeFocused();

  const modifiedClick = await previewLink.evaluate((link) => {
    const event = new MouseEvent("click", { bubbles: true, cancelable: true, button: 1 });
    link.dispatchEvent(event);
    return { defaultPrevented: event.defaultPrevented, href: link.href, target: link.target };
  });
  expect(modifiedClick.defaultPrevented).toBe(false);
  expect(modifiedClick.target).toBe("_blank");
  expect(modifiedClick.href).toMatch(/\/expenses\/\d+\/receipt\/$/);
  await expect(dialog).toBeHidden();
  expect(browserErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});

test("expense PDF receipts allow only same-origin internal preview framing", async ({ page }) => {
  const { browserErrors, failedRequests } = trackPageIssues(page);
  await setupFirstAdmin(page);
  await createCamp(page, "PDF-Beleg Vorschau");
  const campUrl = page.url();
  await createParticipant(page, "Ada", "Lovelace");

  await page.goto(campUrl);
  await page.getByRole("link", { name: "Auslage erfassen" }).click();
  await page.getByLabel("Teilnehmer").selectOption({ label: "Ada Lovelace" });
  await page.locator("#id_category").selectOption({ label: "Verbrauchsmaterial" });
  await page.getByLabel("Beschreibung").fill("Küche PDF");
  await page.getByLabel("Betrag").fill("12.50");
  await page.locator('input[type="file"]').setInputFiles({
    name: "kueche.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4\nreceipt preview\n"),
  });
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByText("Auslage wurde gespeichert.")).toBeVisible();

  const previewLink = page.locator('a[data-pdf-preview="true"]').filter({ hasText: "Beleg ansehen" });
  const pdfResponsePromise = page.waitForResponse((response) => /\/expenses\/\d+\/receipt\/$/.test(response.url()));
  await previewLink.click();

  const pdfResponse = await pdfResponsePromise;
  expect(pdfResponse.headers()["x-frame-options"]).toBe("SAMEORIGIN");
  expect(pdfResponse.headers()["content-security-policy"]).toBe("default-src 'none'; frame-ancestors 'self'");
  const previewDialog = page.getByRole("dialog", { name: "PDF-Vorschau" });
  await expect(previewDialog).toBeVisible();
  await expect(previewDialog.locator("iframe")).toHaveAttribute("src", /\/expenses\/\d+\/receipt\/$/);

  await previewDialog.getByRole("button", { name: "Schließen" }).click();
  await expect(previewDialog).toBeHidden();
  await expect(previewLink).toBeFocused();
  expect(browserErrors).toEqual([]);
  expect(
    failedRequests.filter(
      (failure) =>
        !failure.includes("/expenses/") ||
        (!failure.includes("ERR_ABORTED") && !failure.includes("Frame load interrupted")),
    ),
  ).toEqual([]);
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

async function setupKioskScenario(page, name = "Sommerlager Kiosk") {
  await setupFirstAdmin(page);
  const campName = await createCamp(page, name, 0, 4);
  await createParticipant(page, "Marie", "Curie", "", "1234");

  await page.getByRole("link", { name: "Fliegerlager-Abrechnung" }).click();
  await page.getByRole("link", { name: campName, exact: true }).click();
  await page.getByRole("link", { name: "Preise verwalten" }).first().click();
  await page.getByRole("button", { name: "Getränk anlegen" }).click();
  await page.locator("#price-rule-dialog").getByLabel("Name").fill("Apfelsaft");
  await page.locator("#price-rule-dialog").getByLabel("Einzelpreis").fill("1.50");
  await page.locator("#price-rule-dialog").getByRole("button", { name: "Speichern" }).click();
  await page.locator('input[name="meal-breakfast_adult_price"]').fill("5.00");
  await page.locator('input[name="meal-dinner_adult_price"]').fill("7.00");
  await page.getByRole("button", { name: "Standardpreise speichern" }).click();
  await logout(page);
  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Marie Curie" });
  await page.getByLabel("PIN:", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).toHaveURL(/\/kiosk\/$/);
  return campName;
}

async function expectOnlyModal(page, dialogId) {
  await expect.poll(() => page.locator("dialog:modal").evaluateAll((dialogs) => dialogs.map((dialog) => dialog.id))).toEqual([dialogId]);
}

async function expectButtonHitTestable(button) {
  await expect.poll(() => button.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const hitTarget = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    return hitTarget === element || element.contains(hitTarget);
  })).toBe(true);
}

async function waitForKioskDialogReady(page, dialog, dialogId, actionableControl) {
  await expectOnlyModal(page, dialogId);
  // kioskDialogs first waits for the previous native modal to tear down and
  // then moves focus into the replacement on the following animation frame.
  await dialog.evaluate((element) => new Promise((resolve) => {
    window.requestAnimationFrame(() => window.requestAnimationFrame(resolve));
  }));
  await expect.poll(() => dialog.evaluate((element) => ({
    isModal: element.matches(":modal"),
    containsFocus: element.contains(document.activeElement),
  }))).toEqual({ isModal: true, containsFocus: true });
  if (actionableControl) {
    await expectButtonHitTestable(actionableControl);
  }
}

async function submitKioskDialogAndExpectRedirect(page, dialog, dialogId, button, action, location) {
  await waitForKioskDialogReady(page, dialog, dialogId);
  const responsePromise = page.waitForResponse((response) => {
    const request = response.request();
    return (
      request.method() === "POST" &&
      new URL(response.url()).pathname === "/kiosk/" &&
      request.postData()?.includes(`action=${action}`)
    );
  });
  await expectButtonHitTestable(button);
  const [response] = await Promise.all([responsePromise, button.click()]);
  expect(response.status()).toBe(302);
  expect(response.headers().location).toBe(location);
}

async function createKioskFamilyMember(page, firstName = "Irène", lastName = "Curie") {
  const openKioskMenu = page
    .getByRole("button", { name: /Weitere Bereiche öffnen/ })
    .or(page.locator(".kiosk-mobile-bottom-nav").getByRole("link", { name: "Mehr" }));
  await expectButtonHitTestable(openKioskMenu);
  await openKioskMenu.click();

  const kioskMenu = page.locator("dialog#kiosk-menu-dialog");
  await waitForKioskDialogReady(page, kioskMenu, "kiosk-menu-dialog");
  const familyMenuButton = kioskMenu.getByRole("button", { name: /Familie/ });
  await expectButtonHitTestable(familyMenuButton);
  await familyMenuButton.click();

  const familyManagementDialog = page.locator("dialog#family-management-dialog");
  await waitForKioskDialogReady(page, familyManagementDialog, "family-management-dialog");
  const openFamilyDialogButton = familyManagementDialog.getByRole("button", { name: "Anlegen" });
  await expectButtonHitTestable(openFamilyDialogButton);
  await openFamilyDialogButton.click();

  const familyDialog = page.locator("dialog#family-dialog");
  await waitForKioskDialogReady(page, familyDialog, "family-dialog");
  await familyDialog.getByLabel("Vorname").fill(firstName);
  await familyDialog.getByLabel("Nachname").fill(lastName);
  await familyDialog.getByLabel("Rolle").selectOption({ label: "Kind" });

  await submitKioskDialogAndExpectRedirect(
    page,
    familyDialog,
    "family-dialog",
    familyDialog.getByRole("button", { name: "Speichern" }),
    "family_member_create",
    "/kiosk/",
  );
  await expect(page.getByText("Familienmitglied wurde angelegt.")).toBeVisible();
}

test("Kiosk login and basic booking", async ({ page }) => {
  await setupKioskScenario(page, "Kiosk Login Grundbuchung");

  // Now in Kiosk Home
  await expect(page).toHaveURL(/.*\/kiosk\//);
  const sessionCookie = (await page.context().cookies()).find((cookie) => cookie.name === "sessionid");
  expect(sessionCookie).toBeDefined();
  expect(sessionCookie.expires).toBeGreaterThan(Date.now() / 1000);

  // Check-in can be entered from the kiosk.
  const checkinArrival = dateInputValue(addDays(new Date(), 2));
  const checkinDeparture = dateInputValue(addDays(new Date(), 4));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Eintragen" }).click();
  const checkinDialog = page.locator("dialog#checkin-dialog");
  await expect(checkinDialog).toBeVisible();
  const nestedVerticalScrollContainers = await checkinDialog.evaluate((dialog) =>
    [...dialog.querySelectorAll("*")]
      .filter((element) => ["auto", "scroll"].includes(getComputedStyle(element).overflowY))
      .map((element) => element.className),
  );
  expect(nestedVerticalScrollContainers).toEqual([]);
  const departureInput = checkinDialog.getByLabel("Abreise").first();
  const newlyIncludedAttendance = checkinDialog.getByLabel(
    `Marie Curie am ${germanDate(addDays(new Date(), 2))} anwesend`,
  );
  await expect(newlyIncludedAttendance).toBeDisabled();
  await departureInput.fill(dateInputValue(addDays(new Date(), 5)));
  await checkinDialog.getByLabel("Anreise").fill(checkinArrival);
  await departureInput.fill(checkinDeparture);
  await expect(newlyIncludedAttendance).toBeEnabled();
  await expect(newlyIncludedAttendance).toBeChecked();
  await checkinDialog.getByRole("button", { name: "Check-in speichern" }).click();
  await expect(page.getByText("Check-in-Daten wurden gespeichert.")).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.getByRole("button", { name: "Eintragen" }).click();
  await expect(page.locator("dialog#checkin-dialog").getByLabel("Anreise")).toHaveValue(checkinArrival);
  await expect(page.locator("dialog#checkin-dialog").getByLabel("Abreise")).toHaveValue(checkinDeparture);
  await page.keyboard.press("Escape");
  await expectModalDialogIds(page, []);

  // Breakfast is a same-day quick booking and skips the meal calendar.
  await page.locator("[data-food-button]").first().click();
  await expect(page.locator("dialog#food-dialog")).toBeVisible();
  await expect(page.locator("#food-step-date")).toHaveCount(0);
  await expect(page.locator("dialog#food-dialog").getByText("Wer soll eingebucht werden?")).toBeVisible();
  await page.locator("dialog#food-dialog").getByRole("button", { name: "Jetzt buchen" }).click();
  await expect(page.getByText(/Standard Frühstück.*gebucht\./)).toBeVisible();

});

test("Kiosk quick booking validates targets and supports cancellation", async ({ page }) => {
  await setupKioskScenario(page, "Kiosk Schnellbuchung");
  await createKioskFamilyMember(page);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.getByRole("button", { name: "Apfelsaft" }).click();
  const quickDialog = page.locator("dialog#quick-dialog");
  await expect(quickDialog).toBeVisible();
  const quickTargets = quickDialog.locator('[data-quick-target-scope="drink"]');
  await quickTargets.first().uncheck();
  await quickDialog.getByRole("button", { name: "1x" }).click();
  await expect(quickDialog).toBeVisible();
  await expect(quickDialog.getByRole("alert")).toHaveText("Bitte mindestens eine Person auswählen.");
  await quickTargets.first().check();
  await quickTargets.nth(1).check();
  await quickDialog.getByRole("button", { name: "1x" }).click();
  const quickConfirmationDialog = page.locator("dialog#quick-confirmation-dialog");
  await expect(quickConfirmationDialog).toBeVisible();
  await expect(quickConfirmationDialog).toContainText("Marie Curie");
  await expect(quickConfirmationDialog).toContainText("Irène Curie");
  await expect(quickConfirmationDialog).toContainText("3,00 €");
  await assertNoUnexpectedOverflow(page);
  await quickConfirmationDialog.getByRole("button", { name: "Jetzt kostenpflichtig buchen" }).click();
  await expect(page.getByText("Apfelsaft gebucht.")).toBeVisible();
  await page.emulateMedia({ colorScheme: "light" });
  await assertNoUnexpectedOverflow(page);
  await page.getByRole("button", { name: /Weitere Bereiche öffnen/ }).or(page.locator(".kiosk-mobile-bottom-nav").getByRole("link", { name: "Mehr" })).click();
  await page.getByRole("button", { name: "Letzte Schnellbuchungen" }).click();
  await expect(page.locator("dialog:open")).toHaveCount(1);
  await page.locator("dialog#quick-bookings-dialog [data-open-quick-cancel-dialog]").first().click();
  await expect(page.locator("dialog#quick-cancel-dialog")).toBeVisible();
  await expect(page.locator("dialog:open")).toHaveCount(1);
  await expect(page.locator("dialog#quick-cancel-dialog")).toContainText("Apfelsaft");
  await page.locator("dialog#quick-cancel-dialog").getByRole("button", { name: "Jetzt stornieren" }).click();
  await expect(page.getByText("Buchung wurde storniert.")).toBeVisible();
});

test("Kiosk meal calendar saves multiple dinner dates", async ({ page }) => {
  await setupKioskScenario(page, "Kiosk Essenskalender");
  await page.locator('[data-kiosk-card="food"]').getByRole("button", { name: /Abendessen/ }).click();
  await page.locator("dialog#meal-calendar-dialog").getByRole("button", { name: "Essen buchen" }).click();
  await expect(page.locator("dialog#meal-dialog")).toBeVisible();
  const mealDateChoices = page.locator("dialog#meal-dialog input[data-meal-date-checkbox]:not([disabled])");
  await mealDateChoices.nth(0).check();
  await mealDateChoices.nth(1).check();
  await page.locator("dialog#meal-dialog").getByRole("button", { name: "Weiter" }).click();
  await expect(page.locator("#meal-selected-date")).toContainText("2 Tage ausgewählt");
  await page.locator("dialog#meal-dialog").getByRole("button", { name: "Essensanmeldung speichern" }).click();
  await expect(page.getByText("Essensanmeldung wurde für 2 Tage und 1 Person gespeichert.")).toBeVisible();
  await expect(page).toHaveURL(/.*\/kiosk\/$/);
  await expect(page.locator("dialog#meal-calendar-dialog")).toBeVisible();
  await page.locator("dialog#meal-calendar-dialog").getByRole("button", { name: "Essen buchen" }).click();
  await expect(page.locator("dialog#meal-dialog").getByText("Gebucht für Marie Curie").first()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("dialog#meal-calendar-dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expectModalDialogIds(page, []);
});

test("Breakfast food dialog opens the prebooking calendar", async ({ page }) => {
  await setupKioskScenario(page, "Kiosk Frühstück Dialog Vorwärts");
  await page.locator('[data-kiosk-card="food"] [data-food-button][data-meal-type="breakfast"]').click();
  const breakfastQuickDialog = page.locator("dialog#food-dialog");
  await expectOnlyModal(page, "food-dialog");
  await expect(breakfastQuickDialog.getByRole("button", { name: "Jetzt buchen" })).toBeVisible();
  const breakfastTarget = breakfastQuickDialog.locator('[data-quick-target-scope="food"]').first();
  const breakfastPrebookButton = breakfastQuickDialog.getByRole("button", { name: "Für später vorbestellen" });
  await breakfastTarget.uncheck();
  await expectButtonHitTestable(breakfastPrebookButton);
  await breakfastPrebookButton.click();
  await expect(breakfastQuickDialog.getByRole("alert")).toHaveText("Bitte mindestens eine Person auswählen.");
  await breakfastTarget.check();
  await expectButtonHitTestable(breakfastPrebookButton);
  await breakfastPrebookButton.click();
  const breakfastCalendar = page.locator("dialog#breakfast-meal-dialog");
  await expect(breakfastCalendar).toBeVisible();
  await expectModalDialogIds(page, ["breakfast-meal-dialog"]);
  await expect(page.locator("dialog:open")).toHaveCount(1);
  await expectOnlyModal(page, "breakfast-meal-dialog");
  await expect(breakfastQuickDialog).toBeHidden();
  await expect(breakfastCalendar.locator("#breakfast-booking-target-names-dialog")).toContainText("Marie Curie");
});

test("Breakfast calendar returns to the food dialog", async ({ page }) => {
  await setupKioskScenario(page, "Kiosk Frühstück Dialog Rückweg");
  await page.locator('[data-kiosk-card="food"] [data-food-button][data-meal-type="breakfast"]').click();
  const breakfastQuickDialog = page.locator("dialog#food-dialog");
  const breakfastPrebookButton = breakfastQuickDialog.getByRole("button", { name: "Für später vorbestellen" });
  await breakfastPrebookButton.click();
  const breakfastCalendar = page.locator("dialog#breakfast-meal-dialog");
  await expect(breakfastCalendar).toBeVisible();
  await breakfastCalendar.getByRole("button", { name: "Ändern" }).click();
  await expect(breakfastQuickDialog).toBeVisible();
  await expect(page.locator("dialog:open")).toHaveCount(1);
  await expectOnlyModal(page, "food-dialog");
  await expect(breakfastCalendar).toBeHidden();
  await expectButtonHitTestable(breakfastPrebookButton);
  await breakfastPrebookButton.click();
  await expect(breakfastCalendar).toBeVisible();
  await expectModalDialogIds(page, ["breakfast-meal-dialog"]);
  await expect(page.locator("dialog:open")).toHaveCount(1);
  await expectOnlyModal(page, "breakfast-meal-dialog");
  await expect(breakfastQuickDialog).toBeHidden();
});

test("Closing breakfast dialogs releases scroll lock", async ({ page }) => {
  await setupKioskScenario(page, "Kiosk Frühstück Dialog Schließen");
  await page.locator('[data-kiosk-card="food"] [data-food-button][data-meal-type="breakfast"]').click();
  const breakfastQuickDialog = page.locator("dialog#food-dialog");
  await breakfastQuickDialog.getByRole("button", { name: "Für später vorbestellen" }).click();
  const breakfastCalendar = page.locator("dialog#breakfast-meal-dialog");
  await expect(breakfastCalendar).toBeVisible();
  await expectOnlyModal(page, "breakfast-meal-dialog");
  await breakfastCalendar.getByRole("button", { name: "Schließen" }).click();
  await expect(breakfastCalendar).toBeHidden();
  await expect.poll(() => page.locator("dialog:open").evaluateAll((dialogs) => dialogs.map((dialog) => dialog.id))).toEqual(["food-dialog"]);
  await breakfastQuickDialog.getByRole("button", { name: "Schließen" }).click();
  await expectModalDialogIds(page, []);
  await expect.poll(() => page.locator("dialog:open").evaluateAll((dialogs) => dialogs.map((dialog) => dialog.id))).toEqual([]);
  await expect.poll(() => page.evaluate(() => ({
    scrollLockClass: document.documentElement.classList.contains("dialog-scroll-lock"),
    bodyPosition: document.body.style.position,
  }))).toEqual({ scrollLockClass: false, bodyPosition: "" });
});

test("Breakfast prebooking saves a selected date", async ({ page }) => {
  await setupKioskScenario(page, "Kiosk Frühstück Vorbestellung");
  await page.locator('[data-kiosk-card="food"] [data-food-button][data-meal-type="breakfast"]').click();
  const breakfastQuickDialog = page.locator("dialog#food-dialog");
  await breakfastQuickDialog.getByRole("button", { name: "Für später vorbestellen" }).click();
  const breakfastCalendar = page.locator("dialog#breakfast-meal-dialog");
  await breakfastCalendar.locator("input[data-breakfast-meal-date-checkbox]:not([disabled])").first().check();
  await breakfastCalendar.getByRole("button", { name: "Frühstücksvorbestellung speichern" }).click();
  await expect(page.getByText(/Essensanmeldung wurde für 1 Tag und 1 Person gespeichert\./)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("dialog#meal-calendar-dialog")).toBeHidden();
  await expectModalDialogIds(page, []);
});

test("Kiosk can book a drink after breakfast prebooking", async ({ page }) => {
  const campName = await setupKioskScenario(page, "Kiosk Nachgelagerte Getränke");
  await createKioskFamilyMember(page);
  await page.locator('[data-kiosk-card="food"] [data-food-button][data-meal-type="breakfast"]').click();
  await page.locator("dialog#food-dialog").getByRole("button", { name: "Für später vorbestellen" }).click();
  const breakfastCalendar = page.locator("dialog#breakfast-meal-dialog");
  await breakfastCalendar.locator("input[data-breakfast-meal-date-checkbox]:not([disabled])").first().check();
  await breakfastCalendar.getByRole("button", { name: "Frühstücksvorbestellung speichern" }).click();
  await expect(page.getByText(/Essensanmeldung wurde für 1 Tag und 1 Person gespeichert\./)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("dialog#meal-calendar-dialog")).toBeHidden();
  await expectModalDialogIds(page, []);
  await page.getByRole("button", { name: "Apfelsaft" }).click();
  await page.locator("dialog#quick-dialog").getByRole("button", { name: "1x" }).click();
  await expect(page.getByText("Apfelsaft gebucht.")).toBeVisible();
  await expect(page.locator("dialog#meal-calendar-dialog")).toBeHidden();
  await page.getByRole("link", { name: "Abmelden" }).first().click();
  await expect(page).toHaveURL(/.*\/kiosk\/login\//);
  await loginAsAdmin(page);
  await page.getByRole("link", { name: campName, exact: true }).click();
  await page.getByRole("link", { name: "Marie Curie", exact: true }).last().click();
  await expect(page.getByRole("heading", { name: "Marie Curie" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Familienmitglieder", exact: true })).toBeVisible();
  const familyMembersSection = page
    .getByRole("heading", { name: "Familienmitglieder", exact: true })
    .locator("xpath=ancestor::section[1]");
  await expect(familyMembersSection.getByRole("cell", { name: "Irène Curie", exact: true })).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 800 });
  await assertNoUnexpectedOverflow(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoUnexpectedOverflow(page);
});

test("Kiosk user can change their own PIN and log in with the new PIN", async ({ page }) => {
  await setupFirstAdmin(page);
  await createCamp(page, "PIN-Selbstverwaltung", 0, 4);
  await createParticipant(page, "Marie", "Curie", "", "2468");
  await logout(page);

  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Marie Curie" });
  await page.getByLabel("PIN:", { exact: true }).fill("2468");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();

  const kioskMenuButton = page.getByRole("button", { name: "Weitere Bereiche öffnen" });
  await expectButtonHitTestable(kioskMenuButton);
  await kioskMenuButton.click();
  const kioskMenu = page.locator("dialog#kiosk-menu-dialog");
  await waitForKioskDialogReady(page, kioskMenu, "kiosk-menu-dialog");
  const pinChangeButton = kioskMenu.getByRole("button", { name: "Eigene PIN ändern" });
  await pinChangeButton.click();
  const pinDialog = page.locator("dialog#pin-change-dialog");
  const submitPinChange = pinDialog.getByRole("button", { name: "PIN ändern" });
  await waitForKioskDialogReady(page, pinDialog, "pin-change-dialog", submitPinChange);
  await pinDialog.getByLabel("Aktuelle PIN").fill("2468");
  await pinDialog.getByLabel("Neue PIN:", { exact: true }).fill("8642");
  await pinDialog.getByLabel("Neue PIN wiederholen").fill("8642");
  await submitKioskDialogAndExpectRedirect(
    page,
    pinDialog,
    "pin-change-dialog",
    submitPinChange,
    "pin_change",
    "/kiosk/login/",
  );

  await expect(page).toHaveURL(/\/kiosk\/login\/$/);
  await expect(page.getByText("Deine PIN wurde geändert. Bitte melde dich erneut an.")).toBeVisible();
  await expect(page.getByLabel("Teilnehmer")).toBeVisible();
  await page.getByLabel("Teilnehmer").selectOption({ label: "Marie Curie" });
  await page.getByLabel("PIN:", { exact: true }).fill("8642");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).toHaveURL(/\/kiosk\/$/);
});

test("Kiosk user sees validation errors when changing PIN incorrectly", async ({ page }) => {
  await setupFirstAdmin(page);
  await createCamp(page, "PIN-Fehler-Validierung", 0, 4);
  await createParticipant(page, "Marie", "Curie", "", "2468");
  await logout(page);

  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Marie Curie" });
  await page.getByLabel("PIN:", { exact: true }).fill("2468");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();

  const kioskMenuButton = page.getByRole("button", { name: "Weitere Bereiche öffnen" });
  await expectButtonHitTestable(kioskMenuButton);
  await kioskMenuButton.click();
  const kioskMenu = page.locator("dialog#kiosk-menu-dialog");
  await waitForKioskDialogReady(page, kioskMenu, "kiosk-menu-dialog");
  const pinChangeButton = kioskMenu.getByRole("button", { name: "Eigene PIN ändern" });
  await pinChangeButton.click();
  const pinDialog = page.locator("dialog#pin-change-dialog");
  const submitPinChange = pinDialog.getByRole("button", { name: "PIN ändern" });
  await waitForKioskDialogReady(page, pinDialog, "pin-change-dialog", submitPinChange);

  await pinDialog.getByLabel("Aktuelle PIN").fill("9999");
  await pinDialog.getByLabel("Neue PIN:", { exact: true }).fill("8642");
  await pinDialog.getByLabel("Neue PIN wiederholen").fill("8642");
  await expectButtonHitTestable(submitPinChange);
  await submitPinChange.click();
  await expect(pinDialog).toBeVisible();
  await expect(page).toHaveURL(/\/kiosk\/$/);
  await expect(pinDialog.getByText("Die aktuelle PIN ist nicht korrekt.")).toBeVisible();

  await pinDialog.getByLabel("Aktuelle PIN").fill("2468");
  await pinDialog.getByLabel("Neue PIN:", { exact: true }).fill("8642");
  await pinDialog.getByLabel("Neue PIN wiederholen").fill("9753");
  await expectButtonHitTestable(submitPinChange);
  await submitPinChange.click();
  await expect(pinDialog).toBeVisible();
  await expect(page).toHaveURL(/\/kiosk\/$/);
  await expect(pinDialog.getByText("Die PINs stimmen nicht überein.")).toBeVisible();

  await pinDialog.getByRole("button", { name: "Schließen" }).click();
  await expect(pinDialog).not.toBeVisible();
});

test("Meal booking shows one contextual back action", async ({ page }) => {
  await setupFirstAdmin(page);
  const campName = await createCamp(page, "Kalender Navigation", 0, 4);
  await createParticipant(page, "Marie", "Curie", "", "1234");

  await page.getByRole("link", { name: "Fliegerlager-Abrechnung" }).click();
  await page.getByRole("link", { name: campName, exact: true }).click();
  await page.getByRole("link", { name: "Preise verwalten" }).first().click();
  await page.locator('input[name="meal-dinner_adult_price"]').fill("7.00");
  await page.getByRole("button", { name: "Standardpreise speichern" }).click();
  await logout(page);

  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Marie Curie" });
  await page.getByLabel("PIN:", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();

  // Existing meal-deadline notifications still use the legacy hash deep link.
  await page.goto("/kiosk/#meal-calendar");
  const mealCalendarDialog = page.locator("dialog#meal-calendar-dialog");
  await expect(mealCalendarDialog).toBeVisible();
  await expect(page.locator("dialog:open")).toHaveCount(1);
  await expect(page).toHaveURL(/.*\/kiosk\/$/);
  const openMealDay = mealCalendarDialog.locator(".meal-status-day--empty").first();
  await expect(openMealDay).toContainText("7,00 €");
  await openMealDay.click();

  const mealDayDetail = page.locator('dialog[id^="meal-day-detail-"]:visible');
  await expect(mealDayDetail).toBeVisible();
  await expect(page.locator("dialog:open")).toHaveCount(1);
  await expect(mealCalendarDialog).toBeHidden();
  await mealDayDetail.getByRole("button", { name: "Essen für diesen Tag buchen" }).click();

  const mealDialog = page.locator("dialog#meal-dialog");
  await expect(page.locator("dialog:open")).toHaveCount(1);
  await expect(mealDayDetail).toBeHidden();
  await expect(mealDialog.locator("[data-meal-date-checkbox]:checked")).toHaveCount(1);
  await expect(mealDialog.locator("#meal-step-persons")).toBeVisible();
  await expect(mealDialog.locator("#meal-dialog-close")).toBeHidden();
  await expect(mealDialog.getByRole("button", { name: "Zurück", exact: true })).toHaveCount(1);
  await mealDialog.locator("#meal-back-to-dates").click();
  await expect(mealDayDetail).toBeVisible();
  await expect(page.locator("dialog:open")).toHaveCount(1);
  await expect(mealDialog).toBeHidden();

  await page.keyboard.press("Escape");
  await mealCalendarDialog.getByRole("button", { name: "Essen buchen" }).click();
  await expect(mealDialog.locator("#meal-step-date")).toBeVisible();
  await expect(page.locator("dialog:open")).toHaveCount(1);
  await expect(mealCalendarDialog).toBeHidden();
  await expect(mealDialog.locator("#meal-dialog-close")).toBeVisible();
  await mealDialog.locator("input[data-meal-date-checkbox]:not([disabled])").first().check();
  await mealDialog.getByRole("button", { name: "Weiter" }).click();
  await expect(mealDialog.locator("#meal-dialog-close")).toBeHidden();
  await expect(mealDialog.getByRole("button", { name: "Zurück", exact: true })).toHaveCount(1);
  await mealDialog.locator("#meal-back-to-dates").click();
  await expect(mealDialog.locator("#meal-step-date")).toBeVisible();
  await expect(mealDialog.locator("#meal-dialog-close")).toBeVisible();
});

test("Partner meal retraction requires explicit confirmation", async ({ page }) => {
  test.slow();
  await setupFirstAdmin(page);
  const campName = await createCamp(page, "Partner-Essen", 0, 4);
  await createParticipant(page, "Ada", "Lovelace", "", "1234");
  await page.getByRole("link", { name: "Fliegerlager-Abrechnung" }).click();
  await page.getByRole("link", { name: campName, exact: true }).click();
  await createParticipant(page, "Grace", "Hopper", "", "5678");
  await page.getByRole("link", { name: "Fliegerlager-Abrechnung" }).click();
  await page.getByRole("link", { name: campName, exact: true }).click();
  await page.getByRole("link", { name: "Preise verwalten" }).first().click();
  await page.locator('input[name="meal-dinner_adult_price"]').fill("7.00");
  await page.getByRole("button", { name: "Standardpreise speichern" }).click();
  await logout(page);

  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Ada Lovelace" });
  await page.getByLabel("PIN:", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await page.getByRole("button", { name: /Weitere Bereiche öffnen/ }).or(page.locator(".kiosk-mobile-bottom-nav").getByRole("link", { name: "Mehr" })).click();
  await page.locator("dialog#kiosk-menu-dialog").getByRole("link", { name: /Partner & Aktivitäten/ }).click();
  await page.getByLabel("Teilnehmer einladen").selectOption({ label: "Grace Hopper" });
  await page.getByRole("button", { name: "Partner einladen" }).click();
  await page.getByRole("link", { name: "Abmelden" }).first().click();

  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Grace Hopper" });
  await page.getByLabel("PIN:", { exact: true }).fill("5678");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await page.getByRole("button", { name: /Weitere Bereiche öffnen/ }).or(page.locator(".kiosk-mobile-bottom-nav").getByRole("link", { name: "Mehr" })).click();
  await page.locator("dialog#kiosk-menu-dialog").getByRole("link", { name: /Partner & Aktivitäten/ }).click();
  await page.getByRole("button", { name: "Annehmen" }).click();
  await page.getByRole("link", { name: "Zurück" }).click();

  await page.locator('[data-kiosk-card="food"]').getByRole("button", { name: /Abendessen/ }).click();
  const graceMealCalendar = page.locator("dialog#meal-calendar-dialog");
  await graceMealCalendar.getByRole("button", { name: "Essen buchen" }).click();
  const graceMealDialog = page.locator("dialog#meal-dialog");
  await graceMealDialog.locator("input[data-meal-date-checkbox]:not([disabled])").first().check();
  await graceMealDialog.getByRole("button", { name: "Weiter" }).click();
  await graceMealDialog.getByRole("button", { name: "Essensanmeldung speichern" }).click();
  await expect(page.getByText("Essensanmeldung wurde für 1 Tag und 1 Person gespeichert.")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("link", { name: "Abmelden" }).first().click();

  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Ada Lovelace" });
  await page.getByLabel("PIN:", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/kiosk/#meal-calendar");
  const adaMealCalendar = page.locator("dialog#meal-calendar-dialog");
  await expect(adaMealCalendar).toBeVisible();
  const openPartnerMealDay = adaMealCalendar.locator(".meal-status-day--empty").first();
  await expect(openPartnerMealDay).toBeVisible();
  const { browserErrors, failedRequests } = trackPageIssues(page);
  await expect(adaMealCalendar.locator(".meal-status-day--booked")).toHaveCount(0);
  await openPartnerMealDay.click();
  const mealDayDetail = page.locator('dialog[id^="meal-day-detail-"]:visible');
  const partnerMealRow = mealDayDetail.locator(".meal-detail-row").filter({ hasText: "Grace Hopper" });
  await expect(partnerMealRow).toContainText("Gebucht");
  await partnerMealRow.getByRole("button", { name: "Zurücknehmen" }).click();

  const retractionDialog = page.locator("dialog#meal-retract-dialog");
  await expect(retractionDialog).toBeVisible();
  await expect(retractionDialog).toContainText("Grace Hopper");
  await expect(retractionDialog).toContainText("Betrag: 7,00 €");
  await assertNoUnexpectedOverflow(page);
  expect(browserErrors, `Unexpected browser errors: ${browserErrors.join(" | ")}`).toHaveLength(0);
  expect(failedRequests, `Unexpected failed requests: ${failedRequests.join(" | ")}`).toHaveLength(0);
  await retractionDialog.getByRole("button", { name: "Jetzt zurücknehmen" }).click();
  await expect(page.getByText("Essensanmeldung wurde zurückgenommen.")).toBeVisible();
  await page.emulateMedia({ colorScheme: "light" });
});

test("Kiosk masonry and expense cards stay responsive and accessible", async ({ page }) => {
  const { browserErrors, failedRequests } = trackPageIssues(page);

  await setupFirstAdmin(page);
  const campName = await createCamp(page, "Masonry-Lager", 0, 4);
  await createParticipant(page, "Marie", "Curie", "", "1234");
  await page.setViewportSize({ width: 1280, height: 900 });
  const adminHeaderLayout = await page.locator("header.topbar").evaluate((header) => {
    const identity = header.firstElementChild.getBoundingClientRect();
    const navigation = header.querySelector("nav").getBoundingClientRect();
    return {
      height: Math.round(header.getBoundingClientRect().height),
      identityCenter: Math.round(identity.top + identity.height / 2),
      navigationCenter: Math.round(navigation.top + navigation.height / 2),
    };
  });
  expect(adminHeaderLayout.height, "Aktive Admin-Kopfzeile bleibt kompakt").toBeLessThanOrEqual(72);
  expect(
    Math.abs(adminHeaderLayout.identityCenter - adminHeaderLayout.navigationCenter),
    "Lagerkontext und Navigation sind in einer Zeile ausgerichtet"
  ).toBeLessThanOrEqual(1);
  await assertNoUnexpectedOverflow(page);

  await page.setViewportSize({ width: 390, height: 844 });
  const mobileAdminHeader = await page.locator("header.topbar").evaluate((header) => {
    const navigationItems = Array.from(header.querySelectorAll("nav > .nav-link, nav > .nav-user-group")).filter(
      (item) => window.getComputedStyle(item).display !== "none"
    );
    return {
      height: Math.round(header.getBoundingClientRect().height),
      columns: new Set(navigationItems.map((item) => Math.round(item.getBoundingClientRect().left))).size,
    };
  });
  expect(mobileAdminHeader.height, "Mobile Admin-Kopfzeile bleibt überschaubar").toBeLessThanOrEqual(280);
  expect(mobileAdminHeader.columns, "Mobile Admin-Aktionen nutzen zwei Spalten").toBe(2);
  await assertNoUnexpectedOverflow(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await logout(page);

  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Marie Curie" });
  await page.getByLabel("PIN:", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();

  await page.getByRole("button", { name: /Weitere Bereiche öffnen/ }).or(page.locator(".kiosk-mobile-bottom-nav").getByRole("link", { name: "Mehr" })).click();
  await page.getByRole("button", { name: "Gemeinschaftsausgaben" }).click();
  await page.getByRole("link", { name: "Antrag einreichen" }).click();
  await page.getByLabel("Kategorie").selectOption({ label: "Verbrauchsmaterial" });
  await page.getByLabel("Beschreibung").fill("Sehr langer Gemeinschaftseinkauf für das gesamte Fliegerlager");
  await page.getByLabel("Betrag").fill("42.00");
  await page.getByLabel("Zahlungsdatum").fill(dateInputValue(new Date()));
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByText("Antrag auf Gemeinschaftsausgabe eingereicht.")).toBeVisible();
  await page.getByRole("link", { name: "Abmelden" }).first().click();

  await loginAsAdmin(page);
  await page.getByRole("link", { name: campName, exact: true }).click();
  await page.getByRole("button", { name: "Ablehnen" }).click();
  await page.getByLabel("Begründung (Pflichtfeld)").fill(
    "Der eingereichte Nachweis ist nicht lesbar. Bitte reiche einen neuen Beleg mit vollständigem Betrag ein."
  );
  await page.getByRole("button", { name: "Antrag endgültig ablehnen" }).click();
  await expect(page.getByText(/Antrag abgelehnt/)).toBeVisible();
  await logout(page);

  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Marie Curie" });
  await page.getByLabel("PIN:", { exact: true }).fill("1234");
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
    topByCard: Object.fromEntries(cards.map((card) => [card.dataset.kioskCard, Math.round(card.getBoundingClientRect().top)])),
    margins: cards.map((card) => window.getComputedStyle(card).marginTop),
  }));
  expect(desktopLayout.columns).toBe(2);
  expect(desktopLayout.spans.every((span) => span.startsWith("span "))).toBe(true);
  expect(desktopLayout.topByCard.food).toBe(desktopLayout.topByCard.drinks);
  expect(desktopLayout.margins).toEqual(Array(desktopLayout.margins.length).fill("0px"));

  const kioskSectionSpacing = await page.evaluate(() => {
    const masonryElement = document.querySelector("[data-kiosk-masonry]");
    const invoiceHeading = Array.from(document.querySelectorAll("main.kiosk-page > section h2")).find((heading) =>
      heading.textContent.includes("Meine Rechnungen & Dokumente")
    );
    const invoiceSection = invoiceHeading?.closest("section");
    const masonryRect = masonryElement.getBoundingClientRect();
    const invoiceRect = invoiceSection.getBoundingClientRect();
    const cardBottoms = Array.from(document.querySelectorAll("[data-kiosk-card]"), (card) =>
      card.getBoundingClientRect().bottom
    );
    return {
      gapBeforeMasonry: Math.round(masonryRect.top - invoiceRect.bottom),
      masonryBottom: Math.round(masonryRect.bottom),
      lastCardBottom: Math.round(Math.max(...cardBottoms)),
    };
  });
  expect(kioskSectionSpacing.gapBeforeMasonry).toBe(24);
  expect(kioskSectionSpacing.lastCardBottom).toBeLessThanOrEqual(kioskSectionSpacing.masonryBottom + 1);
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

  const menuButton = page.getByRole("button", { name: /Weitere Bereiche öffnen/ }).or(page.locator(".kiosk-mobile-bottom-nav").getByRole("link", { name: "Mehr" }));
  await menuButton.focus();
  await menuButton.click();
  const menuDialog = page.locator("dialog#kiosk-menu-dialog");
  const familyMenuButton = menuDialog.getByRole("button", { name: /Familie/ });
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
  await openKiosk(page, "/kiosk/login/");

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
  await openKiosk(page, "/kiosk/login/");

  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator("[data-theme-toggle]")).toHaveAttribute("aria-checked", "true");
});

test("Dark theme keeps contextual surfaces readable and responsive", async ({ page }) => {
  const { browserErrors, failedRequests } = trackPageIssues(page);

  await setupFirstAdmin(page);
  await createCamp(page, "Dark-Mode-Lager");
  const campId = new URL(page.url()).pathname.match(/\/camps\/(\d+)\//)[1];
  await page.locator("[data-theme-toggle]").click();
  await openKiosk(page, "/kiosk/login/");

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

  const xlsxLink = page.getByRole("link", { name: "Arbeitsmappe herunterladen", exact: true });
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

test("Admin configures SMTP and manually confirms exact information recipients", async ({ page }) => {
  const { browserErrors, failedRequests } = trackPageIssues(page);

  await setupFirstAdmin(page);
  await page.getByRole("link", { name: "E-Mail", exact: true }).click();
  await expect(page.getByRole("heading", { name: "E-Mail-Einstellungen" })).toBeVisible();
  await page.getByLabel("E-Mail-Versand aktivieren").check();
  await page.getByLabel("SMTP-Host").fill("smtp.example.test");
  await page.getByLabel("SMTP-Benutzername").fill("mailer");
  await page.getByLabel("SMTP-Passwort").fill("browser-test-secret");
  await page.getByLabel("Absendername").fill("Fliegerlager");
  await page.getByLabel("Absenderadresse").fill("lager@example.test");
  await page.getByRole("button", { name: "Einstellungen speichern" }).click();
  await expect(page.getByText("E-Mail-Einstellungen wurden gespeichert.")).toBeVisible();
  await expect(page.getByLabel("SMTP-Passwort")).toHaveValue("");
  await assertNoUnexpectedOverflow(page);

  await page.getByRole("link", { name: "Fliegerlager-Abrechnung" }).click();
  const campName = await createCamp(page, "Sommerlager E-Mail");
  await createParticipant(page, "Ada", "Lovelace", "Family@example.test");
  await page.getByRole("link", { name: "Fliegerlager-Abrechnung" }).click();
  await page.getByRole("link", { name: campName, exact: true }).click();
  await page.getByRole("link", { name: "Information versenden" }).click();
  await expect(page.getByRole("heading", { name: "Information versenden" })).toBeVisible();
  await page.getByLabel("Nachricht").fill("Treffpunkt ist morgen um 8 Uhr.");
  await page.getByRole("button", { name: "Versandvorschau anzeigen" }).click();
  await expect(page.getByRole("heading", { name: "Versandvorschau" })).toBeVisible();
  await expect(page.getByText("family@example.test", { exact: true })).toBeVisible();
  await expect(page.getByText("Ada Lovelace", { exact: true })).toBeVisible();
  await assertNoUnexpectedOverflow(page);

  await page.setViewportSize({ width: 430, height: 932 });
  await page.getByRole("switch", { name: "Dunkles Farbschema" }).click();
  await assertNoUnexpectedOverflow(page);
  await page.getByRole("button", { name: "Versand verbindlich bestätigen" }).click();

  await expect(page.getByRole("heading", { name: "Information · Versandauftrag" })).toBeVisible();
  await expect(page.getByText("Ausstehend", { exact: true }).first()).toBeVisible();

  await page.getByRole("link", { name: "Zur Lagerübersicht" }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Abrechnungslauf erstellen" }).click();
  await expect(page.getByRole("heading", { name: /Abrechnung .* · V1/ })).toBeVisible();
  await page.getByRole("link", { name: "Rechnungen versenden" }).click();
  await expect(page.getByRole("heading", { name: "Rechnungen versenden" })).toBeVisible();
  await page.getByRole("button", { name: "Versandvorschau anzeigen" }).click();
  await expect(page.getByRole("heading", { name: "Versandvorschau" })).toBeVisible();
  await expect(page.getByText("family@example.test", { exact: true })).toBeVisible();
  await expect(page.getByText(/abrechnung-\d+-v1\.pdf/)).toBeVisible();
  await assertNoUnexpectedOverflow(page);
  await page.getByRole("button", { name: "Versand verbindlich bestätigen" }).click();
  await expect(page.getByRole("heading", { name: "Rechnung · Versandauftrag" })).toBeVisible();

  expect(browserErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});

test("Daily shift template and kiosk shift flow", async ({ page }) => {
  test.setTimeout(60_000);
  await setupFirstAdmin(page);
  await createCamp(page, "Sommerlager Dienste", 0, 2);
  await createParticipant(page, "Albert", "Einstein", "", "1234");

  // Create a daily shift template via Frontend
  await page.getByRole("link", { name: "Fliegerlager-Abrechnung" }).click();
  await page.getByRole("link", { name: "Sommerlager Dienste" }).click();
  await page.getByRole("link", { name: "Tägliche Vorlagen verwalten" }).click();
  await page.getByRole("button", { name: "Vorlage anlegen" }).click();
  await expect(page.locator("dialog#template-dialog")).toBeVisible();
  await page.getByLabel("Name / Bezeichnung").fill("Spüldienst");
  await page.getByLabel("Beschreibung / Aufgaben").fill("Spülmaschine einräumen, ausräumen und den Spülbereich sauber hinterlassen.");
  await page.getByLabel("Benötigte Personen").fill("2");
  await page.getByRole("button", { name: "Speichern", exact: true }).click();
  await expect(page.getByText("Spüldienst").first()).toBeVisible();

  // Generate shifts
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "Dienste generieren" }).click();
  await expect(page.getByText("Dienste generiert")).toBeVisible();

  await logout(page);

  // Login to kiosk
  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Albert Einstein" });
  await page.getByLabel("PIN:", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();

  // Go to Shifts
  await page.getByRole("link", { name: "Dienstplan" }).click();
  await expect(page.getByRole("heading", { name: "Dienstplan" })).toBeVisible();

  // Check progress bar
  await expect(page.getByText("Dein Fortschritt")).toBeVisible();
  await expect(page.getByText("Super! Du hast alle Pflichtdienste übernommen.")).toBeVisible();

  // Every shift exposes its own description through the native kiosk help dialog.
  const shiftInfoButton = page.getByRole("button", { name: "Informationen zu Spüldienst" }).first();
  await expect(shiftInfoButton).toBeVisible();
  await shiftInfoButton.click();
  const shiftInfoDialog = page.locator("dialog#kiosk-help-dialog");
  await expect(shiftInfoDialog).toBeVisible();
  await expect(shiftInfoDialog.getByRole("heading", { name: "Informationen zu Spüldienst" })).toBeVisible();
  await expect(shiftInfoDialog).toContainText("Spülmaschine einräumen, ausräumen und den Spülbereich sauber hinterlassen.");
  await page.keyboard.press("Escape");
  await expect(shiftInfoDialog).toBeHidden();
  await expect(shiftInfoButton).toBeFocused();

  // Sign up for a shift
  await page.getByRole("button", { name: "Eintragen" }).first().click();
  await expect(page.getByText("Du hast dich für 'Spüldienst' eingetragen.")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("switch", { name: "Dunkles Farbschema" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await assertNoUnexpectedOverflow(page);
  await shiftInfoButton.click();
  await expect(shiftInfoDialog).toBeVisible();
  await expect(shiftInfoDialog).toContainText("Spülmaschine einräumen, ausräumen und den Spülbereich sauber hinterlassen.");
  const dialogBounds = await shiftInfoDialog.boundingBox();
  expect(dialogBounds).not.toBeNull();
  expect(dialogBounds.x).toBeGreaterThanOrEqual(0);
  expect(dialogBounds.y).toBeGreaterThanOrEqual(0);
  expect(dialogBounds.x + dialogBounds.width).toBeLessThanOrEqual(391);
  expect(dialogBounds.y + dialogBounds.height).toBeLessThanOrEqual(845);
  await page.keyboard.press("Escape");
  await expect(shiftInfoDialog).toBeHidden();
  await expect(shiftInfoButton).toBeFocused();
  await page.setViewportSize({ width: 1280, height: 800 });

  // "Austragen" should not exist, only "Zum Tausch anbieten"
  await expect(page.getByRole("button", { name: "Austragen" })).toBeHidden();
  await page.getByRole("button", { name: "Zum Tausch anbieten" }).first().click();
  await expect(page.getByText("wird nun zum Tausch angeboten.")).toBeVisible();

  // The shift should now be in the "Meine übernommenen Dienste" and have "Angebot zurückziehen"
  await expect(page.getByRole("button", { name: "Angebot zurückziehen" })).toBeVisible();

  await page.getByRole("link", { name: "Zurück" }).click();
  await page.getByRole("link", { name: "Abmelden" }).first().click();
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
    const campName = await createCamp(page, "Sommerlager Kiosk Mobile", 0, 4);
    const participantFirstName = viewport.name === "mobile portrait" ? "MobilePortrait" : "MobileLandscape";
    const participantName = `${participantFirstName} ExtremLangerUngetrennterTeilnehmername`;
    await createParticipant(page, participantFirstName, "ExtremLangerUngetrennterTeilnehmername", "", "1234");

    await page.getByRole("link", { name: "Fliegerlager-Abrechnung" }).click();
    await page.getByRole("link", { name: campName, exact: true }).click();
    await page.getByRole("link", { name: "Preise verwalten" }).first().click();
    await page.locator('input[name="meal-breakfast_adult_price"]').fill("5.00");
    await page.locator('input[name="meal-dinner_adult_price"]').fill("7.00");
    await page.getByRole("button", { name: "Standardpreise speichern" }).click();
    await logout(page);

    await openKiosk(page, "/kiosk/login/");
    await page.getByLabel("Teilnehmer").selectOption({ label: participantName });
    await page.getByLabel("PIN:", { exact: true }).fill("1234");
    await page.getByRole("button", { name: "Anmelden", exact: true }).click();

    await expect(page.getByRole("heading", { name: "Getränk buchen" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Verpflegung buchen" })).toBeVisible();

    if (viewport.name === "mobile portrait") {
      // In mobile portrait, use the bottom navigation to open the Essen menu
      const bottomNav = page.locator(".kiosk-mobile-bottom-nav");
      await bottomNav.getByRole("link", { name: "Essen" }).click({ force: true });
      await expect(page.locator("dialog#meal-calendar-dialog")).toBeVisible();
      await page.locator("dialog#meal-calendar-dialog").getByRole("button", { name: "Essen buchen" }).click();
    } else {
      // In mobile landscape, bottom nav is hidden, grid is visible. Open via food card button.
      await page.getByRole("button", { name: "Abendessen (Kalender)" }).click();
      await expect(page.locator("dialog#meal-calendar-dialog")).toBeVisible();
      await page.locator("dialog#meal-calendar-dialog").getByRole("button", { name: "Essen buchen" }).click();
    }
    await expect(page.locator("dialog#meal-dialog")).toBeVisible();
    await assertNoUnexpectedOverflow(page);
  });
}

test("Admin can batch delete and restore booking charges via table checkboxes", async ({ page }) => {
  await loginAsAdmin(page);
  await createCamp(page, "Batch-Lager");

  await page.getByRole("link", { name: "Preise verwalten" }).first().click();
  await page.getByRole("button", { name: "Getränk anlegen" }).click();
  const priceDialog = page.locator("dialog#price-rule-dialog");
  await priceDialog.getByLabel("Name / Bezeichnung").fill("Cola");
  await priceDialog.getByLabel("Einzelpreis (EUR)").fill("2.50");
  await priceDialog.getByRole("button", { name: "Speichern", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Preisregel wurde gespeichert.");
  await page.getByRole("link", { name: "Zurück zum Lager" }).click();

  await createParticipant(page, "Batch", "Tester");

  // Add 2 manual charges
  const manualChargeDialog = page.getByRole("dialog", { name: "Manuelle Buchung" });

  await page.getByRole("button", { name: "Buchung hinzufügen" }).click();
  await manualChargeDialog.getByLabel("Preisregel auswählen").selectOption({ index: 0 });
  await manualChargeDialog.getByLabel("Notiz (optional)").fill("Batch Pos 1");
  await manualChargeDialog.getByRole("button", { name: "Buchen" }).click();

  await page.getByRole("button", { name: "Buchung hinzufügen" }).click();
  await manualChargeDialog.getByLabel("Preisregel auswählen").selectOption({ index: 0 });
  await manualChargeDialog.getByLabel("Notiz (optional)").fill("Batch Pos 2");
  await manualChargeDialog.getByRole("button", { name: "Buchen" }).click();

  const chargeCell1 = page.locator('td[data-label="Beschreibung"]').filter({ hasText: "Batch Pos 1" });
  const chargeCell2 = page.locator('td[data-label="Beschreibung"]').filter({ hasText: "Batch Pos 2" });

  await expect(chargeCell1).toBeVisible();
  await expect(chargeCell2).toBeVisible();

  // Select all via header checkbox
  const selectAllCharges = page.locator("#select-all-charges");
  await selectAllCharges.check();

  const batchDeleteBtn = page.locator("#btn-batch-delete-charges");
  await expect(batchDeleteBtn).toBeEnabled();
  await expect(page.locator("#selected-charges-count")).toHaveText("2");

  // Accept confirm dialog and click batch delete
  page.once("dialog", (dialog) => dialog.accept());
  await batchDeleteBtn.click();

  await expect(page.getByText("2 Buchung(en) wurden gelöscht")).toBeVisible();

  // Select all audit logs via header checkbox and batch restore
  const selectAllAudit = page.locator("#select-all-audit-logs");
  await selectAllAudit.check();

  const batchRestoreBtn = page.locator("#btn-batch-restore-audit");
  await expect(batchRestoreBtn).toBeEnabled();
  await expect(page.locator("#selected-audit-count")).toHaveText("2");

  page.once("dialog", (dialog) => dialog.accept());
  await batchRestoreBtn.click();

  await expect(page.getByText("2 Buchung(en) wurden wiederhergestellt")).toBeVisible();
  await expect(chargeCell1).toBeVisible();
  await expect(chargeCell2).toBeVisible();
});

test("Login rate limiting blocks user after repeated failed attempts", async ({ page }, testInfo) => {
  await setupFirstAdmin(page);
  await logout(page);

  await page.goto("/login/");
  await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();

  // Submit 5 failed password attempts
  for (let i = 0; i < 5; i++) {
    await page.locator("#id_username").fill("admin");
    await page.locator("#id_password").fill("wrong-password");
    await page.getByRole("button", { name: "Anmelden", exact: true }).click();
    await expect(page.locator("#id_password")).toBeEmpty();
  }

  // 6th attempt should show rate limit error message
  await page.locator("#id_username").fill("admin");
  await page.locator("#id_password").fill("wrong-password");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();

  await expect(page.getByText("Zu viele Fehlversuche. Bitte versuche es in fünf Minuten erneut.")).toBeVisible();

  // Clear rate limits so we don't break subsequent tests on the same IP
  const fs = require("fs");
  const pythonBin = fs.existsSync(".venv/bin/python") ? ".venv/bin/python" : "python";
  require("child_process").execSync(
    `${pythonBin} src/manage.py shell -c "from billing.models import LoginAttempt; LoginAttempt.objects.all().delete()"`,
    { env: { ...process.env, DATABASE_URL: `sqlite:///tmp/e2e_${testInfo.workerIndex}.sqlite3` } }
  );
});

test("Admin can unlock participant PIN timeout after kiosk lockout", async ({ page }) => {
  await setupFirstAdmin(page);
  await createCamp(page, "PIN Unlock Camp");
  await createParticipant(page, "Lockout", "Test", "", "4321");
  const participantUrl = page.url();
  await logout(page);

  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Lockout Test" });

  // Fail PIN 5 times
  for (let i = 0; i < 5; i++) {
    await page.getByLabel("PIN:", { exact: true }).fill("9999");
    await page.getByRole("button", { name: "Anmelden", exact: true }).click();
    await expect(page.getByText("Teilnehmer oder PIN ist ungültig.")).toBeVisible();
  }

  // 6th attempt shows locked message
  await page.getByLabel("PIN:", { exact: true }).fill("9999");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page.getByText("Zu viele Fehlversuche. Bitte warte fünf Minuten und versuche es erneut.")).toBeVisible();

  // Admin logs in and unlocks participant
  await loginAsAdmin(page);
  await page.goto(participantUrl);
  await expect(page.getByRole("button", { name: "Timeout zurücksetzen" })).toBeVisible();
  await page.getByRole("button", { name: "Timeout zurücksetzen" }).click();
  await expect(page.getByText("Timeout wurde zurückgesetzt.")).toBeVisible();
  await logout(page);

  // Kiosk PIN login succeeds with correct PIN now
  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Lockout Test" });
  await page.getByLabel("PIN:", { exact: true }).fill("4321");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).toHaveURL(/.*\/kiosk\//);
});

test("Mobile Kiosk: summary invoice dialog and archived settlements do not overflow viewport and are scrollable", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await setupFirstAdmin(page);
  await createCamp(page, "Rechnung Mobile Camp", 0, 4);
  await createParticipant(page, "Invoice", "Tester", "", "1234");
  await logout(page);

  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Invoice Tester" });
  await page.getByLabel("PIN:", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).toHaveURL(/.*\/kiosk\//);

  // Open summary invoice dialog
  await page.getByRole("button", { name: "Details öffnen" }).click();
  const summaryDialog = page.locator("dialog#summary-dialog");
  await expect(summaryDialog).toBeVisible();

  // Verify no horizontal overflow beyond viewport
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);

  // Verify dialog is constrained in height
  const dialogBox = await summaryDialog.boundingBox();
  expect(dialogBox.height).toBeLessThanOrEqual(667);
});

test("Mobile Kiosk: partner authorization text does not overflow container on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await setupFirstAdmin(page);
  const campName = await createCamp(page, "Partner Mobile Camp", 0, 4);
  const campUrl = page.url();
  await createParticipant(page, "Alice", "Partner", "", "1234");
  await page.goto(campUrl);
  await createParticipant(page, "Bob", "Partner", "", "5678");

  // Invite Bob from Alice
  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Alice Partner" });
  await page.getByLabel("PIN:", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).toHaveURL(/.*\/kiosk\//);
  await page.goto("/kiosk/partners/");
  await page.locator("select[name='link-participant']").selectOption({ index: 1 });
  await page.getByRole("button", { name: "Partner einladen" }).click();
  await page.getByRole("link", { name: "Abmelden" }).first().click();

  // Login Bob to see pending invitation
  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Bob Partner" });
  await page.getByLabel("PIN:", { exact: true }).fill("5678");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).toHaveURL(/.*\/kiosk\//);

  await page.goto("/kiosk/partners/");
  const authScope = page.locator(".kiosk-partner-authorization").first();
  await expect(authScope).toBeVisible();

  // Verify container bounds and no horizontal overflow out of screen
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);

  // Accept invitation
  await page.getByRole("button", { name: "Annehmen" }).click();
  await expect(page.getByRole("button", { name: "Vollmacht widerrufen" })).toBeVisible();

  // Verify accepted state overflow
  const acceptedScroll = await page.evaluate(() => document.documentElement.scrollWidth);
  const acceptedClient = await page.evaluate(() => document.documentElement.clientWidth);
  expect(acceptedScroll).toBeLessThanOrEqual(acceptedClient);
});

test("Mobile Kiosk: check-in date selection does not overflow container on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await setupFirstAdmin(page);
  await createCamp(page, "Checkin Mobile Camp", 0, 4);
  await createParticipant(page, "Checkin", "Tester", "", "1234");
  await logout(page);

  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Checkin Tester" });
  await page.getByLabel("PIN:", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).toHaveURL(/.*\/kiosk\//);

  await page.getByRole("button", { name: "Eintragen" }).click();
  const checkinDialog = page.locator("dialog#checkin-dialog");
  await expect(checkinDialog).toBeVisible();

  // Verify check-in target row and date inputs do not exceed container width on mobile
  const targetRow = page.locator(".target-row--checkin").first();
  await expect(targetRow).toBeVisible();
  const dateInput = page.locator("#checkin-dialog input[type='date']").first();
  await expect(dateInput).toBeVisible();
  const inputBox = await dateInput.boundingBox();
  const containerBox = await targetRow.boundingBox();
  expect(inputBox.x + inputBox.width).toBeLessThanOrEqual(containerBox.x + containerBox.width + 2);

  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
});

test("Mobile Kiosk: checkmark for completed shifts is not horizontally distorted on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await setupFirstAdmin(page);
  await createCamp(page, "Shifts Mobile Camp", 0, 4);
  await createParticipant(page, "Shift", "Master", "", "1234");
  await logout(page);

  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Shift Master" });
  await page.getByLabel("PIN:", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).toHaveURL(/.*\/kiosk\//);

  await page.goto("/kiosk/shifts/");
  const checkIcon = page.locator(".shift-progress__check");
  await expect(checkIcon).toBeVisible();

  // Assert checkmark circle is perfectly 1:1 ratio and not squished horizontally
  const checkBox = await checkIcon.boundingBox();
  expect(checkBox.width).toEqual(checkBox.height);
  expect(checkBox.width).toBe(32);
});

test("Mobile Kiosk: fixed bottom navigation bar is present and functional on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await setupFirstAdmin(page);
  await createCamp(page, "Bottom Nav Mobile Camp", 0, 4);
  await createParticipant(page, "Nav", "Tester", "", "1234");
  await logout(page);

  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Nav Tester" });
  await page.getByLabel("PIN:", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).toHaveURL(/.*\/kiosk\//);

  const bottomNav = page.locator(".kiosk-mobile-bottom-nav");
  await expect(bottomNav).toBeVisible();

  await page.evaluate(() => {
    document.documentElement.style.setProperty("--test-safe-area-bottom", "34px");
    document.documentElement.style.setProperty("--test-safe-area-left", "0px");
    document.documentElement.style.setProperty("--test-safe-area-right", "0px");
    document.documentElement.style.setProperty("--mobile-safe-area-bottom", "var(--test-safe-area-bottom)");
    document.documentElement.style.setProperty("--mobile-safe-area-left", "var(--test-safe-area-left)");
    document.documentElement.style.setProperty("--mobile-safe-area-right", "var(--test-safe-area-right)");
  });

  // Verify fixed position at bottom
  const position = await bottomNav.evaluate((el) => window.getComputedStyle(el).position);
  expect(position).toBe("fixed");

  const bottomSpacing = await bottomNav.evaluate((el) => {
    const styles = window.getComputedStyle(el);
    const bounds = el.getBoundingClientRect();
    const safeArea = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--test-safe-area-bottom"));
    return {
      paddingBottom: Number.parseFloat(styles.paddingBottom),
      bottom: bounds.bottom,
      safeArea,
      viewportHeight: window.innerHeight,
      items: [...el.querySelectorAll(".kiosk-mobile-bottom-nav__item")].map((item) => {
        const itemBounds = item.getBoundingClientRect();
        return { width: itemBounds.width, height: itemBounds.height, bottom: itemBounds.bottom };
      }),
    };
  });
  expect(bottomSpacing.bottom).toBe(bottomSpacing.viewportHeight);
  for (const item of bottomSpacing.items) {
    expect(item.width).toBeGreaterThanOrEqual(44);
    expect(item.height).toBeGreaterThanOrEqual(44);
    expect(item.bottom).toBeLessThanOrEqual(bottomSpacing.viewportHeight - bottomSpacing.safeArea);
  }

  // Verify top navigation is hidden on mobile
  const topNav = page.locator(".kiosk-nav");
  await expect(topNav).toBeHidden();

  // Verify navigation items exist
  await expect(bottomNav.getByRole("link", { name: "Kiosk" })).toBeVisible();
  await expect(bottomNav.getByRole("link", { name: "Dienste" })).toBeVisible();
  await expect(bottomNav.getByRole("link", { name: "Essen" })).toBeVisible();
  await expect(bottomNav.getByRole("link", { name: "Mehr" })).toBeVisible();
  await expect(bottomNav.getByRole("link", { name: "Abmelden" })).toBeVisible();

  // Test toggling the "Mehr" menu
  const mehrButton = bottomNav.getByRole("link", { name: "Mehr" });
  await mehrButton.click();
  const menuDialog = page.locator("dialog#kiosk-menu-dialog");
  await expect(menuDialog).toBeVisible();

  // Clicking "Mehr" again should close the menu
  await mehrButton.click({ force: true });
  await expect(menuDialog).not.toBeVisible();

  // Clicking "Essen" while "Mehr" menu is open should close the menu and open Essen
  await mehrButton.click();
  await expect(menuDialog).toBeVisible();
  const essenButton = bottomNav.getByRole("link", { name: "Essen" });
  await essenButton.click({ force: true });
  await expect(menuDialog).not.toBeVisible();
  const mealDialog = page.locator("dialog#meal-calendar-dialog");
  await expect(mealDialog).toBeVisible();

  // Clean up by closing meal dialog
  await essenButton.click({ force: true });
  await expect(mealDialog).not.toBeVisible();
});

test("Issue #417: Admin attendance matrix/export and kiosk profile flow", async ({ page }) => {
  await setupFirstAdmin(page);
  const campName = await createCamp(page, "Anwesenheit Profile", 0, 4);
  await createParticipant(page, "Marie", "Curie", "marie@example.test", "8642");

  const arrivalDate = dateInputValue(new Date());
  const departureDate = dateInputValue(addDays(new Date(), 3));
  await page.getByRole("link", { name: "Teilnehmer bearbeiten" }).click();
  await page.getByLabel("Anreise").fill(arrivalDate);
  await page.getByLabel("Abreise").fill(departureDate);
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByRole("heading", { name: "Marie Curie" })).toBeVisible();

  await page.getByRole("link", { name: "Fliegerlager-Abrechnung" }).click();
  await page.getByRole("link", { name: campName, exact: true }).click();

  const xlsxLink = page.getByRole("link", { name: "Anwesenheit als Arbeitsmappe herunterladen" });
  await expect(xlsxLink).toBeVisible();
  const xlsxResponsePromise = page.waitForResponse(
    (response) => response.url().includes("/attendance/export.xlsx") && response.status() === 200,
  );
  await xlsxLink.click();
  const xlsxResponse = await xlsxResponsePromise;
  expect(xlsxResponse.headers()["content-type"]).toContain("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  expect(xlsxResponse.headers()["content-disposition"]).toContain(".xlsx");

  await page.getByRole("link", { name: "Anwesenheit", exact: true }).click();
  await expect(page.getByRole("heading", { name: `Anwesenheit: ${campName}` })).toBeVisible();

  const matrix = page.getByRole("region", { name: "Anwesenheitsmatrix" });
  await expect(matrix).toBeVisible();
  await expect(matrix.getByRole("table")).toBeVisible();
  await expect(page.getByText("Legende", { exact: true })).toBeVisible();
  const legend = page.locator(".attendance-legend");
  await expect(legend.locator("dt", { hasText: "Anwesend" })).toBeVisible();
  await expect(legend.locator("dt", { hasText: "Abwesend" })).toBeVisible();
  await expect(legend.locator("dt", { hasText: "Außerhalb des Aufenthalts" })).toBeVisible();

  const participantRow = matrix.getByRole("row", { name: /Marie Curie/ });
  await expect(participantRow).toBeVisible();
  expect(await participantRow.locator('[data-status="present"]').count()).toBeGreaterThan(0);
  expect(await participantRow.locator('[data-status="disabled"]').count()).toBeGreaterThan(0);

  await page.setViewportSize({ width: 390, height: 844 });
  const matrixLayout = await matrix.evaluate((region) => ({
    clientWidth: region.clientWidth,
    scrollWidth: region.scrollWidth,
    tabIndex: region.tabIndex,
    pageScrollWidth: document.documentElement.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
  }));
  expect(matrixLayout.pageScrollWidth).toBeLessThanOrEqual(matrixLayout.viewportWidth + 1);
  expect(matrixLayout.scrollWidth).toBeGreaterThan(matrixLayout.clientWidth);
  expect(matrixLayout.tabIndex).toBeGreaterThanOrEqual(0);
  await matrix.focus();
  await expect.poll(() => matrix.evaluate((region) => document.activeElement === region)).toBe(true);

  await logout(page);
  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Marie Curie" });
  await page.getByLabel("PIN:", { exact: true }).fill("8642");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).toHaveURL(/\/kiosk\/$/);

  const openKioskMenu = page.getByRole("button", { name: /Weitere Bereiche öffnen/ }).or(
    page.locator(".kiosk-mobile-bottom-nav").getByRole("link", { name: "Mehr" }),
  );
  await openKioskMenu.click();
  const kioskMenu = page.locator("dialog#kiosk-menu-dialog");
  const privateProfileLink = kioskMenu.getByRole("link", { name: "Mein Profil" });
  await expect(privateProfileLink).toHaveAttribute("href", /\/kiosk\/profile\/\d+\/$/);
  await privateProfileLink.click();
  await expect(page).toHaveURL(/\/kiosk\/profile\/\d+\/$/);

  await page.locator('input[name="phone"]').fill("+49 201 417");
  await page.locator('input[name="birth_date"]').fill("1990-01-02");
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page).toHaveURL(/\/kiosk\/$/);

  await openKioskMenu.click();
  await kioskMenu.getByRole("link", { name: "Mein Profil" }).click();
  const birthDate = page.locator('input[name="birth_date"]');
  await birthDate.fill("2999-01-01");
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(birthDate).toHaveAttribute("aria-invalid", "true");
  const describedBy = await birthDate.getAttribute("aria-describedby");
  expect(describedBy).toBeTruthy();
  for (const id of describedBy.split(/\s+/)) {
    await expect(page.locator(`#${id}`)).toBeVisible();
  }
  await expect(page.getByText("Das Geburtsdatum darf nicht in der Zukunft liegen.", { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "Abmelden", exact: true }).first().click();
  await expect(page).toHaveURL(/\/kiosk\/login\/$/);
  // The central kiosk intentionally has no private mobile bottom navigation.
  // Use its desktop top navigation for the central-surface profile check.
  await page.setViewportSize({ width: 1280, height: 800 });
  await openKiosk(page, "/central/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Marie Curie" });
  await page.getByLabel("PIN:", { exact: true }).fill("8642");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).toHaveURL(/\/central\/kiosk\/$/);
  await page.getByRole("button", { name: /Weitere Bereiche öffnen/ }).click();
  await expect(page.locator("dialog#kiosk-menu-dialog").getByRole("link", { name: "Mein Profil" })).toHaveAttribute(
    "href",
    /\/central\/kiosk\/profile\/\d+\/$/,
  );
});

test("Desktop Kiosk: top navigation is present and bottom navigation is hidden", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await setupFirstAdmin(page);
  await createCamp(page, "Desktop Nav Camp", 0, 4);
  await createParticipant(page, "DeskNav", "Tester", "", "1234");
  await logout(page);

  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "DeskNav Tester" });
  await page.getByLabel("PIN:", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).toHaveURL(/.*\/kiosk\//);

  const topNav = page.locator(".kiosk-nav");
  await expect(topNav).toBeVisible();

  const bottomNav = page.locator(".kiosk-mobile-bottom-nav");
  await expect(bottomNav).toBeHidden();
});

test("Mobile Kiosk: bottom navigation bar hides shifts in post-camp mode", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await setupFirstAdmin(page);
  // Create a camp that ended in the past (offset -10 days, duration 5 days -> ended 5 days ago)
  await createCamp(page, "Post Nav Mobile Camp", -10, 5);
  await createParticipant(page, "PostNav", "Tester", "", "1234");
  await logout(page);

  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "PostNav Tester" });
  await page.getByLabel("PIN:", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).toHaveURL(/.*\/kiosk\//);

  const bottomNav = page.locator(".kiosk-mobile-bottom-nav");
  await expect(bottomNav).toBeVisible();

  // Verify "Dienste" and "Essen" are hidden since the camp is over
  await expect(bottomNav.getByRole("link", { name: "Kiosk" })).toBeVisible();
  await expect(bottomNav.getByRole("link", { name: "Dienste" })).toHaveCount(0);
  await expect(bottomNav.getByRole("link", { name: "Essen" })).toHaveCount(0);
  await expect(bottomNav.getByRole("link", { name: "Mehr" })).toBeVisible();

});

test("Kiosk: Participant can open donate dialog, enter amount and see confetti", async ({ page }) => {
  await setupFirstAdmin(page);
  await createCamp(page, "Donate Camp", -10, 5); // post-camp
  await createParticipant(page, "Donate", "Tester", "", "1234");
  await logout(page);

  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Donate Tester" });
  await page.getByLabel("PIN:", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).toHaveURL(/.*\/kiosk\//);

  // Click the donate button
  await page.getByRole("button", { name: "Spenden" }).click();

  // Dialog should be open
  const dialog = page.locator("#donate-dialog");
  await expect(dialog).toBeVisible();

  // Fill amount and submit
  await dialog.getByLabel("Betrag in €").fill("10.50");
  await dialog.getByRole("button", { name: "Spenden eintragen" }).click();

  // Should show success message
  await expect(page.locator(".message.success")).toContainText("Vielen Dank für deine Spende von 10.50 €!");

  // Check if confetti canvas is present (indicates animation triggered)
  const confettiCanvas = page.locator("canvas").first();
  await expect(confettiCanvas).toBeAttached();
});
