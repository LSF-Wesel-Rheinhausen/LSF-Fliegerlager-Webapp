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

test("allows only the exact admin mobile cancellation contract", () => {
  const allowedPaths = [
    "/service-worker.js",
    "/manifest.webmanifest",
    "/static/admin/css/changelists.css",
    "/static/admin/img/search.svg",
    "/static/admin/img/icon-no.svg",
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
  ];

  for (const details of cases) {
    assert.equal(isAllowedAdminMobileCancelledFailure(details), false, JSON.stringify(details));
  }
});
