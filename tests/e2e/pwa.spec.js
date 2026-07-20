const { expect, test } = require("./fixtures");

async function expectInstallGuide(browser, baseURL, userAgent, expectedInstructions) {
  const context = await browser.newContext({ baseURL, userAgent });
  const page = await context.newPage();

  await page.goto("/kiosk/login/");
  await page.getByRole("button", { name: "Installieren", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "App installieren" });
  await expect(dialog).toBeVisible();
  await expect(dialog.locator("[data-pwa-install-platform]:visible")).toContainText(expectedInstructions);

  await context.close();
}

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
  await expect(page.locator("[data-pwa-install]")).toHaveCount(0);
  expect((await request.get("/central/kiosk/notifications/")).status()).toBe(404);
});

test("Install guide adapts to iOS and Android", async ({ baseURL, browser }) => {
  await expectInstallGuide(
    browser,
    baseURL,
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
    "Zum Home-Bildschirm",
  );
  await expectInstallGuide(
    browser,
    baseURL,
    "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/136.0.0.0 Mobile Safari/537.36",
    "Browsermenü",
  );
});

test("Notification enrollment updates the current page without reload", async ({ page }) => {
  await page.setContent(`
    <section
      data-notification-settings
      data-public-key="AQ"
      data-subscribe-url="/notifications/subscriptions/"
      data-revoke-base-url="/notifications/subscriptions/"
    >
      <span data-notification-status>Wird geprüft</span>
      <form data-notification-subscribe-form>
        <input name="csrfmiddlewaretoken" value="test-csrf">
        <input name="device_name" value="Mein Smartphone">
        <input type="checkbox" name="category" value="shifts" checked>
        <button type="submit" data-notification-submit>Benachrichtigungen aktivieren</button>
      </form>
      <ul data-notification-device-list>
        <li data-notification-empty>Noch kein Gerät registriert.</li>
      </ul>
      <p data-notification-error hidden></p>
    </section>
  `);
  await page.evaluate(() => {
    const subscription = {
      endpoint: "https://push.example.test/browser-device",
      toJSON: () => ({
        endpoint: "https://push.example.test/browser-device",
        keys: { p256dh: "browser-key", auth: "browser-secret" },
      }),
      unsubscribe: async () => true,
    };
    let currentSubscription = null;
    Object.defineProperty(window, "Notification", {
      configurable: true,
      value: {
        permission: "default",
        requestPermission: async () => {
          window.Notification.permission = "granted";
          return "granted";
        },
      },
    });
    Object.defineProperty(navigator, "serviceWorker", {
      configurable: true,
      value: {
        ready: Promise.resolve({
          pushManager: {
            getSubscription: async () => currentSubscription,
            subscribe: async () => {
              currentSubscription = subscription;
              return subscription;
            },
          },
        }),
      },
    });
    Object.defineProperty(window, "PushManager", { configurable: true, value: function PushManager() {} });
    window.fetch = async (url, options) => {
      if (url.endsWith("/revoke/")) return new Response(null, { status: 204 });
      if (options?.method === "POST") {
        return new Response(JSON.stringify({
          device: {
            id: 42,
            device_name: "Mein Smartphone",
            last_success_at: null,
            endpoint_fingerprint: "current-device",
          },
        }), { status: 201, headers: { "Content-Type": "application/json" } });
      }
      return new Response(null, { status: 404 });
    };
    window.__notificationPageMarker = "retained";
  });
  await page.addScriptTag({ path: "src/static/billing/notifications.js" });

  await page.getByRole("button", { name: "Benachrichtigungen aktivieren" }).click();
  await expect(page.locator("[data-notification-status]")).toHaveText("Aktiv");
  await expect(page.locator("[data-notification-device-list]")).toContainText("Mein Smartphone");
  await expect.poll(() => page.evaluate(() => window.__notificationPageMarker)).toBe("retained");

  await page.getByRole("button", { name: "Entfernen" }).click();
  await expect(page.locator("[data-notification-device-list]")).toContainText("Noch kein Gerät registriert.");
});
