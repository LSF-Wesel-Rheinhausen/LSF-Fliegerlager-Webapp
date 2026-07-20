const { expect, test } = require("./fixtures");

test("Private kiosk installs its scoped PWA and serves the offline fallback", async ({
  browserName,
  context,
  page,
  request,
}) => {
  const manifestResponse = await request.get("/kiosk/manifest.webmanifest");
  expect(manifestResponse.ok()).toBeTruthy();
  const manifest = await manifestResponse.json();
  expect(manifest.scope).toBe("/kiosk/");
  expect(manifest.start_url).toBe("/kiosk/");
  expect(manifest.icons.map((icon) => icon.sizes)).toEqual(expect.arrayContaining(["192x192", "512x512"]));

  await page.goto("/kiosk/login/");
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute("href", "/kiosk/manifest.webmanifest");
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload();
  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBeTruthy();

  const registrations = await page.evaluate(async () => {
    const values = await navigator.serviceWorker.getRegistrations();
    return values.map((registration) => new URL(registration.scope).pathname);
  });
  expect(registrations).toContain("/kiosk/");

  if (browserName === "chromium") {
    await context.setOffline(true);
    await page.goto("/kiosk/login/?offline-check=1");
    await expect(page.getByRole("heading", { name: "Du bist offline" })).toBeVisible();
    await context.setOffline(false);
  }
});

test("Central kiosk exposes a distinct scope and no notification settings route", async ({ page, request }) => {
  const manifestResponse = await request.get("/central/kiosk/manifest.webmanifest");
  expect(manifestResponse.ok()).toBeTruthy();
  const manifest = await manifestResponse.json();
  expect(manifest.scope).toBe("/central/kiosk/");
  expect(manifest.start_url).toBe("/central/kiosk/");

  await page.goto("/central/kiosk/login/");
  await expect(page).toHaveURL(/\/central\/kiosk\/login\/$/);
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute(
    "href",
    "/central/kiosk/manifest.webmanifest",
  );
  expect((await request.get("/central/kiosk/notifications/")).status()).toBe(404);
});
