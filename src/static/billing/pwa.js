(() => {
  const root = document.documentElement;
  const workerUrl = root.dataset.pwaWorker;
  const workerScope = root.dataset.pwaScope;
  if (!("serviceWorker" in navigator) || !workerUrl || !workerScope) return;

  window.addEventListener("load", () => {
    navigator.serviceWorker.register(workerUrl, {scope: workerScope}).catch(() => undefined);
  });

  let installPrompt;
  const installButtons = document.querySelectorAll("[data-pwa-install]");
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
    installButtons.forEach((button) => {
      button.hidden = false;
    });
  });
  installButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      if (!installPrompt) return;
      await installPrompt.prompt();
      installPrompt = undefined;
      installButtons.forEach((item) => {
        item.hidden = true;
      });
    });
  });
})();
