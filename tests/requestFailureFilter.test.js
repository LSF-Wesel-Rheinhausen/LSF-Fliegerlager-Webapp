"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  isAllowedAdminMobileCancelledFailure,
  isBenignPageRequestFailure,
} = require("./e2e/requestFailureFilter");

const allowedAdminMobilePaths = [
  "/service-worker.js",
  "/manifest.webmanifest",
  "/static/admin/css/changelists.css",
  "/static/admin/img/search.svg",
  "/static/admin/img/icon-no.svg",
];

test("allows only exact cancelled GETs for the documented admin mobile paths", () => {
  for (const path of allowedAdminMobilePaths) {
    assert.equal(
      isAllowedAdminMobileCancelledFailure({
        method: "GET",
        url: `http://localhost:3102${path}?cache=1`,
        errorText: "Load request cancelled",
      }),
      true,
      path,
    );
  }
});

test("rejects other methods, errors, and paths from the admin mobile allowlist", () => {
  const base = {
    method: "GET",
    url: "http://localhost:3102/static/admin/img/search.svg",
    errorText: "Load request cancelled",
  };
  for (const details of [
    { ...base, method: "POST" },
    { ...base, errorText: "NS_BINDING_ABORTED" },
    { ...base, errorText: "Load request cancelled " },
    { ...base, url: "http://localhost:3102/static/admin/img/icon-yes.svg" },
    { ...base, url: "http://localhost:3102/static/billing/admin-mobile.css" },
    { ...base, url: "http://localhost:3102/static/billing/admin-mobile.js" },
    { ...base, url: "http://localhost:3102/static/billing/logo.jpg" },
    { ...base, url: "not-a-url" },
  ]) {
    assert.equal(isAllowedAdminMobileCancelledFailure(details), false, JSON.stringify(details));
  }
});

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
