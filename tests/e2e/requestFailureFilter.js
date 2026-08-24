"use strict";

const ADMIN_ICON_PATH = "/static/billing/icons/admin-icon-192.png";
const ABORTED_FAILURE_TEXT_PATTERNS = ["NS_BINDING_ABORTED", "ERR_ABORTED"];
const ADMIN_MOBILE_CANCELLED_FAILURE_TEXT = "Load request cancelled";
const ADMIN_MOBILE_CANCELLED_PATHS = new Set([
  "/service-worker.js",
  "/manifest.webmanifest",
  "/static/admin/css/changelists.css",
  "/static/admin/img/search.svg",
  "/static/admin/img/icon-no.svg",
  "/static/admin/img/sorting-icons.svg",
  "/static/admin/img/tooltag-add.svg",
]);

function requestFailureDetails(request) {
  const failure = typeof request.failure === "function" ? request.failure() : null;
  return {
    method: typeof request.method === "function" ? request.method() : "",
    url: typeof request.url === "function" ? request.url() : "",
    errorText: failure?.errorText ?? "",
  };
}

function isBenignPageRequestFailure(details) {
  if (details.method !== "GET") {
    return false;
  }
  if (details.url.endsWith(".webmanifest") || details.url.includes("/manifest")) {
    return true;
  }
  if (!details.url.endsWith(ADMIN_ICON_PATH)) {
    return false;
  }
  return ABORTED_FAILURE_TEXT_PATTERNS.some((pattern) => details.errorText.includes(pattern));
}

function isAllowedAdminMobileCancelledFailure(details) {
  if (details.method !== "GET" || details.errorText !== ADMIN_MOBILE_CANCELLED_FAILURE_TEXT) {
    return false;
  }
  try {
    const url = new URL(details.url);
    return ADMIN_MOBILE_CANCELLED_PATHS.has(url.pathname) && !url.search && !url.hash;
  } catch {
    return false;
  }
}

module.exports = {
  isAllowedAdminMobileCancelledFailure,
  isBenignPageRequestFailure,
  requestFailureDetails,
};
