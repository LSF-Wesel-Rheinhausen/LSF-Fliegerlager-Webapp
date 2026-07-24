document.querySelectorAll("[data-dialog-open]").forEach((button) => {
  button.addEventListener("click", () => {
    document.getElementById(button.dataset.dialogOpen)?.showModal();
  });
});

document.querySelectorAll("[data-dialog-close]").forEach((button) => {
  button.addEventListener("click", () => {
    button.closest("dialog")?.close();
  });
});

(function initDeploymentStatusPolling() {
  const panel = document.querySelector("[data-deployment-status-panel]");
  if (!panel) return;

  const url = panel.dataset.deploymentStatusUrl;
  if (!url) return;

  const activePhases = new Set(["preparing", "installing", "pulling", "restarting", "backup", "rollback"]);
  let currentPhase = panel.dataset.deploymentPhase || "";

  function updateUI(data) {
    if (!data) return;

    const messageEl = panel.querySelector("[data-deployment-message]");
    const badgeEl = panel.querySelector("[data-deployment-badge]");
    const errorEl = panel.querySelector("[data-deployment-error]");
    const rollbackErrorEl = panel.querySelector("[data-deployment-rollback-error]");
    const backupEl = panel.querySelector("[data-deployment-backup]");
    const backupPathEl = panel.querySelector("[data-deployment-backup-path]");

    if (data.message && messageEl) {
      messageEl.textContent = data.message;
    }

    if (data.phase && badgeEl) {
      badgeEl.textContent = data.phase;
      if (data.phase === "complete" || data.phase === "checked") {
        badgeEl.classList.add("status-badge--ok");
      } else {
        badgeEl.classList.remove("status-badge--ok");
      }
    }

    if (errorEl) {
      if (data.error) {
        errorEl.textContent = data.error;
        errorEl.style.display = "";
      } else {
        errorEl.style.display = "none";
      }
    }

    if (rollbackErrorEl) {
      if (data.rollback_error) {
        rollbackErrorEl.textContent = data.rollback_error;
        rollbackErrorEl.style.display = "";
      } else {
        rollbackErrorEl.style.display = "none";
      }
    }

    if (backupEl && backupPathEl) {
      if (data.backup) {
        backupPathEl.textContent = data.backup;
        backupEl.style.display = "";
      } else {
        backupEl.style.display = "none";
      }
    }

    const previousPhase = currentPhase;
    currentPhase = data.phase || currentPhase;

    if (previousPhase !== "complete" && currentPhase === "complete") {
      window.location.reload();
    }
  }

  async function pollStatus() {
    try {
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      if (response.ok) {
        const data = await response.json();
        updateUI(data);
      }
    } catch {
      // Ignore network or restart connection glitches during container restart
    }
  }

  if (activePhases.has(currentPhase)) {
    setInterval(pollStatus, 3000);
  }
})();
