const { expect, test } = require("./fixtures");
const { isBenignPageRequestFailure, requestFailureDetails } = require("./requestFailureFilter");

test.use({ serviceWorkers: "block" });

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

async function setupAdminWithCamp(page) {
  await page.goto("/setup/");
  if (page.url().includes("/login/")) {
    await page.locator("#id_username").fill("admin@example.test");
    await page.locator("#id_password").fill("strong-test-pass-123");
    await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  } else {
    await expect(page.getByRole("heading", { name: "Ersteinrichtung" })).toBeVisible();
    await page.locator("#id_username").fill("admin");
    await page.locator("#id_email").fill("admin@example.test");
    await page.locator("#id_password1").fill("strong-test-pass-123");
    await page.locator("#id_password2").fill("strong-test-pass-123");
    await page.getByRole("button", { name: "Admin anlegen" }).click();
  }
  await expect(page.getByRole("heading", { name: "Lager" })).toBeVisible();

  await page.getByRole("link", { name: "Lager anlegen" }).click();
  await expect(page.getByRole("heading", { name: "Lager anlegen" })).toBeVisible();
  const campName = `Sortierlager ${Date.now()}`;
  const year = new Date().getFullYear();
  await page.getByLabel("Name").fill(campName);
  await page.getByLabel("Jahr").fill(String(year));
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
  return { campName, campUrl: page.url() };
}

async function createParticipant(page, campUrl, firstName, lastName) {
  await page.goto(campUrl);
  await page.getByRole("link", { name: "Teilnehmer anlegen" }).click();
  await expect(page.getByRole("heading", { name: "Teilnehmer anlegen" })).toBeVisible();
  await page.getByLabel("Vorname").fill(firstName);
  await page.getByLabel("Nachname").fill(lastName);
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByRole("heading", { name: `${firstName} ${lastName}` })).toBeVisible();
}

function settlementTable(page) {
  return page.locator(".participant-settlements table");
}

function participantColumn(page) {
  return settlementTable(page).locator("tbody tr:visible td:first-child");
}

