(() => {
  const root = document.querySelector("[data-notification-settings]");
  if (!root) return;

  const status = root.querySelector("[data-notification-status]");
  const error = root.querySelector("[data-notification-error]");
  const form = root.querySelector("[data-notification-subscribe-form]");
  const submitButton = root.querySelector("[data-notification-submit]");
  const deviceList = root.querySelector("[data-notification-device-list]");
  const installGuidance = root.querySelector("[data-notification-install-guidance]");
  let registration;
  let browserSubscription;
  let currentDeviceId;

  const csrfToken = () => root.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
  const isIos = () =>
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const isStandalone = () =>
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true ||
    document.referrer.startsWith("android-app://");

  const decodePublicKey = (value) => {
    const padding = "=".repeat((4 - (value.length % 4)) % 4);
    const bytes = atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(bytes, (character) => character.charCodeAt(0));
  };

  const endpointFingerprint = async (endpoint) => {
    if (!window.crypto?.subtle) return null;
    const bytes = new TextEncoder().encode(endpoint);
    const digest = await window.crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  };

  const setStatus = (message, active = false) => {
    status.textContent = message;
    status.classList.toggle("status-badge--ok", active);
  };

  const showError = (message) => {
    error.textContent = message;
    error.hidden = false;
  };

  const clearError = () => {
    error.hidden = true;
    error.textContent = "";
  };

  const setBusy = (busy, label) => {
    if (!submitButton) return;
    if (!submitButton.dataset.defaultLabel) submitButton.dataset.defaultLabel = submitButton.textContent;
    submitButton.disabled = busy;
    submitButton.textContent = busy ? label : submitButton.dataset.defaultLabel;
    form?.setAttribute("aria-busy", busy ? "true" : "false");
  };

  const installationAllowsNotifications = () => {
    if (!isIos()) {
      if (installGuidance) {
        installGuidance.textContent = "Installation optional – Benachrichtigungen können direkt im Browser aktiviert werden.";
      }
      return true;
    }
    if (isStandalone()) {
      if (installGuidance) {
        installGuidance.textContent = "Als Home-Screen-App installiert – Benachrichtigungen können aktiviert werden.";
      }
      return true;
    }
    if (installGuidance) {
      installGuidance.textContent =
        "Installiere die App zuerst zum Home-Bildschirm. iOS und iPadOS erlauben Web Push nur in der installierten App.";
    }
    return false;
  };

  const serviceWorkerReady = async () => {
    if (registration) return registration;
    let timeoutId;
    try {
      registration = await Promise.race([
        navigator.serviceWorker.ready,
        new Promise((_, reject) => {
          timeoutId = window.setTimeout(() => reject(new Error("Service Worker nicht verfügbar.")), 12000);
        }),
      ]);
      return registration;
    } finally {
      window.clearTimeout(timeoutId);
    }
  };

  const formatLastSuccess = (value) => {
    if (!value) return "Noch nicht erreicht";
    return `Zuletzt erreicht: ${new Intl.DateTimeFormat("de-DE", {
      dateStyle: "short",
      timeStyle: "short",
    }).format(new Date(value))}`;
  };

  const categoryOptions = Array.from(form?.querySelectorAll('input[name="category"]') || []).map((input) => ({
    value: input.value,
    label: input.closest("label")?.textContent.trim() || input.value,
  }));

  const preferencesDialogElement = (device) => {
    const dialog = document.createElement("dialog");
    dialog.className = "notification-preferences-dialog";
    const titleId = `notification-preferences-title-${device.id}`;
    dialog.setAttribute("aria-labelledby", titleId);
    const preferencesForm = document.createElement("form");
    preferencesForm.className = "form-grid";
    preferencesForm.dataset.preferencesForm = String(device.id);
    const title = document.createElement("h3");
    title.id = titleId;
    title.textContent = "Nachrichten auswählen";
    const fieldset = document.createElement("fieldset");
    const legend = document.createElement("legend");
    legend.textContent = `Kategorien für ${device.device_name}`;
    fieldset.append(legend);
    categoryOptions.forEach((category) => {
      const label = document.createElement("label");
      label.className = "checkbox-row";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.name = "category";
      checkbox.value = category.value;
      checkbox.checked = (device.categories || []).includes(category.value);
      const text = document.createElement("span");
      text.textContent = category.label;
      label.append(checkbox, text);
      fieldset.append(label);
    });
    const preferencesError = document.createElement("p");
    preferencesError.className = "message error";
    preferencesError.dataset.preferencesError = "";
    preferencesError.setAttribute("role", "alert");
    preferencesError.hidden = true;
    const dialogActions = document.createElement("div");
    dialogActions.className = "actions";
    const cancelButton = document.createElement("button");
    cancelButton.className = "button button-secondary";
    cancelButton.type = "button";
    cancelButton.dataset.closeDialog = "";
    cancelButton.textContent = "Abbrechen";
    const saveButton = document.createElement("button");
    saveButton.className = "button";
    saveButton.type = "submit";
    saveButton.textContent = "Speichern";
    dialogActions.append(cancelButton, saveButton);
    preferencesForm.append(title, fieldset, preferencesError, dialogActions);
    dialog.append(preferencesForm);
    return dialog;
  };

  const deviceElement = (device, current = false) => {
    const item = document.createElement("li");
    item.dataset.notificationDevice = String(device.id);
    item.dataset.endpointFingerprint = device.endpoint_fingerprint;

    const details = document.createElement("div");
    const name = document.createElement("span");
    name.className = "device-list__name";
    const strong = document.createElement("strong");
    strong.dataset.notificationDeviceName = "";
    strong.textContent = device.device_name;
    const currentBadge = document.createElement("span");
    currentBadge.className = "status-badge status-badge--ok";
    currentBadge.dataset.notificationCurrent = "";
    currentBadge.textContent = "Dieses Gerät";
    currentBadge.hidden = !current;
    name.append(strong, currentBadge);
    const lastSuccess = document.createElement("span");
    lastSuccess.className = "hint";
    lastSuccess.textContent = formatLastSuccess(device.last_success_at);
    details.append(name, lastSuccess);

    const actions = document.createElement("div");
    actions.className = "actions";
    const testButton = document.createElement("button");
    testButton.className = "button button-secondary";
    testButton.type = "button";
    testButton.dataset.testSubscription = String(device.id);
    testButton.textContent = "Testen";
    const renameButton = document.createElement("button");
    renameButton.className = "button button-secondary";
    renameButton.type = "button";
    renameButton.dataset.renameSubscription = String(device.id);
    renameButton.textContent = "Umbenennen";
    const preferencesButton = document.createElement("button");
    preferencesButton.className = "button button-secondary";
    preferencesButton.type = "button";
    preferencesButton.dataset.preferencesSubscription = String(device.id);
    preferencesButton.textContent = "Nachrichten auswählen";
    const revokeButton = document.createElement("button");
    revokeButton.className = "button button-danger";
    revokeButton.type = "button";
    revokeButton.dataset.revokeSubscription = String(device.id);
    revokeButton.textContent = "Entfernen";
    actions.append(preferencesButton, renameButton, testButton, revokeButton);

    const preferencesDialog = preferencesDialogElement(device);
    const dialog = document.createElement("dialog");
    dialog.className = "notification-rename-dialog";
    const titleId = `notification-rename-title-${device.id}`;
    dialog.setAttribute("aria-labelledby", titleId);
    const renameForm = document.createElement("form");
    renameForm.className = "form-grid";
    renameForm.dataset.renameForm = String(device.id);
    const title = document.createElement("h3");
    title.id = titleId;
    title.textContent = "Gerät umbenennen";
    const label = document.createElement("label");
    const inputId = `notification-rename-name-${device.id}`;
    label.htmlFor = inputId;
    label.textContent = "Gerätename";
    const input = document.createElement("input");
    input.id = inputId;
    input.name = "device_name";
    input.maxLength = 80;
    input.required = true;
    input.value = device.device_name;
    const renameError = document.createElement("p");
    renameError.className = "message error";
    renameError.dataset.renameError = "";
    renameError.setAttribute("role", "alert");
    renameError.hidden = true;
    const dialogActions = document.createElement("div");
    dialogActions.className = "actions";
    const cancelButton = document.createElement("button");
    cancelButton.className = "button button-secondary";
    cancelButton.type = "button";
    cancelButton.dataset.closeDialog = "";
    cancelButton.textContent = "Abbrechen";
    const saveButton = document.createElement("button");
    saveButton.className = "button";
    saveButton.type = "submit";
    saveButton.textContent = "Speichern";
    dialogActions.append(cancelButton, saveButton);
    renameForm.append(title, label, input, renameError, dialogActions);
    dialog.append(renameForm);

    item.append(details, actions, preferencesDialog, dialog);
    return item;
  };

  const ensureEmptyState = () => {
    if (!deviceList || deviceList.querySelector("[data-notification-device]")) return;
    const item = document.createElement("li");
    item.className = "hint";
    item.dataset.notificationEmpty = "";
    item.textContent = "Noch kein Gerät registriert.";
    deviceList.append(item);
  };

  const upsertDevice = (device, current = false) => {
    if (!deviceList) return;
    deviceList.querySelector("[data-notification-empty]")?.remove();
    const existing = deviceList.querySelector(`[data-notification-device="${device.id}"]`);
    const item = deviceElement(device, current);
    if (existing) existing.replaceWith(item);
    else deviceList.prepend(item);
    if (current) currentDeviceId = String(device.id);
  };

  const markCurrentDevice = async () => {
    if (!browserSubscription || !deviceList) return false;
    const fingerprint = await endpointFingerprint(browserSubscription.endpoint);
    if (!fingerprint) return false;
    const item = Array.from(deviceList.querySelectorAll("[data-notification-device]")).find(
      (element) => element.dataset.endpointFingerprint === fingerprint,
    );
    if (!item) return false;
    item.querySelector("[data-notification-current]").hidden = false;
    currentDeviceId = item.dataset.notificationDevice;
    return true;
  };

  const initializeStatus = async () => {
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
      setStatus("Nicht unterstützt");
      if (form) form.hidden = true;
      return;
    }
    if (!installationAllowsNotifications()) {
      setStatus("Installation erforderlich");
      if (submitButton) submitButton.disabled = true;
      return;
    }
    if (submitButton) submitButton.disabled = false;
    if (Notification.permission === "denied") {
      setStatus("Im Browser blockiert");
      if (submitButton) submitButton.disabled = true;
      return;
    }
    setStatus("Wird vorbereitet");
    const worker = await serviceWorkerReady();
    browserSubscription = await worker.pushManager.getSubscription();
    const isCurrentDevice = await markCurrentDevice();
    setStatus(isCurrentDevice ? "Aktiv" : "Nicht aktiv", isCurrentDevice);
  };

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearError();
    setBusy(true, "Wird aktiviert …");
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") throw new Error("Benachrichtigungen wurden im Browser nicht erlaubt.");
      const worker = await serviceWorkerReady();
      browserSubscription =
        (await worker.pushManager.getSubscription()) ||
        (await worker.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: decodePublicKey(root.dataset.publicKey),
        }));
      const data = new FormData(form);
      const response = await fetch(root.dataset.subscribeUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
        body: JSON.stringify({
          ...browserSubscription.toJSON(),
          device_name: data.get("device_name"),
          categories: data.getAll("category"),
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Gerät konnte nicht registriert werden.");
      upsertDevice(payload.device, true);
      setStatus("Aktiv", true);
      submitButton.dataset.defaultLabel = "Einstellungen speichern";
    } catch (exception) {
      showError(exception.message || "Benachrichtigungen konnten nicht aktiviert werden.");
    } finally {
      setBusy(false, "");
    }
  });

  deviceList?.addEventListener("click", async (event) => {
    const revokeButton = event.target.closest("[data-revoke-subscription]");
    const testButton = event.target.closest("[data-test-subscription]");
    const renameButton = event.target.closest("[data-rename-subscription]");
    const preferencesButton = event.target.closest("[data-preferences-subscription]");
    const closeButton = event.target.closest("[data-close-dialog]");
    if (closeButton) {
      closeButton.closest("dialog")?.close();
      return;
    }
    if (renameButton) {
      const id = renameButton.dataset.renameSubscription;
      const dialog = renameButton
        .closest("[data-notification-device]")
        ?.querySelector(`[data-rename-form="${id}"]`)
        ?.closest("dialog");
      const dialogError = dialog?.querySelector("[data-rename-error]");
      if (dialogError) {
        dialogError.hidden = true;
        dialogError.textContent = "";
      }
      dialog?.showModal();
      return;
    }
    if (preferencesButton) {
      const id = preferencesButton.dataset.preferencesSubscription;
      const dialog = preferencesButton
        .closest("[data-notification-device]")
        ?.querySelector(`[data-preferences-form="${id}"]`)
        ?.closest("dialog");
      const dialogError = dialog?.querySelector("[data-preferences-error]");
      if (dialogError) {
        dialogError.hidden = true;
        dialogError.textContent = "";
      }
      dialog?.showModal();
      return;
    }
    if (!revokeButton && !testButton) return;
    clearError();
    const button = revokeButton || testButton;
    button.disabled = true;
    const id = revokeButton?.dataset.revokeSubscription || testButton.dataset.testSubscription;
    const action = revokeButton ? "revoke" : "test";
    try {
      const response = await fetch(`${root.dataset.subscriptionBaseUrl}${id}/${action}/`, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken() },
      });
      if (!response.ok) throw new Error();
      if (testButton) {
        setStatus("Test eingeplant", id === currentDeviceId);
        return;
      }
      deviceList.querySelector(`[data-notification-device="${id}"]`)?.remove();
      if (id === currentDeviceId) {
        await browserSubscription?.unsubscribe();
        browserSubscription = null;
        currentDeviceId = null;
        setStatus("Nicht aktiv");
      }
      ensureEmptyState();
    } catch (_exception) {
      showError(revokeButton ? "Gerät konnte nicht entfernt werden." : "Test konnte nicht eingeplant werden.");
    } finally {
      button.disabled = false;
    }
  });

  deviceList?.addEventListener("submit", async (event) => {
    const preferencesForm = event.target.closest("[data-preferences-form]");
    if (preferencesForm) {
      event.preventDefault();
      clearError();
      const id = preferencesForm.dataset.preferencesForm;
      const saveButton = preferencesForm.querySelector('button[type="submit"]');
      const preferencesError = preferencesForm.querySelector("[data-preferences-error]");
      preferencesError.hidden = true;
      preferencesError.textContent = "";
      saveButton.disabled = true;
      try {
        const data = new FormData(preferencesForm);
        const response = await fetch(`${root.dataset.subscriptionBaseUrl}${id}/preferences/`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
          body: JSON.stringify({ categories: data.getAll("category") }),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "Nachrichtenauswahl konnte nicht gespeichert werden.");
        preferencesForm.querySelectorAll('input[name="category"]').forEach((checkbox) => {
          checkbox.checked = payload.device.categories.includes(checkbox.value);
        });
        preferencesForm.closest("dialog").close();
      } catch (exception) {
        preferencesError.textContent =
          exception.message || "Nachrichtenauswahl konnte nicht gespeichert werden.";
        preferencesError.hidden = false;
      } finally {
        saveButton.disabled = false;
      }
      return;
    }

    const renameForm = event.target.closest("[data-rename-form]");
    if (!renameForm) return;
    event.preventDefault();
    clearError();
    const id = renameForm.dataset.renameForm;
    const saveButton = renameForm.querySelector('button[type="submit"]');
    const renameError = renameForm.querySelector("[data-rename-error]");
    renameError.hidden = true;
    renameError.textContent = "";
    saveButton.disabled = true;
    try {
      const data = new FormData(renameForm);
      const response = await fetch(`${root.dataset.subscriptionBaseUrl}${id}/rename/`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
        body: JSON.stringify({ device_name: data.get("device_name") }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Gerät konnte nicht umbenannt werden.");
      const item = renameForm.closest("[data-notification-device]");
      item.querySelector("[data-notification-device-name]").textContent = payload.device.device_name;
      renameForm.querySelector('input[name="device_name"]').value = payload.device.device_name;
      renameForm.closest("dialog").close();
    } catch (exception) {
      renameError.textContent = exception.message || "Gerät konnte nicht umbenannt werden.";
      renameError.hidden = false;
    } finally {
      saveButton.disabled = false;
    }
  });

  window.addEventListener("pwa:statechange", () => {
    if (
      "Notification" in window &&
      installationAllowsNotifications() &&
      submitButton &&
      Notification.permission !== "denied"
    ) {
      submitButton.disabled = false;
    }
  });

  initializeStatus().catch(() => {
    setStatus("Nicht verfügbar");
    showError("Der Benachrichtigungsdienst antwortet nicht. Lade die Seite neu und versuche es erneut.");
  });
})();
