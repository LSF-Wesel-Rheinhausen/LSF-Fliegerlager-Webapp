"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { isBenignPageRequestFailure } = require("./e2e/requestFailureFilter");

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
