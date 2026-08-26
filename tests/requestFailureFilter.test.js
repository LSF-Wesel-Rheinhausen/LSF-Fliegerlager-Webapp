"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  isAllowedAdminMobileCancelledFailure,
  isBenignPageRequestFailure,
} = require("./e2e/requestFailureFilter");

test("ignores aborted admin icon requests", () => {
  assert.equal(
    isBenignPageRequestFailure({
      method: "GET",
      url: "http://localhost:3102/static/billing/icons/admin-icon-192.png",
      errorText: "NS_BINDING_ABORTED",
    }),
    true,
  );
});

test("keeps unrelated request failures visible", () => {
  assert.equal(
    isBenignPageRequestFailure({
      method: "GET",
      url: "http://localhost:3102/static/billing/app-v8.css",
      errorText: "NS_BINDING_ABORTED",
    }),
    false,
  );
  assert.equal(
    isBenignPageRequestFailure({
      method: "GET",
      url: "http://localhost:3102/static/billing/icons/admin-icon-192.png",
      errorText: "NS_ERROR_CONNECTION_REFUSED",
    }),
    false,
  );
  assert.equal(
    isBenignPageRequestFailure({
      method: "POST",
      url: "http://localhost:3102/static/billing/icons/admin-icon-192.png",
      errorText: "NS_BINDING_ABORTED",
    }),
    false,
  );
});

test("allows only known aborted failures for canonical PWA manifests", () => {
  const paths = [
    "/manifest.webmanifest",
    "/kiosk/manifest.webmanifest",
    "/central/kiosk/manifest.webmanifest",
  ];
  const errorTexts = ["NS_BINDING_ABORTED", "ERR_ABORTED", "net::ERR_ABORTED"];

  for (const path of paths) {
    for (const errorText of errorTexts) {
      const details = {
        method: "GET",
        url: `http://localhost:3102${path}`,
        errorText,
      };
      assert.equal(isBenignPageRequestFailure(details), true, `${path} ${errorText}`);
    }
  }

  const adminCancellation = {
    method: "GET",
    url: "http://localhost:3102/manifest.webmanifest",
    errorText: "Load request cancelled",
  };
  assert.equal(isBenignPageRequestFailure(adminCancellation), false);
  assert.equal(isAllowedAdminMobileCancelledFailure(adminCancellation), true);
});

test("keeps manifest network, HTTP, URL, and host failures visible", () => {
  const failures = [
    "DNS failure",
    "NS_ERROR_CONNECTION_REFUSED",
    "SSL_ERROR_BAD_CERT_DOMAIN",
    "404 Not Found",
  ];
  for (const errorText of failures) {
    const details = {
      method: "GET",
      url: "http://localhost:3102/manifest.webmanifest",
      errorText,
    };
    assert.equal(isBenignPageRequestFailure(details), false, errorText);
    assert.equal(isAllowedAdminMobileCancelledFailure(details), false, errorText);
  }

  for (const url of [
    "http://localhost:3102/manifest.webmanifest?cache=1",
    "http://localhost:3102/manifest.webmanifest#fragment",
    "http://localhost.evil.test:3102/manifest.webmanifest",
    "https://evil.example/manifest.webmanifest",
    "http://localhost:3102/not-a-manifest.webmanifest",
    "http://localhost:3102/assets/manifest.webmanifest",
  ]) {
    const details = {
      method: "GET",
      url,
      errorText: "NS_BINDING_ABORTED",
    };
    assert.equal(isBenignPageRequestFailure(details), false, url);
    assert.equal(isAllowedAdminMobileCancelledFailure(details), false, url);
  }
});

test("recognizes IPv6 loopback as a local request origin", () => {
  const manifestAbort = {
    method: "GET",
    url: "http://[::1]:3102/manifest.webmanifest",
    errorText: "NS_BINDING_ABORTED",
  };
  assert.equal(isBenignPageRequestFailure(manifestAbort), true);

  const adminCancellation = {
    ...manifestAbort,
    errorText: "Load request cancelled",
  };
  assert.equal(isBenignPageRequestFailure(adminCancellation), false);
  assert.equal(isAllowedAdminMobileCancelledFailure(adminCancellation), true);

  const nonLocalIpv6 = {
    ...manifestAbort,
    url: "http://[2001:db8::1]:3102/manifest.webmanifest",
  };
  assert.equal(isBenignPageRequestFailure(nonLocalIpv6), false);
  assert.equal(isAllowedAdminMobileCancelledFailure({ ...nonLocalIpv6, errorText: "Load request cancelled" }), false);
});

test("allows only the exact admin mobile cancellation contract", () => {
  const allowedPaths = [
    "/service-worker.js",
    "/manifest.webmanifest",
    "/static/admin/css/changelists.css",
    "/static/admin/img/search.svg",
    "/static/admin/img/icon-no.svg",
    "/static/admin/img/sorting-icons.svg",
    "/static/admin/img/tooltag-add.svg",
  ];

  for (const path of allowedPaths) {
    assert.equal(
      isAllowedAdminMobileCancelledFailure({
        method: "GET",
        url: `http://localhost:3102${path}`,
        errorText: "Load request cancelled",
      }),
      true,
      path,
    );
  }
});

test("does not hide product, method, path, or error failures", () => {
  const cases = [
    {
      method: "POST",
      url: "http://localhost:3102/service-worker.js",
      errorText: "Load request cancelled",
    },
    {
      method: "GET",
      url: "http://localhost:3102/static/billing/admin-mobile.css",
      errorText: "Load request cancelled",
    },
    {
      method: "GET",
      url: "http://localhost:3102/static/billing/admin-mobile.js",
      errorText: "Load request cancelled",
    },
    {
      method: "GET",
      url: "http://localhost:3102/static/admin/img/search.svg?cache=1",
      errorText: "Load request cancelled",
    },
    {
      method: "GET",
      url: "http://localhost:3102/static/admin/img/search.svg",
      errorText: "NS_BINDING_ABORTED",
    },
    {
      method: "GET",
      url: "http://localhost:3102/static/admin/img/search.svg",
      errorText: "DNS failure",
    },
    {
      method: "GET",
      url: "http://localhost:3102/static/admin/img/not-allowed.svg",
      errorText: "Load request cancelled",
    },
    {
      method: "GET",
      url: "http://localhost:3102/static/admin/img/sorting-icons.svg?cache=1",
      errorText: "Load request cancelled",
    },
    {
      method: "GET",
      url: "http://localhost:3102/static/admin/img/tooltag-add.svg#fragment",
      errorText: "Load request cancelled",
    },
    {
      method: "GET",
      url: "http://localhost:3102/static/admin/img/sorting-icons.svg",
      errorText: "NS_BINDING_ABORTED",
    },
    {
      method: "POST",
      url: "http://localhost:3102/static/admin/img/tooltag-add.svg",
      errorText: "Load request cancelled",
    },
    {
      method: "GET",
      url: "http://localhost:3102/static/admin/img/sorting-icon.svg",
      errorText: "Load request cancelled",
    },
    {
      method: "GET",
      url: "http://localhost:3102/static/billing/admin-mobile.js",
      errorText: "Load request cancelled",
    },
  ];

  for (const details of cases) {
    assert.equal(isAllowedAdminMobileCancelledFailure(details), false, JSON.stringify(details));
  }
});
