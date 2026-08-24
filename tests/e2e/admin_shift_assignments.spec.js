const { expect, test } = require("./fixtures");

function dateInputValue(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

async function setupAdminCampParticipantAndShift(page) {
  await page.goto("/setup/");
  if (page.url().includes("/login/")) {
    await page.locator("#id_username").fill("admin");
    await page.locator("#id_password").fill("strong-test-pass-123");
    await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  } else {
    await page.locator("#id_username").fill("admin");
    await page.locator("#id_email").fill("admin@example.test");
    await page.locator("#id_password1").fill("strong-test-pass-123");
    await page.locator("#id_password2").fill("strong-test-pass-123");
    await page.getByRole("button", { name: "Admin anlegen" }).click();
  }

  await page.getByRole("link", { name: "Lager anlegen" }).click();
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const endDate = new Date(tomorrow);
  endDate.setDate(endDate.getDate() + 2);
  await page.getByLabel("Name").fill("Dienstbesetzung E2E");
  await page.getByLabel("Jahr").fill(String(tomorrow.getFullYear()));
  await page.getByLabel("Beginn").fill(dateInputValue(tomorrow));
  await page.getByLabel("Ende").fill(dateInputValue(endDate));
  await page.getByRole("button", { name: "Speichern" }).click();
  const campId = new URL(page.url()).pathname.match(/\/camps\/(\d+)\//)[1];

  await page.getByRole("link", { name: "Teilnehmer anlegen" }).click();
  await page.getByLabel("Vorname").fill("Ada");
  await page.getByLabel("Nachname").fill("Dienstperson");
  await page.getByRole("button", { name: "Speichern" }).click();

  await page.goto(`/camps/${campId}/shifts/new/`);
  await page.getByLabel("Name des Dienstes").fill("Küchendienst");
  await page.getByLabel("Datum").fill(dateInputValue(tomorrow));
  await page.getByLabel("Benötigte Helfer").fill("1");
  await page.getByRole("button", { name: "Speichern" }).click();
  await page.getByRole("link", { name: "Bearbeiten" }).click();
}

test.describe("Admin-Dienstbesetzung ohne JavaScript", () => {
  test.use({ javaScriptEnabled: false });

  test("bleibt mobil, per Tastatur und mit nativen Formularen bedienbar", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await setupAdminCampParticipantAndShift(page);

    await expect(page.getByRole("heading", { name: "Ausführende Personen" })).toBeVisible();
    const search = page.getByLabel("Teilnehmende oder Begleitpersonen suchen");
    await search.fill("Ada");
    await page.getByRole("button", { name: "Suchen" }).click();
    await expect(page.getByText("Ada Dienstperson")).toBeVisible();

    const addButton = page.getByRole("button", { name: "Eintragen" });
    await addButton.focus();
    await expect(addButton).toBeFocused();
    const addBounds = await addButton.boundingBox();
    expect(addBounds.height).toBeGreaterThanOrEqual(44);
    await addButton.click();

    await expect(page.getByText("Ausführende Person wurde eingetragen.")).toBeVisible();
    await expect(page.getByText("Ada Dienstperson")).toBeVisible();
    const removeButton = page.getByRole("button", { name: "Austragen" });
    const removeBounds = await removeButton.boundingBox();
    expect(removeBounds.height).toBeGreaterThanOrEqual(44);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
    await removeButton.focus();
    await expect(removeButton).toBeFocused();
    await removeButton.click();
    await expect(page.getByText("Ausführende Person wurde ausgetragen.")).toBeVisible();
    await expect(page.getByText("Noch niemand eingetragen.")).toBeVisible();
  });
});
