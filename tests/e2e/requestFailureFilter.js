"use strict";

const ADMIN_ICON_PATH = "/static/billing/icons/admin-icon-192.png";
const ABORTED_FAILURE_TEXT_PATTERNS = ["NS_BINDING_ABORTED", "ERR_ABORTED"];

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
  if (!details.url.endsWith(ADMIN_ICON_PATH)) {
    return false;
  }
  return ABORTED_FAILURE_TEXT_PATTERNS.some((pattern) => details.errorText.includes(pattern));
}

module.exports = {
  isBenignPageRequestFailure,
  requestFailureDetails,
};
