const { expect, test } = require("./fixtures");

test.use({ serviceWorkers: "block" });
test.describe.configure({ mode: "serial" });

test("Recovery-Seite behält Origin für CSRF-POST ohne Token im Referer", async ({ page, baseURL }) => {
  await page.goto("/account/recovery/");
  const csrfToken = await page.locator('input[name="csrfmiddlewaretoken"]').inputValue();

  const recoveryToken = "e2e-referrer-policy-token";
  const recoveryPath = `/account/recovery/confirm/${recoveryToken}/`;
  const getResponse = await page.goto(recoveryPath);

  expect(getResponse).not.toBeNull();
  expect(getResponse.status()).toBe(400);
  expect(getResponse.headers()["cache-control"]).toBe("no-store");
  expect(getResponse.headers()["referrer-policy"]).toBe("strict-origin");

  const postRequestPromise = page.waitForRequest(
    (request) => request.method() === "POST" && new URL(request.url()).pathname === recoveryPath,
  );
  const postResponsePromise = page.waitForResponse(
    (response) => response.request().method() === "POST" && new URL(response.url()).pathname === recoveryPath,
  );

  await page.evaluate(
    ({ csrfToken, recoveryPath }) => {
      const form = document.createElement("form");
      form.method = "post";
      form.action = recoveryPath;

      const csrf = document.createElement("input");
      csrf.type = "hidden";
      csrf.name = "csrfmiddlewaretoken";
      csrf.value = csrfToken;
      form.appendChild(csrf);

      document.body.appendChild(form);
      form.submit();
    },
    { csrfToken, recoveryPath },
  );

  const postRequest = await postRequestPromise;
  const postResponse = await postResponsePromise;
  const expectedOrigin = new URL(baseURL).origin;

  expect(postRequest.headers()["origin"]).toBe(expectedOrigin);
  expect(postRequest.headers()["referer"]).toBe(`${expectedOrigin}/`);
  expect(postRequest.headers()["referer"]).not.toContain(recoveryToken);
  expect(postResponse.status()).toBe(400);
});
