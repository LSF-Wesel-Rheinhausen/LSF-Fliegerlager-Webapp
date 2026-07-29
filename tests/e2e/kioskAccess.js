const { expect } = require("@playwright/test");

const KIOSK_ACCESS_PIN = "864208";

async function configureCampKioskAccess(page) {
  await page.getByRole("link", { name: "Lager-PIN verwalten" }).click();
  await expect(page.getByRole("heading", { name: "Lager-PIN verwalten" })).toBeVisible();
  await page.getByLabel("Neue Lager-PIN").fill(KIOSK_ACCESS_PIN);
  await page.getByLabel("Lager-PIN wiederholen").fill(KIOSK_ACCESS_PIN);
  await page.getByRole("button", { name: /Lager-PIN (einrichten|ändern)/ }).click();
  await expect(page.getByText("Lager-PIN gespeichert. Alle bisherigen Lagerzugänge wurden widerrufen.")).toBeVisible();
  await page.getByRole("link", { name: "Zurück zur Übersicht" }).click();
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
}

async function openKiosk(page, path = "/kiosk/login/") {
  await page.goto(path);
  if (page.url().includes("/access/")) {
    await expect(page.getByRole("heading", { name: "Lager-PIN eingeben" })).toBeVisible();
    await page.getByLabel("Lager-PIN").fill(KIOSK_ACCESS_PIN);
    await page.getByRole("button", { name: "Weiter" }).click();
  }
  await expect(page).not.toHaveURL(/\/access\//);
}

module.exports = {
  KIOSK_ACCESS_PIN,
  configureCampKioskAccess,
  openKiosk,
};