test("sorting a column toggles order and aria-sort", async ({ page }) => {
  const { browserErrors, failedRequests } = trackPageIssues(page);
  const { campUrl } = await setupAdminWithCamp(page);
  await createParticipant(page, campUrl, "Zora", "Zulu");
  await createParticipant(page, campUrl, "Anton", "Alpha");
  await createParticipant(page, campUrl, "Berta", "Beta");
  await page.goto(campUrl);

  const table = settlementTable(page);
  const header = table.locator("th", { hasText: "Teilnehmer" });
  const sortButton = header.getByRole("button", { name: "Teilnehmer" });
  await expect(sortButton).toBeVisible();

  await sortButton.click();
  await expect(header).toHaveAttribute("aria-sort", "ascending");
  await expect(participantColumn(page).first()).toHaveText("Anton Alpha");
  await expect(participantColumn(page).last()).toHaveText("Zora Zulu");

  await sortButton.click();
  await expect(header).toHaveAttribute("aria-sort", "descending");
  await expect(participantColumn(page).first()).toHaveText("Zora Zulu");

  const statusHeader = table.locator("th", { hasText: "Status" });
  await statusHeader.getByRole("button").click();
  await expect(statusHeader).toHaveAttribute("aria-sort", "ascending");
  await expect(header).not.toHaveAttribute("aria-sort", /.+/);

  expect(browserErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});

test("filtering hides non-matching rows and shows a count", async ({ page }) => {
  const { browserErrors, failedRequests } = trackPageIssues(page);
  const { campUrl } = await setupAdminWithCamp(page);
  await createParticipant(page, campUrl, "Zora", "Zulu");
  await createParticipant(page, campUrl, "Anton", "Alpha");
  await createParticipant(page, campUrl, "Berta", "Beta");
  await page.goto(campUrl);

  const section = page.locator(".participant-settlements");
  const filterInput = section.locator(".table-tools input[type=search]");
  await expect(filterInput).toBeVisible();

  await filterInput.fill("berta");
  await expect(participantColumn(page)).toHaveCount(1);
  await expect(participantColumn(page).first()).toHaveText("Berta Beta");
  await expect(section.locator(".table-tools__count")).toHaveText("1 von 3 Zeilen");

  await filterInput.fill("");
  await expect(participantColumn(page)).toHaveCount(3);
  await expect(section.locator(".table-tools__count")).toBeHidden();

  expect(browserErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});

test("empty table keeps its placeholder row under sort and filter", async ({ page }) => {
  const { browserErrors, failedRequests } = trackPageIssues(page);
  const { campUrl } = await setupAdminWithCamp(page);
  await page.goto(campUrl);

  const runsTable = page.locator("table", { hasText: "Noch keine Abrechnungsläufe gespeichert." }).first();
  await runsTable.locator("th", { hasText: "Version" }).getByRole("button").click();
  await expect(runsTable.getByText("Noch keine Abrechnungsläufe gespeichert.")).toBeVisible();

  const settlementsSection = page.locator(".participant-settlements");
  await settlementsSection.locator(".table-tools input[type=search]").fill("niemand");
  await expect(settlementsSection.getByText("Noch keine Teilnehmer vorhanden.")).toBeVisible();

  expect(browserErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});

test("responsive table offers a sort select on mobile", async ({ page }) => {
  const { browserErrors, failedRequests } = trackPageIssues(page);
  const { campUrl } = await setupAdminWithCamp(page);
  await createParticipant(page, campUrl, "Mia", "Mobil");

  await page.setViewportSize({ width: 390, height: 844 });
  const bookingsSection = page.locator("section", { hasText: "Buchungen" }).filter({ has: page.locator("table[data-sortable]") }).first();
  const sortSelect = bookingsSection.locator(".table-tools__sort select");
  await expect(sortSelect).toBeVisible();
  await expect(bookingsSection.locator(".table-tools input[type=search]")).toBeVisible();

  const optionLabels = await sortSelect.locator("option").allTextContents();
  expect(optionLabels).toContain("Standard");
  expect(optionLabels).toContain("Datum (aufsteigend)");
  expect(optionLabels).toContain("Summe (absteigend)");

  await sortSelect.selectOption({ label: "Datum (aufsteigend)" });
  await expect(bookingsSection.locator("th", { hasText: "Datum" })).toHaveAttribute("aria-sort", "ascending");

  await page.setViewportSize({ width: 1280, height: 800 });
  await expect(sortSelect).toBeHidden();

  expect(browserErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});

test("enhanced admin page keeps ARIA references intact and uses real buttons", async ({ page }) => {
  const { browserErrors, failedRequests } = trackPageIssues(page);
  const { campUrl } = await setupAdminWithCamp(page);
  await createParticipant(page, campUrl, "Aria", "Check");
  await page.goto(campUrl);

  const violations = await page.evaluate(() => {
    const ids = new Set([...document.querySelectorAll("[id]")].map((element) => element.id));
    const found = [];
    for (const element of document.querySelectorAll("[aria-describedby], [aria-labelledby]")) {
      for (const attribute of ["aria-describedby", "aria-labelledby"]) {
        for (const reference of (element.getAttribute(attribute) || "").split(/\s+/).filter(Boolean)) {
          if (!ids.has(reference)) found.push(`${attribute} -> ${reference}`);
        }
      }
    }
    return found;
  });
  expect(violations).toEqual([]);

  const sortControls = page.locator("table[data-sortable] th .table-sort-button");
  expect(await sortControls.count()).toBeGreaterThan(0);
  const nonButtonControls = await page.evaluate(
    () => [...document.querySelectorAll(".table-sort-button")].filter((el) => el.tagName !== "BUTTON").length,
  );
  expect(nonButtonControls).toBe(0);

  expect(browserErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});
