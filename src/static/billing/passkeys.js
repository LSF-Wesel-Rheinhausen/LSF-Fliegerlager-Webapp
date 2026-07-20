(() => {
  "use strict";

  const statusElement = (container) => container.querySelector("[data-passkey-status]");

  const setStatus = (container, message) => {
    const status = statusElement(container);
    if (!status) return;
    status.textContent = message;
    status.hidden = !message;
  };

  const csrfToken = () => document.querySelector('input[name="csrfmiddlewaretoken"]')?.value ?? "";

  const decodeBase64url = (value) => {
    const padding = "=".repeat((4 - (value.length % 4)) % 4);
    const binary = window.atob(value.replace(/-/g, "+").replace(/_/g, "/") + padding);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  };

  const encodeBase64url = (value) => {
    const bytes = new Uint8Array(value);
    let binary = "";
    bytes.forEach((byte) => {
      binary += String.fromCharCode(byte);
    });
    return window.btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  };

  const registrationOptions = (options) => {
    if (window.PublicKeyCredential?.parseCreationOptionsFromJSON) {
      return window.PublicKeyCredential.parseCreationOptionsFromJSON(options);
    }
    return {
      ...options,
      challenge: decodeBase64url(options.challenge),
      user: {...options.user, id: decodeBase64url(options.user.id)},
      excludeCredentials: (options.excludeCredentials ?? []).map((credential) => ({
        ...credential,
        id: decodeBase64url(credential.id),
      })),
    };
  };

  const authenticationOptions = (options) => {
    if (window.PublicKeyCredential?.parseRequestOptionsFromJSON) {
      return window.PublicKeyCredential.parseRequestOptionsFromJSON(options);
    }
    return {
      ...options,
      challenge: decodeBase64url(options.challenge),
      allowCredentials: (options.allowCredentials ?? []).map((credential) => ({
        ...credential,
        id: decodeBase64url(credential.id),
      })),
    };
  };

  const credentialToJSON = (credential) => {
    const response = {
      clientDataJSON: encodeBase64url(credential.response.clientDataJSON),
    };
    if (credential.response.attestationObject) {
      response.attestationObject = encodeBase64url(credential.response.attestationObject);
      response.transports = credential.response.getTransports?.() ?? [];
    }
    if (credential.response.authenticatorData) {
      response.authenticatorData = encodeBase64url(credential.response.authenticatorData);
      response.signature = encodeBase64url(credential.response.signature);
      response.userHandle = credential.response.userHandle
        ? encodeBase64url(credential.response.userHandle)
        : null;
    }
    return {
      id: credential.id,
      rawId: encodeBase64url(credential.rawId),
      type: credential.type,
      authenticatorAttachment: credential.authenticatorAttachment,
      clientExtensionResults: credential.getClientExtensionResults(),
      response,
    };
  };

  const postJSON = async (url, payload = {}) => {
    const response = await window.fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
      },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "Passkey-Vorgang fehlgeschlagen.");
    return data;
  };

  const supported = () => Boolean(window.PublicKeyCredential && navigator.credentials);

  const loginButton = document.querySelector("[data-passkey-login]");
  loginButton?.addEventListener("click", async () => {
    setStatus(loginButton.parentElement, "");
    if (!supported()) {
      setStatus(loginButton.parentElement, "Passkeys werden von diesem Browser nicht unterstützt.");
      return;
    }
    loginButton.disabled = true;
    try {
      const options = await postJSON(loginButton.dataset.optionsUrl);
      const credential = await navigator.credentials.get({publicKey: authenticationOptions(options)});
      const result = await postJSON(loginButton.dataset.verifyUrl, {
        credential: credentialToJSON(credential),
        next: loginButton.dataset.next,
      });
      window.location.assign(result.redirect);
    } catch (error) {
      setStatus(loginButton.parentElement, error.message || "Anmeldung mit Passkey fehlgeschlagen.");
      loginButton.disabled = false;
    }
  });

  const registrationForm = document.querySelector("[data-passkey-register]");
  registrationForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    setStatus(registrationForm, "");
    if (!supported()) {
      setStatus(registrationForm, "Passkeys werden von diesem Browser nicht unterstützt.");
      return;
    }
    const submitButton = registrationForm.querySelector('button[type="submit"]');
    submitButton.disabled = true;
    try {
      const options = await postJSON(registrationForm.dataset.optionsUrl);
      const credential = await navigator.credentials.create({publicKey: registrationOptions(options)});
      await postJSON(registrationForm.dataset.verifyUrl, {
        credential: credentialToJSON(credential),
        name: registrationForm.elements.passkey_name.value,
      });
      window.location.reload();
    } catch (error) {
      setStatus(registrationForm, error.message || "Passkey konnte nicht registriert werden.");
      submitButton.disabled = false;
    }
  });

  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
})();
