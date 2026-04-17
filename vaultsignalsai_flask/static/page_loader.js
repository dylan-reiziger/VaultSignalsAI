(function () {
  if (window.VaultPageLoader?.settleIntroLoader) {
    window.VaultPageLoader.settleIntroLoader();
    return;
  }

  function waitForWindowLoad() {
    if (document.readyState === 'complete') {
      return Promise.resolve();
    }

    return new Promise((resolve) => {
      window.addEventListener('load', resolve, { once: true });
    });
  }

  function settleIntroLoader() {
    const loader = document.getElementById('appLoader');
    if (!loader) {
      return;
    }

    if (!document.body.classList.contains('loader-active')) {
      loader.remove();
      return;
    }

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const minimumDuration = prefersReducedMotion ? 250 : 2600;
    const maximumWait = prefersReducedMotion ? 700 : 4200;

    const hideLoader = () => {
      loader.classList.add('is-complete');
      document.body.classList.remove('loader-active');
      window.setTimeout(() => {
        loader.remove();
      }, prefersReducedMotion ? 120 : 680);
    };

    Promise.all([
      new Promise((resolve) => window.setTimeout(resolve, minimumDuration)),
      Promise.race([
        waitForWindowLoad(),
        new Promise((resolve) => window.setTimeout(resolve, maximumWait)),
      ]),
    ]).then(() => {
      window.requestAnimationFrame(hideLoader);
    });
  }

  window.VaultPageLoader = { settleIntroLoader };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', settleIntroLoader, { once: true });
  } else {
    settleIntroLoader();
  }
})();