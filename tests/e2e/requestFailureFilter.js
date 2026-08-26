"use strict";

const ADMIN_ICON_PATH = "/static/billing/icons/admin-icon-192.png";
const ABORTED_FAILURE_TEXT_PATTERNS = ["NS_BINDING_ABORTED", "ERR_ABORTED"];
const ADMIN_MOBILE_CANCELLED_FAILURE_TEXT = "Load request cancelled";
const LOCAL_REQUEST_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);
const PWA_MANIFEST_PATHS = new Set([
  "/manifest.webmanifest",
  "/kiosk/manifest.webmanifest",
  "/central/kiosk/manifest.webmanifest",
]);
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

function parseLocalRequestUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    if (!LOCAL_REQUEST_HOSTS.has(url.hostname) || url.search || url.hash) {
      return null;
    }
    return url;
  } catch {
    return null;
  }
}

function hasKnownAbortedFailure(errorText) {
  return ABORTED_FAILURE_TEXT_PATTERNS.some(
    (pattern) => errorText === pattern || errorText.endsWith(`::${pattern}`),
  );
}

function isBenignPageRequestFailure(details) {
  if (details.method !== "GET") {
    return false;
  }
  const url = parseLocalRequestUrl(details.url);
  if (!url || !hasKnownAbortedFailure(details.errorText)) {
    return false;
  }
  return url.pathname === ADMIN_ICON_PATH || PWA_MANIFEST_PATHS.has(url.pathname);
}

function isAllowedAdminMobileCancelledFailure(details) {
  if (details.method !== "GET" || details.errorText !== ADMIN_MOBILE_CANCELLED_FAILURE_TEXT) {
    return false;
  }
  const url = parseLocalRequestUrl(details.url);
  return url !== null && ADMIN_MOBILE_CANCELLED_PATHS.has(url.pathname);
}

module.exports = {
  isAllowedAdminMobileCancelledFailure,
  isBenignPageRequestFailure,
  requestFailureDetails,
};
