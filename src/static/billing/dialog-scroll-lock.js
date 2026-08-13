(() => {
  const html = document.documentElement;
  let lockState;
  let transitionDepth = 0;

  const hasOpenDialog = () => Boolean(document.querySelector("dialog[open]"));

  const syncScrollLock = () => {
    if (transitionDepth > 0) return;
    if (hasOpenDialog()) {
      if (lockState || !document.body) return;
      const { scrollX, scrollY } = window;
      const body = document.body;
      lockState = {
        body: {
          left: body.style.left,
          overflow: body.style.overflow,
          position: body.style.position,
          right: body.style.right,
          top: body.style.top,
          width: body.style.width,
        },
        htmlOverflow: html.style.overflow,
        scrollX,
        scrollY,
      };
      body.style.position = "fixed";
      body.style.top = `-${scrollY}px`;
      body.style.left = `-${scrollX}px`;
      body.style.right = "0";
      body.style.width = "100%";
      body.style.overflow = "hidden";
      html.style.overflow = "hidden";
      html.classList.add("dialog-scroll-lock");
      return;
    }

    if (!lockState || !document.body) return;
    const { body, htmlOverflow, scrollX, scrollY } = lockState;
    const currentBody = document.body;
    currentBody.style.left = body.left;
    currentBody.style.overflow = body.overflow;
    currentBody.style.position = body.position;
    currentBody.style.right = body.right;
    currentBody.style.top = body.top;
    currentBody.style.width = body.width;
    html.style.overflow = htmlOverflow;
    html.classList.remove("dialog-scroll-lock");
    lockState = undefined;
    window.scrollTo(scrollX, scrollY);
  };

  const observer = new MutationObserver(syncScrollLock);
  observer.observe(html, { attributes: true, attributeFilter: ["open"], subtree: true, childList: true });
  document.addEventListener("close", syncScrollLock, true);
  document.addEventListener("DOMContentLoaded", syncScrollLock, { once: true });
  syncScrollLock();
  window.dialogScrollLock = {
    hold() {
      transitionDepth += 1;
      let active = true;
      return () => {
        if (!active) return;
        active = false;
        transitionDepth -= 1;
        if (transitionDepth === 0) queueMicrotask(syncScrollLock);
      };
    },
    transition(callback) {
      const release = this.hold();
      try {
        return callback();
      } finally {
        release();
      }
    },
  };

  window.announceToScreenReader = (message, priority = "polite") => {
    const targetId = priority === "assertive" ? "sr-announcer-assertive" : "sr-announcer-polite";
    const announcer = document.getElementById(targetId);
    if (announcer) {
      announcer.textContent = "";
      setTimeout(() => {
        announcer.textContent = message;
      }, 50);
    }
  };
})();
