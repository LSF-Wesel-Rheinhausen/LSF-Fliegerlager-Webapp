(() => {
  const root = document.documentElement;
  const workerUrl = root.dataset.pwaWorker;
  const workerScope = root.dataset.pwaScope;
  const installButtons = document.querySelectorAll("[data-pwa-install]");
  const installDialog = document.querySelector("[data-pwa-install-dialog]");
  const nativeInstallButton = installDialog?.querySelector("[data-pwa-native-install]");
  const installStatus = installDialog?.querySelector("[data-pwa-install-status]");
  let installPrompt;

  const isIos = () =>
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

  const isAndroid = () => /Android/.test(navigator.userAgent);

  const isStandalone = () =>
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true ||
    document.referrer.startsWith("android-app://");

  const setInstallStatus = (message) => {
    if (installStatus) installStatus.textContent = message;
  };

  const selectPlatformInstructions = () => {
    const platform = isIos() ? "ios" : isAndroid() ? "android" : "desktop";
    installDialog?.querySelectorAll("[data-pwa-install-platform]").forEach((section) => {
      section.hidden = section.dataset.pwaInstallPlatform !== platform;
    });
  };

  const updateInstallState = () => {
    const installed = isStandalone();
    root.dataset.pwaInstalled = installed ? "true" : "false";
    installButtons.forEach((button) => {
      button.hidden = installed;
    });
    document.querySelectorAll("[data-pwa-install-state]").forEach((element) => {
      element.textContent = installed ? "Installiert" : "Noch nicht installiert";
    });
    if (nativeInstallButton) nativeInstallButton.hidden = installed || !installPrompt;
    window.dispatchEvent(new CustomEvent("pwa:statechange", { detail: { installed } }));
  };

  if ("serviceWorker" in navigator && workerUrl && workerScope) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register(workerUrl, { scope: workerScope }).catch(() => {
        setInstallStatus("Die Offline-Funktion konnte nicht vorbereitet werden.");
      });
    });
  }

  selectPlatformInstructions();
  updateInstallState();

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
    setInstallStatus("Die App kann direkt über den Browser installiert werden.");
    updateInstallState();
  });

  installButtons.forEach((button) => {
    button.addEventListener("click", () => {
      selectPlatformInstructions();
      installDialog?.showModal();
    });
  });

  nativeInstallButton?.addEventListener("click", async () => {
    if (!installPrompt) {
      setInstallStatus("Nutze die Anleitung für dein Gerät.");
      return;
    }

    nativeInstallButton.disabled = true;
    setInstallStatus("Installationsdialog wird geöffnet …");
    try {
      await installPrompt.prompt();
      const choice = installPrompt.userChoice ? await installPrompt.userChoice : null;
      if (choice?.outcome === "dismissed") {
        setInstallStatus("Installation nicht abgeschlossen. Du kannst es erneut versuchen.");
      }
    } catch (_error) {
      setInstallStatus("Der Browser konnte den Installationsdialog nicht öffnen. Nutze die Anleitung unten.");
    } finally {
      installPrompt = undefined;
      nativeInstallButton.disabled = false;
      updateInstallState();
    }
  });

  window.addEventListener("appinstalled", () => {
    installPrompt = undefined;
    setInstallStatus("App installiert.");
    updateInstallState();
    installDialog?.close();
  });
})();
