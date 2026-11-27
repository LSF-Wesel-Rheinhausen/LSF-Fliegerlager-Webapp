const { expect, test } = require("./fixtures");
const { configureCampKioskAccess, openKiosk } = require("./kioskAccess");

async function setupAdmin(page) {
  await page.goto("/setup/");
  if (page.url().includes("/login/")) {
    await page.locator("#id_username").fill("admin@example.test");
    await page.locator("#id_password").fill("strong-test-pass-123");
    await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  } else {
    await page.locator("#id_username").fill("admin@example.test");
    await page.locator("#id_email").fill("admin@example.test");
    await page.locator("#id_password1").fill("strong-test-pass-123");
    await page.locator("#id_password2").fill("strong-test-pass-123");
    await page.getByRole("button", { name: "Admin anlegen" }).click();
  }
}

async function createParticipant(page, campId) {
  await page.goto(`/camps/${campId}/`);
  await page.getByRole("link", { name: "Teilnehmer anlegen" }).click();
  await page.getByLabel("Vorname").fill("Ada");
  await page.getByLabel("Nachname").fill("Schaltertest");
  await page.getByRole("button", { name: "Speichern" }).click();
  await page.locator(".participant-more-actions > summary").click();
  await page.getByRole("link", { name: "PIN setzen", exact: true }).click();
  await page.getByLabel("Neue PIN").fill("1234");
  await page.getByRole("button", { name: "Speichern", exact: true }).click();
}

test("camp feature switch persists and gates private and central kiosk routes", async ({ page, browser, baseURL }) => {
  await setupAdmin(page);
  await page.goto("/camps/");
  await page.getByRole("link", { name: "Lager anlegen" }).click();
  const today = new Date();
  const start = new Date(today);
  start.setDate(start.getDate() - 2);
  const end = new Date(today);
  end.setDate(end.getDate() + 4);
  const dateValue = (value) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
  await page.getByLabel(/^Name:?$/).fill(`Funktionsschalter ${Date.now()}`);
  await page.getByLabel(/^Jahr:?$/).fill(String(today.getFullYear()));
  await page.getByLabel(/^Beginn:?$/).fill(dateValue(start));
  await page.getByLabel(/^Ende:?$/).fill(dateValue(end));
  await page.getByLabel(/^Aktiv:?$/).check();
  await page.getByRole("button", { name: "Speichern", exact: true }).click();
  const match = page.url().match(/\/camps\/(\d+)\//);
  expect(match).not.toBeNull();
  const campId = match[1];
  await configureCampKioskAccess(page);
  await createParticipant(page, campId);
  const editUrl = `/camps/${campId}/edit/`;

  await page.goto(editUrl);
  await expect(page.getByRole("heading", { name: "Nutzerfunktionen" })).toBeVisible();
  await expect(page.getByText("Gilt für dieses Lager. Bestehende Buchungen bleiben erhalten.")).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ colorScheme: "light" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.emulateMedia({ colorScheme: "light" });
  const shifts = page.getByRole("checkbox", { name: "Dienste verwalten" });
  await expect(shifts).toBeChecked();
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    const layout = await page.locator(".camp-feature-toggle").evaluateAll((rows) =>
      rows.map((row) => {
        const input = row.querySelector('input[type="checkbox"]');
        const inputRect = input.getBoundingClientRect();
        return {
          rowHeight: row.getBoundingClientRect().height,
          inputHeight: inputRect.height,
          inputWidth: inputRect.width,
          inputRight: inputRect.right,
        };
      }),
    );
    expect(layout).toHaveLength(11);
    expect(layout.every(({ rowHeight, inputHeight, inputWidth }) => rowHeight >= 52 && inputHeight >= 44 && inputWidth >= 44)).toBe(true);
    expect(Math.max(...layout.map(({ inputRight }) => inputRight)) - Math.min(...layout.map(({ inputRight }) => inputRight))).toBeLessThanOrEqual(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(shifts).toHaveAttribute("type", "checkbox");
  await shifts.focus();
  await page.keyboard.press("Space");
  await expect(shifts).not.toBeChecked();
  await page.getByRole("button", { name: "Speichern" }).click();
  await page.goto(editUrl);
  await expect(page.getByRole("checkbox", { name: "Dienste verwalten" })).not.toBeChecked();

  const kioskContext = await browser.newContext({ baseURL, viewport: { width: 1440, height: 900 } });
  try {
    const kiosk = await kioskContext.newPage();

    for (const mode of [
      { prefix: "/kiosk", home: "/kiosk/", shifts: "/kiosk/shifts/" },
      { prefix: "/central/kiosk", home: "/central/kiosk/", shifts: "/central/kiosk/shifts/" },
    ]) {
      await openKiosk(kiosk, `${mode.prefix}/login/`);
      await kiosk.getByLabel("Teilnehmer").selectOption({ label: "Ada Schaltertest" });
      await kiosk.getByLabel("PIN:", { exact: true }).fill("1234");
      await kiosk.getByRole("button", { name: "Anmelden", exact: true }).click();
      await expect(kiosk).toHaveURL(new RegExp(`${mode.home.replaceAll("/", "\\/")}$`));

      for (const viewport of [
        { width: 1440, height: 900 },
        { width: 390, height: 844 },
      ]) {
        await kiosk.setViewportSize(viewport);
        await kiosk.goto(mode.home);
        await expect(kiosk.locator(`a[href="${mode.shifts}"]`)).toHaveCount(0);
        expect(await kiosk.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
      }

      const denied = await kiosk.goto(mode.shifts);
      expect(denied.status()).toBe(403);
      await expect(kiosk.getByText("Diese Funktion ist für dieses Lager nicht freigegeben.")).toBeVisible();
    }

    await page.goto(editUrl);
    const reenableShifts = page.getByRole("checkbox", { name: "Dienste verwalten" });
    await expect(reenableShifts).not.toBeChecked();
    await reenableShifts.check();
    await page.getByRole("button", { name: "Speichern" }).click();

    for (const mode of [
      { prefix: "/kiosk", home: "/kiosk/", shifts: "/kiosk/shifts/" },
      { prefix: "/central/kiosk", home: "/central/kiosk/", shifts: "/central/kiosk/shifts/" },
    ]) {
      await openKiosk(kiosk, `${mode.prefix}/login/`);
      await kiosk.getByLabel("Teilnehmer").selectOption({ label: "Ada Schaltertest" });
      await kiosk.getByLabel("PIN:", { exact: true }).fill("1234");
      await kiosk.getByRole("button", { name: "Anmelden", exact: true }).click();
      for (const viewport of [
        { width: 1440, height: 900 },
        { width: 390, height: 844 },
      ]) {
        await kiosk.setViewportSize(viewport);
        await kiosk.goto(mode.home);
        await expect(kiosk.locator(`a[href="${mode.shifts}"]`).first()).toBeAttached();
      }
      const restored = await kiosk.goto(mode.shifts);
      expect(restored.status()).toBe(200);
    }
  } finally {
    await kioskContext.close();
  }
});
