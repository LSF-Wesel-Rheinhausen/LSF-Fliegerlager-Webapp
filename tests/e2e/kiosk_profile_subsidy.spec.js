const { expect, test } = require("./fixtures");
const { configureCampKioskAccess, openKiosk } = require("./kioskAccess");

const berlinDateFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Berlin",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function berlinDateParts(date) {
  return Object.fromEntries(
    berlinDateFormatter
      .formatToParts(date)
      .filter(({ type }) => type !== "literal")
      .map(({ type, value }) => [type, value]),
  );
}

function dateValue(date) {
  const { year, month, day } = berlinDateParts(date);
  return `${year}-${month}-${day}`;
}

async function setupFirstAdmin(page) {
  await page.goto("/setup/");
  if (page.url().includes("/login/")) {
    await page.locator("#id_username").fill("admin");
    await page.locator("#id_password").fill("strong-test-pass-123");
    await page.getByRole("button", { name: "Anmelden", exact: true }).click();
    return;
  }
  await page.locator("#id_username").fill("admin");
  await page.locator("#id_email").fill("admin@example.test");
  await page.locator("#id_password1").fill("strong-test-pass-123");
  await page.locator("#id_password2").fill("strong-test-pass-123");
  await page.getByRole("button", { name: "Admin anlegen" }).click();
}

async function createCamp(page) {
  const today = new Date();
  const startsOn = new Date(today);
  startsOn.setDate(startsOn.getDate() - 1);
  const endsOn = new Date(today);
  endsOn.setDate(endsOn.getDate() + 3);
  await page.getByRole("link", { name: "Lager anlegen" }).click();
  await page.getByLabel("Name").fill("Profil-Förderung E2E");
  await page.getByLabel("Jahr").fill(dateValue(today).slice(0, 4));
  await page.getByLabel("Beginn").fill(dateValue(startsOn));
  await page.getByLabel(/^Ende:?$/).fill(dateValue(endsOn));
  await page.getByRole("button", { name: "Speichern" }).click();
  await configureCampKioskAccess(page);
}

test("youth profile shows its own effective subsidy, never guardian rates", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await setupFirstAdmin(page);
  await createCamp(page);

  await page.getByRole("link", { name: "Teilnehmer anlegen" }).click();
  await page.getByLabel("Vorname").fill("Mira");
  await page.getByLabel("Nachname").fill("Jugendgruppe");
  await page.getByLabel("Jugendgruppe").check();
  await page.getByLabel("Hilfssatz").fill("0.5000");
  await page.getByLabel("Berufssatz").fill("0.6000");
  await page.getByRole("button", { name: "Speichern" }).click();
  await page.locator(".participant-more-actions > summary").click();
  await page.getByRole("link", { name: "PIN setzen", exact: true }).click();
  await page.getByLabel("Neue PIN").fill("2468");
  await page.getByRole("button", { name: "Speichern", exact: true }).click();

  await page.getByRole("link", { name: "Preise verwalten" }).first().click();
  await page.locator('input[name="meal-breakfast_adult_price"]').fill("10.00");
  await page.locator('input[name="meal-breakfast_adult_foerdersatz"]').fill("80");
  await page.getByRole("button", { name: "Standardpreise speichern" }).click();
  await expect(page.getByText("Standardpreise für Verpflegung wurden gespeichert.")).toBeVisible();

  await openKiosk(page, "/kiosk/login/");
  await page.getByLabel("Teilnehmer").selectOption({ label: "Mira Jugendgruppe" });
  await page.getByLabel("PIN:", { exact: true }).fill("2468");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();

  const familyDialog = page.locator("#family-dialog");
  const csrfToken = await familyDialog.locator('input[name="csrfmiddlewaretoken"]').inputValue();
  const familyResponse = await page.request.post("/kiosk/", {
    maxRedirects: 0,
    form: {
      csrfmiddlewaretoken: csrfToken,
      action: "family_member_create",
      "family-first_name": "Lina",
      "family-last_name": "Familie",
      "family-role": "child",
    },
    headers: { referer: page.url() },
  });
  expect(familyResponse.status()).toBe(302);
  await page.reload();

  const openKioskMenu = page.getByRole("button", { name: /Weitere Bereiche öffnen/ }).or(
    page.locator(".kiosk-mobile-bottom-nav").getByRole("link", { name: "Mehr" }),
  );
  const kioskMenu = page.locator("dialog#kiosk-menu-dialog");

  for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    if (viewport.width === 390) await page.emulateMedia({ colorScheme: "dark" });
    await page.goto("/kiosk/");
    await openKioskMenu.click();
    await kioskMenu.getByRole("link", { name: "Mein Profil" }).click();
    const subsidy = page.locator("[data-profile-subsidy]");
    await expect(subsidy).toBeVisible();
    await expect(subsidy).toContainText("Hilfssatz");
    await expect(subsidy).toContainText("50 %");
    await expect(subsidy).toContainText("Berufssatz");
    await expect(subsidy).toContainText("60 %");
    await expect(subsidy).toContainText("Standard Frühstück");
    await expect(subsidy).toContainText("80 %");
    await expect(subsidy).toContainText("24 %");
    await expect(subsidy.locator("input, select, textarea, button")).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);

    await page.getByRole("link", { name: "Lina Familie", exact: true }).click();
    await expect(page.locator("[data-profile-subsidy]")).toHaveCount(0);
    await expect(page.locator("main")).not.toContainText("85 %");
    await expect(page.locator("main")).not.toContainText("75 %");
    await expect(page.locator("main")).not.toContainText("24 %");
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  }
  expect(pageErrors).toEqual([]);
});
