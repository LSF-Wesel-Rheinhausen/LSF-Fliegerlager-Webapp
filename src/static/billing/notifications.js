(() => {
  const root = document.querySelector("[data-notification-settings]");
  if (!root) return;
  const status = root.querySelector("[data-notification-status]");
  const error = root.querySelector("[data-notification-error]");
  const form = root.querySelector("[data-notification-subscribe-form]");

  const csrfToken = () => root.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";

  const decodePublicKey = (value) => {
    const padding = "=".repeat((4 - value.length % 4) % 4);
    const bytes = atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(bytes, (character) => character.charCodeAt(0));
  };

  const showError = (message) => {
    error.textContent = message;
    error.hidden = false;
  };

  const initializeStatus = async () => {
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
      status.textContent = "Nicht unterstützt";
      if (form) form.hidden = true;
      return;
    }
    if (Notification.permission === "denied") {
      status.textContent = "Im Browser blockiert";
      return;
    }
    const registration = await navigator.serviceWorker.ready;
    status.textContent = await registration.pushManager.getSubscription() ? "Aktiv" : "Nicht aktiv";
  };

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.hidden = true;
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") throw new Error("Benachrichtigungen wurden im Browser nicht erlaubt.");
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: decodePublicKey(root.dataset.publicKey),
      });
      const data = new FormData(form);
      const response = await fetch(root.dataset.subscribeUrl, {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken()},
        body: JSON.stringify({
          ...subscription.toJSON(),
          device_name: data.get("device_name"),
          categories: data.getAll("category"),
        }),
      });
      if (!response.ok) throw new Error((await response.json()).error || "Gerät konnte nicht registriert werden.");
      window.location.reload();
    } catch (exception) {
      showError(exception.message || "Benachrichtigungen konnten nicht aktiviert werden.");
    }
  });

  root.querySelectorAll("[data-revoke-subscription]").forEach((button) => {
    button.addEventListener("click", async () => {
      const url = `${root.dataset.revokeBaseUrl}${button.dataset.revokeSubscription}/revoke/`;
      const response = await fetch(url, {method: "POST", headers: {"X-CSRFToken": csrfToken()}});
      if (response.ok) window.location.reload();
      else showError("Gerät konnte nicht entfernt werden.");
    });
  });

  root.querySelectorAll("[data-test-subscription]").forEach((button) => {
    button.addEventListener("click", async () => {
      const url = `${root.dataset.revokeBaseUrl}${button.dataset.testSubscription}/test/`;
      const response = await fetch(url, {method: "POST", headers: {"X-CSRFToken": csrfToken()}});
      if (response.ok) status.textContent = "Test eingeplant";
      else showError("Testbenachrichtigung konnte nicht eingeplant werden.");
    });
  });

  initializeStatus().catch(() => {
    status.textContent = "Nicht verfügbar";
  });
})();
